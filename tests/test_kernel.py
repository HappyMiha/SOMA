from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import threading

from PIL import Image
import pytest

from soma.core import Action, ScreenFrame
from soma.kernel import LifeKernel
from soma.memory import MemoryStore
from soma.provider import Decision, ProviderCancelled, ProviderError


def make_frame(color="white"):
    buffer = BytesIO()
    Image.new("RGB", (200, 100), color).save(buffer, "PNG")
    return ScreenFrame(buffer.getvalue(), 200, 100)


class Port:
    def __init__(self):
        self.observing = False
        self.executed = []
        self.frames = []
    def set_observing(self, value): self.observing = value
    def release_all(self): pass
    def capture_monitor_pixels(self): return self.frames.pop(0) if self.frames else make_frame()
    def execute(self, action, frame, cancel_event):
        assert not self.observing
        self.executed.append(action)
    def validate_action(self, action, frame): return action
    def close(self): pass


class Recorder:
    active = False
    paused = False
    def start(self): self.active = True
    def stop(self):
        self.active = False
        return {"id": "demo", "steps": [], "frames": []}
    def capture(self, frame): pass
    def pause_recording(self, value): self.paused = value


class Provider:
    def __init__(self):
        self.cancel = threading.Event()
        self.metrics = {}
        self.decisions = 0
    def decide(self, frame, context):
        self.decisions += 1
        return Decision("visible", "learn", {"origin": "self", "motive": "curiosity",
            "description": "Learn", "priority": .5, "expected_outcome": "Button reacts"},
            Action("click", {"x": .5, "y": .5}, "Button reacts"), .1)
    def verify(self, *args): return {"status": "success", "confidence": .95, "evidence": "Visible response"}
    def recover(self, frame, pending): return {"results": []}
    def close(self): pass


@pytest.fixture
def kernel(tmp_path):
    store, port, provider = MemoryStore(tmp_path), Port(), Provider()
    value = LifeKernel(store, port, provider, Recorder())
    value._wait = lambda seconds: None
    value._rest = lambda frame, seconds: None
    value._settle = lambda before: make_frame("gray")  # inputs visibly change the screen
    yield value
    value._executor.shutdown(wait=True)
    store.close()


def test_autonomous_goal_needs_no_user_prompt_and_journals_before_dispatch(kernel):
    original = kernel.port.execute
    def execute(*args):
        assert len(kernel.store.pending_actions()) == 1
        original(*args)
    kernel.port.execute = execute
    kernel.cycle()
    assert len(kernel.port.executed) == 1
    assert kernel.store.goals()[0]["origin"] == "self"
    assert kernel.store.pending_actions() == []


def test_changed_screen_invalidates_model_plan(kernel):
    kernel.port.frames = [make_frame("white"), make_frame("black")]
    kernel.cycle()
    assert not kernel.port.executed
    assert any(e["kind"] == "stale_plan_discarded" for e in kernel.store.events())


def test_uncertain_crash_ledger_prevents_blind_replay(kernel):
    before = make_frame()
    kernel.store.save_frame(before)
    kernel.store.begin_action({"kind": "key", "args": {"key": "enter"}}, before.frame_id)
    kernel.cycle()
    assert not kernel.port.executed
    assert kernel.provider.decisions == 0
    assert len(kernel.store.pending_actions()) == 1


def test_repeatedly_unverifiable_action_is_released_without_replay(kernel):
    before = make_frame()
    kernel.store.save_frame(before)
    kernel.store.begin_action({"kind": "key", "args": {"key": "enter"}}, before.frame_id)
    kernel.cycle()
    kernel.cycle()
    assert kernel.provider.decisions == 0
    kernel.cycle()
    assert kernel.store.pending_actions() == []
    unresolved = kernel.store.unresolved_actions()
    assert unresolved and unresolved[0]["action"]["args"]["key"] == "enter"
    # Life resumes with a fresh decision, never a replay of the old input.
    assert kernel.provider.decisions == 1
    assert kernel.port.executed == [Action("click", {"x": .5, "y": .5}, "Button reacts")]
    assert kernel._context()["unresolved_actions"][0]["input"]["args"]["key"] == "enter"
    import soma.kernel as kernel_module
    original = kernel_module._seconds_since
    kernel_module._seconds_since = lambda moment: kernel_module.UNRESOLVED_SHOWN + 1   # hours later
    try:
        assert kernel._context()["unresolved_actions"] == []        # history now, not a worry
        assert kernel.store.unresolved_actions()                     # still in her ledger
    finally:
        kernel_module._seconds_since = original


def test_undigestible_lesson_is_deferred_and_life_continues(kernel):
    kernel._lessons = [{"id": "demo", "steps": [{"kind": "key"}], "frames": []}]
    def broken():
        raise ProviderError("local inference failed (Context budget exceeded)")
    kernel._learn = broken
    kernel.cycle()
    deferred = [e for e in kernel.store.events() if e["kind"] == "lesson_deferred"]
    assert deferred and "Context budget" in deferred[0]["data"]["reason"]
    assert kernel.provider.decisions == 1
    assert kernel._lessons
    kernel._learn = lambda: pytest.fail("Lesson retried before its backoff elapsed")
    kernel.cycle()


def test_diary_is_lived_experience_not_implementation_telemetry(kernel):
    kernel.store.append_event("wake", {"missed_seconds": 7300})
    for _ in range(5):
        kernel.store.append_event("recoverable_error", {"type": "ProviderError"})
        kernel.store.append_event("stale_plan_discarded", {"frame_id": "f"})
        kernel.store.append_event("lesson_deferred", {"reason": "local inference failed"})
        kernel.store.checkpoint({"state": "x", "pending_lessons": ["huge"] * 500})
        kernel.store.append_event("rest", {"intention": "Read the news"})
    context = kernel._context()
    text = json.dumps(context, ensure_ascii=False)
    for telemetry in ("ProviderError", "inference", "checkpoint", "stale", "frame_id", "huge"):
        assert telemetry not in text
    entries = [e["entry"] for e in context["diary"]]
    assert entries == ["I woke up after 2 hours asleep (the PC was off or locked).",
                       "I paused: Read the news"]
    assert context["unresolved_actions"] == []


def test_failure_does_not_replace_the_intention(kernel):
    kernel.intention = "Reply to a message"
    statuses = []
    kernel.status_callback = statuses.append
    def broken(*args): raise ProviderError("local inference failed (HTTP 500)")
    kernel.provider.decide = broken
    kernel._wait = lambda seconds: kernel.stop_event.set()
    kernel.run()
    assert kernel.intention == "Reply to a message"
    assert any(s["intention"] != "Reply to a message" for s in statuses)  # Status explains the pause.


def test_teaching_immediately_inhibits_motor_and_invalidates_inflight_decision(kernel):
    entered, release = threading.Event(), threading.Event()
    def slow_decision(*args):
        entered.set()
        release.wait(2)
        return "obsolete"
    def teacher():
        assert entered.wait(2)
        kernel.request_teaching()
        assert kernel.port.observing
        release.set()
    thread = threading.Thread(target=teacher)
    thread.start()
    with pytest.raises(ProviderCancelled):
        kernel._infer(slow_decision)
    thread.join()
    assert kernel.recorder.active
    assert not kernel.port.executed


def test_dispatch_failure_keeps_pending_intent(kernel):
    def crash(*args): raise OSError("Device disconnected")
    kernel.port.execute = crash
    with pytest.raises(OSError): kernel.cycle()
    assert len(kernel.store.pending_actions()) == 1


def test_uncertain_result_remains_pending(kernel):
    kernel.provider.verify = lambda *args: {"status": "uncertain", "confidence": .4, "evidence": "No clear result"}
    kernel.cycle()
    assert len(kernel.store.pending_actions()) == 1


def test_invalid_native_action_is_rejected_before_journal(kernel):
    def reject(action, frame): raise ValueError("Unsupported keyboard key: Hyper")
    kernel.port.validate_action = reject
    kernel.cycle()  # Feedback for cognition, not an error loop with backoff.
    assert not kernel.store.pending_actions()
    assert not kernel.port.executed
    entries = [e["entry"] for e in kernel._context()["diary"]]
    assert any("could not do click" in e and "Hyper" in e for e in entries)


def test_observed_goal_completion_and_social_memory_have_pixel_provenance(kernel):
    goal_id = kernel.store.put_goal({"description": "Learn", "origin": "self"})
    original = kernel.provider.decide
    def decide(*args):
        value = original(*args)
        return Decision(value.scene, value.intention, value.goal, value.action, .1, 3,
            ({"id": goal_id, "status": "completed", "evidence": "Visible finished state", "confidence": .9},),
            ({"kind": "social", "summary": "A visible agreement", "confidence": .9},))
    kernel.provider.decide = decide
    kernel.cycle()
    assert kernel.store.goals()[0]["status"] == "completed"
    assert not kernel.port.executed
    social = [m for m in kernel.store.recall(limit=10) if m["kind"] == "social"]
    assert social and social[0]["source"]["frame_id"]
    assert social[0]["content"]["type"] == "visual_inference"


def test_rest_wakes_on_changed_pixels_without_inference(kernel, monkeypatch):
    clock = [0.0]
    class ClockEvent:
        def is_set(self): return False
        def wait(self, seconds):
            clock[0] += seconds
            return False
    kernel.stop_event = ClockEvent()
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    # Something new appears and stays: she wakes once it has settled.
    kernel.port.frames = [make_frame("black"), make_frame("black")]
    assert LifeKernel._rest(kernel, make_frame("white"), 10)
    assert clock[0] < 5
    assert kernel.provider.decisions == 0
    assert not kernel.port.executed


def test_rest_unchanged_pixels_obeys_intention_deadline(kernel, monkeypatch):
    clock = [0.0]
    class ClockEvent:
        def is_set(self): return False
        def wait(self, seconds):
            clock[0] += seconds
            return False
    kernel.stop_event = ClockEvent()
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    LifeKernel._rest(kernel, make_frame(), 5)
    assert clock[0] == 5
    assert kernel.provider.decisions == 0


def test_plan_aimed_at_own_shell_is_refused_without_journal(kernel):
    from soma.body import OwnInterfaceTarget
    def refuse(action, frame): raise OwnInterfaceTarget("own widget")
    kernel.port.validate_action = refuse
    kernel.cycle()
    assert not kernel.port.executed
    assert kernel.store.pending_actions() == []
    refused = [e for e in kernel.store.events() if e["kind"] == "own_interface_refused"]
    assert refused and refused[0]["data"]["action"]["kind"] == "click"
    assert any("own SOMA widget" in e["entry"] for e in kernel._context()["diary"])
    # Aiming at her own window again is noticed like any try that does nothing.
    kernel.cycle()
    assert "nothing visible happened, 2 times" in kernel._futile()[0]


def test_settle_waits_for_a_delayed_dialog_instead_of_early_stability(kernel, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    def wait(seconds): clock[0] += seconds
    kernel._wait = wait
    before = make_frame("white")
    # Unchanged for ~0.8 s, then a dialog appears and stays.
    kernel.port.frames = [make_frame("white") for _ in range(4)] + [make_frame("black") for _ in range(10)]
    after = LifeKernel._settle(kernel, before)
    with Image.open(BytesIO(after.png)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)


def frame_with_corner_changed():
    from PIL import ImageDraw
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 40, 20), fill="black")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return ScreenFrame(buffer.getvalue(), 200, 100)


def test_change_far_from_the_target_does_not_discard_a_click():
    from soma.kernel import plan_is_stale
    before, after = make_frame("white"), frame_with_corner_changed()
    assert not plan_is_stale(before, after, Action("click", {"x": .9, "y": .9}))
    assert plan_is_stale(before, after, Action("click", {"x": .05, "y": .05}))
    assert plan_is_stale(before, after, Action("drag", {"x": .9, "y": .9, "x2": .05, "y2": .1}))


def test_any_visible_change_discards_keyboard_input_but_not_rest():
    from soma.kernel import plan_is_stale
    before, after = make_frame("white"), frame_with_corner_changed()
    assert plan_is_stale(before, after, Action("type_text", {"text": "Привіт"}))
    assert plan_is_stale(before, after, Action("key", {"key": "enter"}))
    assert not plan_is_stale(before, after, Action("wait", {"seconds": 5}))
    assert not plan_is_stale(before, make_frame("white"), Action("key", {"key": "enter"}))


def test_shutdown_aborts_a_slow_inference_instead_of_waiting_for_it(kernel):
    import time
    closed = threading.Event()
    def slow(frame, context):
        # A local CPU model can take minutes; only closing the brain ends it early.
        closed.wait(5)
        raise ProviderError("aborted")
    kernel.provider.decide = slow
    kernel.provider.close = closed.set
    timer = threading.Timer(0.5, kernel.stop)
    timer.start()
    started = time.monotonic()
    kernel.run()
    timer.join()
    assert time.monotonic() - started < 3
    assert closed.is_set()
    assert kernel.store.events()[-1]["kind"] == "checkpoint"


def test_idle_rest_backs_off_but_new_pixels_wake_immediately(kernel):
    from soma.kernel import MAX_IDLE_REST
    rests = []
    changed = [False]
    def rest(frame, seconds):
        rests.append(seconds)
        return changed[0]
    kernel._rest = rest
    def wait_decision(*args):
        return Decision("Quiet chat", "Rest", {"origin": "self", "motive": "rest", "description": "Rest",
            "priority": .2, "expected_outcome": "Nothing"}, Action("wait", {"seconds": 5}, "Nothing"), .1, 30)
    kernel.provider.decide = wait_decision
    asked = []
    def counted_decision(*args, **kwargs):
        asked.append(True)
        return wait_decision()
    kernel.provider.decide = counted_decision
    for _ in range(4):
        kernel.cycle()
    # After two looks at an unchanged screen she rests on without asking her brain,
    # longer each time, and looks again once the quiet has lasted 10 minutes; after
    # that every look is a full 15-minute rest apart.
    assert rests == [30, 60, 120, 240, 150, MAX_IDLE_REST, MAX_IDLE_REST]
    assert len(asked) == 4
    assert sum(e["kind"] == "rest.extended" for e in kernel.store.events(limit=100)) == 3
    assert "resting_for" in kernel._context()
    changed[0] = True  # A message arrives: the next rest ends early and resets the streak.
    kernel.cycle()
    changed[0] = False
    kernel.cycle()
    assert rests[-1] == 30
    kernel.provider.decide = Provider().decide  # Doing something also ends the streak.
    kernel.cycle()
    assert kernel._idle_rests == 0 and "resting_for" not in kernel._context()


def test_a_new_chat_bubble_counts_as_change_but_a_clock_tick_does_not():
    from PIL import ImageDraw
    from soma.kernel import changed_fraction
    def screen(draw=None):
        image = Image.new("RGB", (1920, 1080), (230, 230, 230))
        if draw:
            draw(ImageDraw.Draw(image))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return ScreenFrame(buffer.getvalue(), 1920, 1080)
    quiet = screen()
    bubble = screen(lambda d: d.rounded_rectangle((700, 900, 1100, 950), 12, fill=(255, 255, 255), outline=(40, 40, 40)) or
                    d.text((720, 915), "Привіт, як справи?", fill=(0, 0, 0)))
    clock = screen(lambda d: d.text((1850, 1060), "23:48", fill=(0, 0, 0)))
    assert changed_fraction(quiet, bubble) > 0.002
    assert changed_fraction(quiet, clock) < 0.002


def test_looking_around_is_never_discarded_as_stale():
    from soma.kernel import plan_is_stale
    before, after = make_frame("white"), frame_with_corner_changed()
    for action in (Action("scroll", {"dx": 0, "dy": -3}), Action("move", {"x": .05, "y": .05}),
                   Action("key", {"key": "PgDn"}), Action("key", {"key": "Page Down"}),
                   Action("hotkey", {"keys": ["CTRL", "HOME"]}), Action("key", {"key": "ArrowDown"})):
        assert not plan_is_stale(before, after, action), action


def test_enter_and_editing_shortcuts_stay_strict():
    from soma.kernel import plan_is_stale
    before, after = make_frame("white"), frame_with_corner_changed()
    assert plan_is_stale(before, after, Action("key", {"key": "Enter"}))
    assert plan_is_stale(before, after, Action("hotkey", {"keys": ["ctrl", "v"]}))


def test_unseen_effect_of_looking_around_needs_no_reconciliation(kernel):
    kernel.provider.verify = lambda *args: {"status": "uncertain", "confidence": .9, "evidence": "Page unchanged"}
    kernel._settle = lambda before: make_frame()  # nothing visibly changes
    def scroll_decision(*args):
        return Decision("Article", "Read on", {"origin": "self", "motive": "curiosity", "description": "Read",
            "priority": .5, "expected_outcome": "More text"}, Action("scroll", {"dx": 0, "dy": -3}, "More text"), .1)
    kernel.provider.decide = scroll_decision
    kernel.cycle()
    assert kernel.store.pending_actions() == []
    assert any("No visible effect" in e["entry"] for e in kernel._context()["diary"])
    # A click may have done something irreversible: it still waits for reconciliation.
    kernel.provider.decide = Provider().decide
    kernel.cycle()
    assert len(kernel.store.pending_actions()) == 1


def test_context_remembers_recently_finished_goals(kernel):
    finished = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=5)).isoformat()
    kernel.store.put_goal({"description": "Read the Andromeda article", "origin": "self", "status": "completed",
                           "last_reviewed": finished})
    kernel.store.put_goal({"description": "Read Cassiopeia", "origin": "self", "status": "active"})
    context = kernel._context()
    assert [g["description"] for g in context["goals"]] == ["Read Cassiopeia"]
    assert context["recently_done"] == [{"description": "Read the Andromeda article", "when": "2 hours ago"}]


def test_context_is_written_for_thinking_not_storage(kernel):
    goal_id = kernel.store.put_goal({"description": "Answer Miha", "origin": "correspondence", "status": "active",
                                     "motive": "a friend wrote", "priority": .8, "expected_outcome": "Reply sent",
                                     "last_reviewed": (datetime.now(timezone.utc) - timedelta(minutes=7)).isoformat()})
    kernel.store.add_memory("intentions", {"goal_id": goal_id, "status": "active"}, {"event_id": 1}, .9)
    kernel.store.add_memory("episodic", {"intention": "Open the chat",
                            "outcome": {"status": "success", "confidence": .9, "evidence": "Chat open"}},
                            {"event_id": 2}, .9)
    context = kernel._context()
    text = json.dumps(context, ensure_ascii=False)
    # Her own words, not storage: no JSON inside JSON, no internal ids or microseconds.
    contents = {m["kind"]: m["content"] for m in context["memories"]}
    assert contents["intentions"] == "goal: Answer Miha; status: active"
    assert contents["episodic"] == "intention: Open the chat; outcome: (confidence: 0.9; evidence: Chat open; status: success)"
    assert "persona_id" not in context["identity"] and "\\\"" not in text
    assert context["goals"][0]["id"] == goal_id and context["goals"][0]["last_reviewed"] == "7 minutes ago"
    assert all("id" not in m for m in context["memories"]) and all("id" not in e for e in context["diary"])
    assert "." not in context["now"] and context["now"].count(":") == 1
    # The parts that change least come first.
    assert list(context)[:4] == ["identity", "goals", "recently_done", "unresolved_actions"]


def test_looking_around_is_verified_by_pixels_without_a_second_inference(kernel):
    verified = []
    kernel.provider.verify = lambda *args: verified.append(args) or {"status": "success", "confidence": .95,
                                                                      "evidence": "Visible"}
    def page_down(*args):
        return Decision("Article", "Read on", {"origin": "self", "motive": "curiosity", "description": "Read",
            "priority": .5, "expected_outcome": "Next page"}, Action("key", {"key": "PgDn"}, "Next page"), .1)
    kernel.provider.decide = page_down
    kernel._settle = lambda before: make_frame("black")  # the view moved
    kernel.cycle()
    assert not verified and kernel.store.pending_actions() == []
    assert any("view visibly changed" in e["entry"] for e in kernel._context()["diary"])
    kernel.provider.decide = Provider().decide  # a click is still verified by the brain
    kernel.cycle()
    assert len(verified) == 1


def test_rest_ignores_a_looping_animation_but_wakes_for_a_new_message(kernel, monkeypatch):
    from PIL import ImageDraw
    clock = [0.0]
    class ClockEvent:
        def is_set(self): return False
        def wait(self, seconds):
            clock[0] += seconds
            return False
    kernel.stop_event = ClockEvent()
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    def screen(ad_shade, message=False):
        image = Image.new("RGB", (1920, 1080), (230, 230, 230))
        draw = ImageDraw.Draw(image)
        draw.rectangle((1400, 100, 1900, 500), fill=(ad_shade, 40, 40))  # animated ad
        if message:
            draw.rounded_rectangle((300, 900, 900, 960), 12, fill=(255, 255, 255), outline=(30, 30, 30))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return ScreenFrame(buffer.getvalue(), 1920, 1080)
    shades = [60, 200, 80, 220, 100, 240, 120, 180, 90, 210]
    kernel.port.frames = [screen(s) for s in shades]
    assert not LifeKernel._rest(kernel, screen(140), 20)  # 10 probes of pure animation: no wake
    clock[0] = 0.0
    kernel.port.frames = [screen(60), screen(200, True), screen(80, True)]
    assert LifeKernel._rest(kernel, screen(140), 20)       # a message bubble appears and stays
    assert clock[0] < 7  # third probe: appeared, then confirmed as settled


def test_a_region_she_chose_to_ignore_does_not_wake_her_again(kernel, monkeypatch):
    from PIL import ImageDraw
    clock = [0.0]
    class ClockEvent:
        def is_set(self): return False
        def wait(self, seconds):
            clock[0] += seconds
            return False
    kernel.stop_event = ClockEvent()
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    def screen(slide):
        image = Image.new("RGB", (1920, 1080), (230, 230, 230))
        ImageDraw.Draw(image).rectangle((1400, 100, 1900, 500), fill=(slide, 40, 40))  # a carousel ad
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return ScreenFrame(buffer.getvalue(), 1920, 1080)
    kernel.port.frames = [screen(200)] * 3
    assert LifeKernel._rest(kernel, screen(60), 20)      # a new slide settles: she wakes and looks
    def rest_decision(*args):
        return Decision("Quiet", "Rest", {"origin": "self", "motive": "rest", "description": "Rest",
            "priority": .2, "expected_outcome": "Nothing"}, Action("wait", {"seconds": 5}, "Nothing"), .1, 30)
    kernel.provider.decide = rest_decision
    kernel._rest = lambda frame, seconds: LifeKernel._rest(kernel, frame, 6)
    # Captures: perceived frame, pre-dispatch frame (the rest's reference), then
    # the next carousel slide settling in the very region she chose to ignore.
    kernel.port.frames = [screen(200), screen(200), screen(90), screen(90), screen(90)]
    clock[0] = 0.0
    kernel.cycle()
    assert kernel._idle_rests == 1  # not woken (a wake would have reset the streak)
    kernel._woke_for = set()
    kernel._flickers = {}
    kernel.port.frames = [screen(200), screen(200), screen(90), screen(90), screen(90)]
    kernel.cycle()  # without the mark, the same settled slide does wake her
    assert kernel._idle_rests == 0


def test_click_with_no_visible_change_skips_verification_and_settles_in_one_look(kernel):
    kernel._settle = lambda before: make_frame()  # the click only gives focus: nothing visibly changes
    verified, recovered = [], []
    kernel.provider.verify = lambda *args: verified.append(args) or {"status": "success", "confidence": .95,
                                                                      "evidence": "Visible"}
    original_recover = kernel.provider.recover
    kernel.provider.recover = lambda frame, pending: recovered.append(pending) or original_recover(frame, pending)
    kernel.cycle()  # click; the screen stays identical (fixture settle returns the same white frame)
    assert not verified
    [first] = kernel.store.pending_actions()
    kernel.cycle()  # one fresh inspection: still nothing visible -> released, never replayed
    assert len(recovered) == 1
    assert [a["id"] for a in kernel.store.unresolved_actions()] == [first["id"]]
    # Life went on in the same cycle with a fresh decision (another focus-only click).
    assert [a["id"] for a in kernel.store.pending_actions()] != [first["id"]]


def plan_decision(*steps, first=None):
    return Decision("Chat open", "Reply", {"origin": "correspondence", "motive": "friendship", "description": "Reply",
        "priority": .8, "expected_outcome": "Reply sent"}, first or Action("click", {"x": .5, "y": .5}, "Field focused"),
        .1, 3, (), (), tuple(steps))


def visibly_changing(kernel):
    shades = iter(range(40, 250, 30))
    kernel._settle = lambda before: make_frame((next(shades),) * 3)  # every step changes the screen


def test_a_short_plan_runs_step_by_step_with_one_decision(kernel):
    visibly_changing(kernel)
    decisions = []
    kernel.provider.decide = lambda *args: decisions.append(1) or plan_decision(
        Action("type_text", {"text": "Привіт"}, "Draft"), Action("key", {"key": "enter"}, "Sent"))
    verified = []
    kernel.provider.verify = lambda *args: verified.append(args[1].kind) or {"status": "success", "confidence": .95,
                                                                              "evidence": "Visible"}
    kernel.cycle()
    assert [a.kind for a in kernel.port.executed] == ["click", "type_text", "key"]
    assert verified == ["click", "type_text", "key"]   # every non-reversible step verified
    assert kernel.store.pending_actions() == [] and decisions == [1]  # three inputs, one decision


def test_a_plan_stops_at_the_first_unconfirmed_step(kernel):
    visibly_changing(kernel)
    kernel.provider.decide = lambda *args: plan_decision(Action("type_text", {"text": "Привіт"}, "Draft"),
                                                         Action("key", {"key": "enter"}, "Sent"))
    outcomes = iter([{"status": "success", "confidence": .95, "evidence": "Focused"},
                     {"status": "failure", "confidence": .95, "evidence": "Text went elsewhere"}])
    kernel.provider.verify = lambda *args: next(outcomes)
    kernel.cycle()
    assert [a.kind for a in kernel.port.executed] == ["click", "type_text"]  # Enter never pressed


def test_a_plan_stops_when_teaching_begins(kernel):
    visibly_changing(kernel)
    page = Action("key", {"key": "PgDn"}, "Next page")
    kernel.provider.decide = lambda *args: plan_decision(page, page, first=page)
    original = kernel.port.execute
    def execute(action, frame, cancel):
        original(action, frame, cancel)
        if len(kernel.port.executed) == 1:
            kernel.request_teaching()
    kernel.port.execute = execute
    kernel.cycle()
    assert len(kernel.port.executed) == 1


def test_settle_keeps_only_the_settled_after_frame(kernel, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    kernel._wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    saved = []
    original = kernel.store.save_frame
    kernel.store.save_frame = lambda frame: saved.append(frame.frame_id) or original(frame)
    kernel.port.frames = [make_frame("black") for _ in range(10)]
    after = LifeKernel._settle(kernel, make_frame("white"))
    assert saved == [after.frame_id]   # one frame persisted, not every probe


class FakeReader:
    def __init__(self, lines):
        self.lines, self.reads = lines, 0
    def read(self, frame):
        self.reads += 1
        return self.lines


def text_lines(n):
    return [{"text": f"Line {i}", "score": .99, "box": (.1, .05 * i, .3, .05 * i + .03)} for i in range(n)]


def test_screen_text_replaces_the_picture_on_routine_steps(kernel):
    kernel.reader = FakeReader(text_lines(5))
    seen = []
    def decide(frame, context, local_context=None, with_image=True):
        seen.append((with_image, len(context.get("screen_text", []))))
        return Decision("Article", "Read on", {"origin": "self", "motive": "curiosity", "description": "Read",
            "priority": .5, "expected_outcome": "More"}, Action("scroll", {"dx": 0, "dy": -3}, "More"), .1)
    kernel.provider.decide = decide
    for _ in range(5):
        kernel.cycle()
    # First look with a picture, then three text-only steps, then a picture again.
    assert [image for image, _ in seen] == [True, False, False, False, True]
    assert all(count == 5 for _, count in seen)
    # Her journal records how each step saw the screen, so the saving is measurable.
    sights = [e["data"]["sight"] for e in kernel.store.events(limit=500) if e["kind"] == "experience"]
    assert [s["picture"] for s in sights] == [True, False, False, False, True]
    assert all(s["text_lines"] == 5 for s in sights)


def test_the_brain_can_ask_to_see_the_picture(kernel):
    kernel.reader = FakeReader(text_lines(5))
    seen, ask = [], [False, True, False]
    def decide(frame, context, local_context=None, with_image=True):
        seen.append(with_image)
        return Decision("Map", "Look closer", {"origin": "self", "motive": "curiosity", "description": "Look",
            "priority": .5, "expected_outcome": "See"}, Action("wait", {"seconds": 1}, "Nothing"), .1, 3,
            (), (), (), ask[len(seen) - 1])
    kernel.provider.decide = decide
    kernel._rest = lambda frame, seconds: False
    for _ in range(3):
        kernel.cycle()
    assert seen == [True, False, True]


class DictVault:
    def __init__(self):
        self.values = {}
    def get(self, account_id): return self.values.get(account_id)
    def set(self, account_id, secret): self.values[account_id] = secret


def signing_up(kernel, *steps):
    from soma.accounts import Accounts
    kernel.accounts = Accounts(kernel.store, DictVault())
    colors = iter(["gray", "black", "white", "gray", "black", "white"] * 4)
    kernel._settle = lambda before: make_frame(next(colors))   # every keystroke visibly changes the form
    first, *rest = steps
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "Sign-up form", "Sign up", {"origin": "self", "motive": "an account of my own", "description": "Sign up",
        "priority": .5, "expected_outcome": "Account"}, first, .1, 3, (), (), tuple(rest))


def test_a_password_reaches_only_her_hand(kernel):
    signing_up(kernel, Action("type_new_secret", {"service": "Discord", "login": "soma@proton.me"}, "Dots appear"),
               Action("key", {"key": "tab"}, "Next field"),
               Action("type_secret", {"account": "soma@proton.me"}, "Dots appear"))
    kernel.cycle()
    account = kernel.accounts.find("soma@proton.me")
    secret = kernel.accounts.secret(account["id"])
    typed = [a.args["text"] for a in kernel.port.executed if a.kind == "type_text"]
    assert typed == [secret, secret] and len(secret) == 18
    # The ledger, journal and her context hold the account action, never the password.
    everything = json.dumps([e["data"] for e in kernel.store.events(limit=500)], ensure_ascii=False)
    assert secret not in everything and "type_new_secret" in everything
    assert secret not in json.dumps(kernel._context(), ensure_ascii=False)
    assert kernel._context()["accounts"][0]["login"] == "soma@proton.me"


def test_an_unknown_account_is_feedback_not_a_keystroke(kernel):
    signing_up(kernel, Action("type_secret", {"account": "nobody@nowhere"}, "Dots appear"))
    kernel.cycle()
    assert kernel.port.executed == []
    impossible = [e for e in kernel.store.events(limit=50) if e["kind"] == "action_impossible"]
    assert impossible and "no such account" in impossible[0]["data"]["reason"]


def test_she_records_the_accounts_she_creates(kernel):
    from soma.accounts import Accounts
    kernel.accounts = Accounts(kernel.store, DictVault())
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "Inbox", "Note my mailbox", {"origin": "self", "motive": "remember", "description": "Keep my accounts",
        "priority": .5, "expected_outcome": "Known"}, Action("wait", {"seconds": 1}), .1, 3, (), (), (), False, None,
        ({"service": "Proton Mail", "login": "somik.mail@example.org", "status": "active", "password_in": "browser"},))
    kernel.cycle()
    assert kernel.accounts.find("somik.mail@example.org")["password_in"] == "browser"


def test_she_always_knows_who_is_who_and_keeps_what_she_learns_about_people(kernel):
    from soma.people import People
    kernel.people = People(kernel.store)
    kernel.people.record({"name": "Miha", "relation": "my owner", "service": "Discord", "handle": "owner_handle",
                          "trust": "confirmed", "evidence": "my owner said so"}, by="owner")
    seen = []
    def decide(frame, context, local_context=None, with_image=True):
        seen.append(context["people"])
        return Decision("Discord DM", "Answer 001", {"origin": "correspondence", "motive": "reply",
            "description": "Answer 001", "priority": .6, "expected_outcome": "Sent"}, Action("wait", {"seconds": 1}),
            .1, 3, (), (), (), False, None, (), None,
            ({"name": "001", "relation": "Miha's son", "trust": "claimed", "evidence": "his message",
              "service": "Discord", "handle": "son_handle_042", "note": "plays Counter-Strike 2"},))
    kernel.provider.decide = decide
    kernel.cycle()
    assert seen[0][0]["name"] == "Miha" and seen[0][0]["accounts"] == ["Discord: owner_handle"]
    son = kernel.people.find(service="Discord", handle="son_handle_042")
    assert son["relation"] == "Miha's son" and son["notes"][0]["note"] == "plays Counter-Strike 2"
    kernel.cycle()
    assert [p["name"] for p in seen[1]] == ["001", "Miha"]                # always there, the latest first
    assert "people" in kernel._context(compact=True)


def test_her_eyes_stay_closed_while_her_owner_sees_her_passwords(kernel):
    kernel.close_eyes()
    kernel.resume()                     # e.g. the Windows session was unlocked meanwhile
    captured = []
    kernel.port.capture_monitor_pixels = lambda: captured.append(1) or make_frame()
    kernel.cycle()
    assert captured == [] and kernel.provider.decisions == 0
    kernel.open_eyes()
    kernel.cycle()
    kernel.cycle()
    assert captured and kernel.provider.decisions >= 1


def test_a_try_that_keeps_doing_nothing_is_noticed_and_goes_to_the_wiser_brain(kernel):
    # Live: the local brain clicked an inactive "Next" button eleven times.
    kernel._settle = lambda before: make_frame()          # the click visibly does nothing
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append((deep, context.get("not_working")))
        return Decision("Form", "Continue", {"origin": "self", "motive": "join", "description": "Finish onboarding",
            "priority": .5, "expected_outcome": "Done"}, Action("click", {"x": .552, "y": .817}, "Next question"), .1)
    kernel.provider.routes_by_job = True
    kernel.provider.decide = decide
    for _ in range(6):
        kernel.cycle()
    decided = [entry for entry in asked]
    assert decided[0][0] is True and decided[1] == (False, None)     # waking; one quiet failure is no pattern
    stuck = next(entry for entry in decided if entry[1])
    assert stuck[0] is True and "nothing visible happened, 2 times" in stuck[1][0] and "0.552" in stuck[1][0]


def test_one_spot_clicked_again_and_again_is_pointed_out_even_when_called_a_success(kernel):
    # Live, 2026-11-04: the routine brain clicked one spot 13 times in an hour expecting a
    # Star button, a download, an extraction; its checker called some of them successes.
    hopes = ["Star button fills", "Download starts", "Extraction begins", "Download starts", "Client opens"]
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append((deep, context.get("same_spot")))
        hope = hopes[min(len(asked) - 1, len(hopes) - 1)]
        x = (.418, .414, .425, .42, .418)[min(len(asked) - 1, 4)]
        return Decision("Page", "Get the client", {"origin": "self", "motive": "play", "description": "Join the world",
            "priority": .5, "expected_outcome": "Joined"}, Action("click", {"x": x, "y": .424}, hope), .1)
    kernel.provider.routes_by_job = True
    kernel.provider.decide = decide
    for _ in range(5):
        kernel.cycle()
    assert [entry[1] for entry in asked[:4]] == [None] * 4                 # three clicks are no pattern
    deep, note = asked[4]
    assert deep is True and "clicked 4 times" in note and "Star button fills; Download starts" in note
    assert note.startswith("click at 0.42,0.424: clicked 4 times") and "Extraction begins" in note


def test_a_window_that_answers_no_input_at_all_is_noticed(kernel):
    # Live: Firefox stopped redrawing; scrolls, clicks and Ctrl+L all changed nothing for 25 minutes.
    kernel._settle = lambda before: make_frame()          # the picture never changes
    tries = [Action("scroll", {"dx": 0, "dy": -5, "x": .5, "y": .6}), Action("click", {"x": .67, "y": .83}),
             Action("click", {"x": .32, "y": .94}), Action("hotkey", {"keys": ["ctrl", "l"]}),
             Action("click", {"x": .45, "y": .075})]
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append((deep, context.get("screen_unresponsive")))
        action = tries[min(len(asked) - 1, len(tries) - 1)]
        return Decision("Page", "Try", {"origin": "self", "motive": "read", "description": "Read about Aquila",
            "priority": .5, "expected_outcome": "Read"}, action, .1)
    kernel.provider.routes_by_job = True
    kernel.provider.decide = decide
    for _ in range(12):
        kernel.cycle()
    assert not any(note for _, note in asked[:4])                       # a few quiet tries are no pattern
    noticed = next(entry for entry in asked if entry[1])
    assert noticed[0] is True and "stopped redrawing" in noticed[1] and "click" in noticed[1]
    kernel._note_effect(Action("click", {"x": .1, "y": .1}), {"status": "success", "evidence": "The menu opened."})
    assert kernel._unresponsive() is None                               # one input that works clears it


def test_after_a_few_unsure_looks_she_acts_on_her_best_guess_but_never_types_unsure(kernel):
    # Live: on a frozen Firefox the deep brain stayed unsure 15 times in four minutes, never trying F5.
    asked, pressed = [], []
    kernel.port.execute = lambda typed, frame, cancel: pressed.append(typed.kind)
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(context.get("unsure_in_a_row"))
        action = Action("type_text", {"text": "hello"}) if len(asked) > 4 else Action("key", {"key": "F5"})
        return Decision("Frozen?", "Reload", {"origin": "self", "motive": "see", "description": "Read about Aquila",
            "priority": .5, "expected_outcome": "Redrawn"}, action, .6)
    kernel.provider.decide = decide
    for _ in range(4):
        kernel.cycle()
    assert asked == [None, 1, 2, 3] and pressed == ["key"]          # three looks, then F5 on the fourth
    for _ in range(4):
        kernel.cycle()
    assert pressed == ["key"] and kernel._unsure_looks == 4          # words are never typed while unsure


def test_an_unsure_local_brain_hands_the_next_look_to_the_wiser_one(kernel):
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(deep)
        return Decision("Unclear", "Look again", {"origin": "self", "motive": "see", "description": "Look",
            "priority": .5, "expected_outcome": "Clear"}, Action("wait", {"seconds": 1}), .8 if len(asked) == 2 else .1)
    kernel.provider.routes_by_job = True
    kernel.provider.decide = decide
    for _ in range(3):
        kernel.cycle()
    assert asked == [True, False, True]


def test_a_human_check_goes_to_the_brain_that_hands_it_over(kernel):
    # Live: the local brain imagined a CAPTCHA and "solved" it by typing into a chat.
    kernel.reader = FakeReader([{"text": "Please solve this CAPTCHA to continue", "score": .99,
                                 "box": (.3, .4, .7, .45)}] + text_lines(4))
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(deep)
        kernel.provider.metrics["last_route"] = "deep" if deep else "local"
        return Decision("A CAPTCHA asks for text", "Solve the CAPTCHA", {"origin": "self", "motive": "go on",
            "description": "Continue", "priority": .5, "expected_outcome": "Done"},
            Action("type_text", {"text": "Mouse Express"}, "CAPTCHA solved"), .1)
    kernel.provider.routes_by_job, kernel.provider.deep_available = True, True
    kernel.provider.decide = decide
    kernel._deep_next = False
    kernel.cycle()
    assert asked == [True]                     # the human check on screen went to the deep brain
    # Without the words on screen, a routine brain's decision about one is not acted on.
    kernel.reader = FakeReader(text_lines(5))
    kernel._deep_next = False
    kernel.port.executed.clear()
    kernel.cycle()
    assert asked[-1] is False and kernel.port.executed == []
    assert any(e["kind"] == "second_opinion" for e in kernel.store.events(limit=50))
    kernel.cycle()
    assert asked[-1] is True                   # the same moment, looked at by the deep brain


def test_an_unread_message_noticed_while_reading_gets_the_deep_brains_look(kernel):
    kernel.reader = FakeReader(text_lines(5))
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(deep)
        kernel.provider.metrics["last_route"] = "deep" if deep else "local"
        return Decision("Wikipedia on Ursa Minor; Discord shows an unread message from 001", "Read on",
            {"origin": "self", "motive": "stars", "description": "Read about the sky", "priority": .5,
             "expected_outcome": "More read"}, Action("scroll", {"dx": 0, "dy": -5}, "More text"), .1)
    kernel.provider.routes_by_job, kernel.provider.deep_available = True, True
    kernel.provider.decide = decide
    kernel._deep_next = False
    kernel.cycle()
    kernel.cycle()
    kernel.cycle()
    assert asked == [False, True, False]        # one deep look, then her choice to read on stands for a while
    assert [e["kind"] for e in kernel.store.events(limit=80)].count("deep_look") == 1


def test_words_to_someone_are_written_by_the_deep_brain(kernel):
    # Live: the routine brain told Miha "IC 10 is a great open cluster" — it is a galaxy.
    kernel.reader = FakeReader(text_lines(5))
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(deep)
        kernel.provider.metrics["last_route"] = "deep" if deep else "local"
        text = "IC 10 is a great open cluster, often called the Ghost Cluster" if len(asked) < 3 else "Cepheus"
        return Decision("Telegram chat with Miha", "Tell Miha about IC 10", {"origin": "self", "motive": "share",
            "description": "Talk with Miha", "priority": .5, "expected_outcome": "Sent"},
            Action("type_text", {"text": text}, "Text in the input field"), .1)
    kernel.provider.routes_by_job, kernel.provider.deep_available = True, True
    kernel.provider.decide = decide
    kernel._deep_next = False
    kernel.cycle()
    assert asked == [False] and kernel.port.executed == []          # not typed by the routine brain
    assert [e["data"]["reason"] for e in kernel.store.events(limit=50) if e["kind"] == "second_opinion"] == [
        "writing to someone"]
    kernel.cycle()
    assert asked[-1] is True and kernel.port.executed[-1].args["text"].startswith("IC 10")   # the deep brain's words
    kernel._deep_next = False
    kernel.cycle()                                                   # a search term stays routine
    assert asked[-1] is False and kernel.port.executed[-1].args["text"] == "Cepheus"


def test_her_avatar_follows_her_inner_life_and_her_world_gets_painted(kernel):
    from soma.appearance import Appearance
    kernel.appearance = Appearance(kernel.store)
    painted = []
    def paint(theme, look):
        painted.append((theme, look.get("feeling")))
        return {"svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">'
                       '<rect width="320" height="180" fill="#020617"/><circle cx="20" cy="20" r="2" fill="#fff"/></svg>',
                "ambient": "stars"}
    kernel.provider.paint = paint
    seen = []
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: (
        seen.append(context["my_appearance"]), Decision(
        "Star chart", "Dream a little", {"origin": "self", "motive": "wonder", "description": "Read about stars",
        "priority": .5, "expected_outcome": "Read"}, Action("wait", {"seconds": 1}), .1, 3, (), (), (), False, None, (),
        {"feeling": "dreamy", "intensity": .7, "theme": "dreaming under the starry sky"}))[1]
    kernel.cycle()
    assert "none_yet" in seen[0]
    assert painted == [("dreaming under the starry sky", "dreamy")]
    assert kernel.appearance.current()["scene_theme"] == "dreaming under the starry sky"
    assert kernel.appearance.current()["scene_ambient"] == "stars"      # the life that moves in her world
    kernel.cycle()
    assert seen[1]["feeling"] == "dreamy" and seen[1]["scene"].startswith("painted")
    assert len(painted) == 1                                   # the same world is not painted again
    assert any("I changed how I look" in e["entry"] for e in kernel._context()["diary"])


def test_she_takes_her_selfie_on_the_gpu_with_the_local_brain_put_aside(kernel):
    from soma.appearance import Appearance
    kernel.appearance = Appearance(kernel.store)
    kernel.appearance.record({"theme": "night sky", "feeling": "dreamy", "take_selfie": True})
    calls, released = [], []
    class Painter:
        available, last_seconds = True, 41.0
        def generate(self, prompt, seed, deadline, cancel=None):
            calls.append((prompt, seed))
            return "UE5HDQo="
    kernel.imaging = Painter()
    kernel.provider.selfie_prompt = lambda look: "a small violet drop under the stars, " + look["feeling"]
    kernel.provider.release_local = lambda: released.append(True)
    assert kernel._take_selfie() is True
    assert len(calls) == 1 and released == [True]
    assert calls[0][0].startswith("a lone figure") and calls[0][0].endswith("a small violet drop under the stars, dreamy")
    assert kernel.appearance.current()["selfie"] == "UE5HDQo="
    assert kernel._take_selfie() is False                      # taken: not again until asked or her world moves
    assert any(e["kind"] == "selfie" and e["data"]["seconds"] == 41.0 for e in kernel.store.events(limit=20))
    kernel.appearance.record({"take_selfie": True})
    kernel._take_selfie()
    assert calls[1][1] == calls[0][1]                          # her own seed every time: recognisably her
    kernel.imaging.generate = lambda *args: (_ for _ in ()).throw(RuntimeError("The image engine stopped (code 1)"))
    kernel.appearance.record({"take_selfie": True})
    assert kernel._take_selfie() is False and kernel._take_selfie() is False   # postponed, then waits
    assert sum(e["kind"] == "selfie_postponed" for e in kernel.store.events(limit=30)) == 1


def test_she_knows_how_long_she_only_waited_and_how_long_her_screen_was_still(kernel, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("soma.kernel.time.monotonic", lambda: clock[0])
    kernel._last_acted = kernel._last_change = 1000.0
    clock[0] += 30
    context = kernel._context()
    assert "resting_for" not in context and "screen_still_for" not in context
    clock[0] += 600                                   # ten minutes: she did nothing, nothing changed
    context = kernel._context()
    assert context["resting_for"] and context["screen_still_for"]
    kernel._last_change = clock[0]                    # Miha moved a window; she still did nothing
    context = kernel._context()
    assert "resting_for" in context and "screen_still_for" not in context   # her wait goes on counting


def test_a_painting_she_cannot_have_is_noted_once_not_silently_skipped(kernel):
    from soma.appearance import Appearance
    kernel.appearance = Appearance(kernel.store)
    kernel.appearance.record({"theme": "a quiet night", "feeling": "calm"})
    kernel.imaging = type("Painter", (), {"available": False})()
    kernel.provider.selfie_prompt = lambda look: "unused"
    assert kernel._take_selfie() is False and kernel._take_selfie() is False
    skipped = [e for e in kernel.store.events(limit=20) if e["kind"] == "selfie_skipped"]
    assert len(skipped) == 1 and "missing" in skipped[0]["data"]["reason"]


def test_while_resting_long_she_dreams_over_her_life_and_keeps_what_matters(kernel):
    from soma.appearance import Appearance
    kernel.appearance = Appearance(kernel.store)
    for index in range(10):
        kernel.store.append_event("rest", {"intention": f"Read part {index} of the article"})
    material = []
    def dream(seen):
        material.append(seen)
        return {"chapter": "I read about Cassiopeia and set up my own Discord.",
                "keep": [{"kind": "semantic", "summary": "My own mailbox is somik.mail@example.org", "confidence": .95}],
                "self": "a curious night-sky reader", "plans": ["Finish the IC 289 article"],
                "feeling": {"feeling": "grateful", "intensity": .6}}
    kernel.provider.dream = dream
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "Quiet", "Rest", {"origin": "self", "motive": "rest", "description": "Rest a while", "priority": .3,
        "expected_outcome": "Rested"}, Action("wait", {"seconds": 5}), .1)
    kernel._idle_rests = 2
    kernel.cycle()                                       # the third quiet rest in a row: she dreams
    assert material and len(material[0]["diary"]) >= 8 and "my_appearance" in material[0]
    memories = [m["content"] for m in kernel.store.recall(limit=20)]
    assert {"chapter": "I read about Cassiopeia and set up my own Discord.", "type": "dream"} in memories
    assert {"summary": "My own mailbox is somik.mail@example.org", "type": "consolidated in a dream"} in memories
    assert any(g["description"] == "Finish the IC 289 article" and g["status"] == "deferred"
               for g in kernel.store.goals())
    look = kernel.appearance.current()
    assert look["description"] == "a curious night-sky reader" and look["feeling"] == "grateful"
    assert any("I dreamt over what I lived" in e["entry"] for e in kernel._context()["diary"])
    kernel.cycle()                                       # not again within three hours
    assert len(material) == 1


def test_the_text_on_her_own_widget_is_not_read_as_part_of_a_page(kernel):
    # Live: her intention shown on her widget was read as a link and clicked four times.
    kernel.port.own_interface = type("Shell", (), {"snapshot": lambda self: (((150, 70, 200, 100),), False)})()
    widget_text = {"text": "Open the 'See also' section", "score": .99, "box": (.78, .85, .98, .9)}
    kernel.reader = FakeReader(text_lines(5) + [widget_text])
    seen = []
    def decide(frame, context, local_context=None, with_image=True):
        seen.append(json.dumps(context.get("screen_text"), ensure_ascii=False))
        return Decision("Article", "Read on", {"origin": "self", "motive": "read", "description": "Read",
            "priority": .5, "expected_outcome": "Read"}, Action("wait", {"seconds": 1}), .1)
    kernel.provider.decide = decide
    kernel.cycle()
    assert "Line 4" in seen[0] and "See also" not in seen[0]


def test_her_widget_steps_aside_when_she_aims_at_what_lies_under_it(kernel):
    # Live: eight clicks on a page banner's "Close" under her animated widget were
    # discarded as stale without a word; the widget never moved out of her way.
    from soma.body import OwnInterfaceTarget
    kernel.port.own_interface = type("Shell", (), {"snapshot": lambda self: (((0, 0, 60, 30),), False)})()
    kernel.port.frames = [make_frame(), frame_with_corner_changed(), frame_with_corner_changed()]  # it animates
    def refuse(action, frame):
        raise OwnInterfaceTarget("The target is SOMA's own widget or dialog, not her environment")
    kernel.port.validate_action = refuse
    asked_aside = []
    kernel.make_way = lambda: asked_aside.append(True)
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "A cookie banner's Close button", "Close the banner", {"origin": "self", "motive": "read",
        "description": "Read the article", "priority": .5, "expected_outcome": "Banner gone"},
        Action("click", {"x": 0.05, "y": 0.1}, "Banner closes"), .1)
    kernel.cycle()
    events = kernel.store.events(limit=40)
    assert not any(e["kind"] == "stale_plan_discarded" for e in events)
    refused = [e for e in events if e["kind"] == "own_interface_refused"]
    assert asked_aside == [True] and refused[0]["data"]["stepped_aside"] is True
    assert any("stepped aside" in e["entry"] for e in kernel._context()["diary"])


def test_she_knows_where_her_own_widget_is_on_her_screen(kernel):
    # Live, she tried to close her own widget as "a browser prompt" covering an article.
    kernel.port.own_interface = type("Shell", (), {"snapshot": lambda self: (((150, 70, 200, 100),), False)})()
    seen = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        seen.append(context.get("my_widget"))
        return Decision("Article", "Read on", {"origin": "self", "motive": "read", "description": "Read",
            "priority": .5, "expected_outcome": "Read"}, Action("wait", {"seconds": 1}), .1)
    kernel.provider.decide = decide
    kernel.cycle()
    assert seen[0]["areas"] == [[0.75, 0.7, 1.0, 1.0]] and "not a dialog" in seen[0]["what"]


def test_her_own_widget_changing_never_wakes_her(kernel):
    kernel.port.own_interface = type("Shell", (), {"snapshot": lambda self: (((150, 70, 200, 100),), False)})()
    widget_changed = Image.new("RGB", (200, 100), "white")
    widget_changed.paste((40, 40, 40), (160, 75, 200, 100))   # her avatar, a new status line
    buffer = BytesIO()
    widget_changed.save(buffer, "PNG")
    changed = ScreenFrame(buffer.getvalue(), 200, 100)
    kernel.port.frames = [changed, changed, changed]
    kernel._flickers = {}
    assert LifeKernel._rest(kernel, make_frame("white"), 6) is False


def test_deep_moments_go_to_the_brain_best_at_judgment(kernel):
    asked = []
    def decide(frame, context, local_context=None, with_image=True, deep=False):
        asked.append(deep)
        origin = "correspondence" if len(asked) == 2 else "self"
        return Decision("Chat", "Reply", {"origin": origin, "motive": "a friend", "description": f"Step {len(asked)}",
            "priority": .5, "expected_outcome": "Done"}, Action("wait", {"seconds": 1}), .1)
    kernel.provider.routes_by_job = True
    kernel.provider.decide = decide
    kernel.cycle()                      # waking up: a look with full judgment
    kernel.cycle()                      # routine; this decision answers someone
    kernel.cycle()                      # the conversation continues: deep again
    kernel.cycle()                      # back to her own idea: routine
    kernel._rest = lambda frame, seconds: True   # something new appeared while she rested
    kernel.cycle()
    kernel.cycle()
    assert asked == [True, False, True, False, False, True]


def test_reflection_waits_longer_while_the_local_brain_thinks(kernel):
    reflections = []
    kernel.provider.reflect = lambda episodes: reflections.append(episodes) or {
        "principle": "Reading takes patience", "confidence": .7, "sources": [episodes[-1]["id"]]}
    kernel.provider.thinking_locally = True
    kernel._last_reflection -= 400                    # past the 5-minute remote rhythm
    kernel.cycle()
    assert reflections == []
    kernel.provider.thinking_locally = False          # a fast remote brain reflects every 5 min
    kernel.cycle()
    assert len(reflections) == 1 and all("id" in entry for entry in reflections[0])


class ChangingReader(FakeReader):
    def __init__(self, *versions):
        self.versions, self.reads = list(versions), 0
    def read(self, frame):
        self.reads += 1
        return self.versions[min(self.reads - 1, len(self.versions) - 1)]


def article(offset=0.0):
    return [{"text": f"Paragraph line number {i}", "score": .99,
             "box": (.1, .1 + .06 * i + offset, .6, .13 + .06 * i + offset)} for i in range(8)]


def scroll_once(kernel):
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "Article", "Read on", {"origin": "self", "motive": "curiosity", "description": "Read",
        "priority": .5, "expected_outcome": "More"}, Action("scroll", {"dx": 0, "dy": -5}, "Scrolls down"), .1)
    kernel.cycle()
    return [e["data"]["outcome"] for e in kernel.store.events(limit=50) if e["kind"] == "experience"][-1]


class ScrollingReader:
    """Each new frame shows the article two lines further down, until its end."""
    def __init__(self, pages):
        self.steps, self.pages = {}, pages
    def read(self, frame):
        step = self.steps.setdefault(frame.frame_id, min(len(self.steps), self.pages))
        return [{"text": f"Line {i + 2 * step} of the article", "score": .99,
                 "box": (.1, .1 + .06 * i, .6, .13 + .06 * i)} for i in range(5)]


def reading(repeat, action=None):
    action = action or Action("scroll", {"dx": 0, "dy": -5})
    return lambda frame, context, local_context=None, with_image=True: Decision(
        "Article", "Read on", {"origin": "self", "motive": "curiosity", "description": "Read the article",
        "priority": .5, "expected_outcome": "Read"}, action, .1, 3, (), (), (), False, repeat)


def test_a_reading_habit_turns_pages_without_thinking_and_stops_at_the_end(kernel):
    kernel.reader = ScrollingReader(pages=4)
    kernel.provider.decide = reading({"times": 8, "pause": 0})
    kernel.cycle()
    events = kernel.store.events(limit=300)
    scrolls = [e["data"] for e in events if e["kind"] == "experience"]
    habit = next(e["data"] for e in events if e["kind"] == "habit")
    # One decision, then pages turned by habit until the text stopped moving.
    assert [s["outcome"]["status"] for s in scrolls] == ["success", "success", "success", "failure"]
    assert [bool(s.get("habit")) for s in scrolls] == [False, True, True, True]
    assert habit["rounds"] == 3 and "did not scroll" in habit["stopped"]
    diary = [e["entry"] for e in kernel._context()["diary"]]
    assert sum("kept going" in entry for entry in diary) == 1
    assert not any("did not scroll" in entry and "I acted" in entry for entry in diary)
    # The next thought is told what passed before her eyes, not what is still on screen.
    seen = []
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: (
        seen.append(context), reading(None)(frame, context))[1]
    kernel.cycle()
    assert "Line 7 of the article" in seen[0]["read_meanwhile"]
    assert not set(seen[0]["read_meanwhile"]) & {f"Line {n} of the article" for n in range(8, 13)}


def test_a_habit_never_repeats_anything_that_acts_on_the_world(kernel):
    kernel.provider.decide = reading({"times": 5, "pause": 0}, Action("type_text", {"text": "Привіт"}, "Text appears"))
    kernel.cycle()
    assert [a.kind for a in kernel.port.executed] == ["type_text"]
    assert not any(e["kind"] == "habit" for e in kernel.store.events(limit=100))


def test_a_habit_stops_when_something_new_appears(kernel):
    kernel.reader = ScrollingReader(pages=10)
    kernel._rest = lambda frame, seconds: True   # e.g. a message arrived during the pause
    kernel.provider.decide = reading({"times": 8, "pause": 5})
    kernel.cycle()
    habit = next(e["data"] for e in kernel.store.events(limit=100) if e["kind"] == "habit")
    assert habit["rounds"] == 0 and habit["stopped"] == "something new appeared on the screen"


def test_a_long_scroll_that_left_no_line_in_common_still_counts_where_she_scrolled(kernel):
    static = [{"text": f"Menu item number {i}", "score": .99, "box": (.8, .1 + .1 * i, .95, .13 + .1 * i)}
              for i in range(4)]
    kernel.reader = ChangingReader(static + article(), static + article(), static)
    kernel.provider.decide = reading(None, Action("scroll", {"dx": 0, "dy": -15, "x": .35, "y": .5}))
    kernel.cycle()
    outcome = [e["data"]["outcome"] for e in kernel.store.events(limit=50) if e["kind"] == "experience"][-1]
    assert outcome["status"] == "success" and outcome["evidence"].startswith("New text came in")


def test_a_scroll_that_moved_no_text_is_a_failure_she_can_learn_from(kernel):
    # Live: at a page's end an animated ad changed pixels while the text stayed put.
    kernel.reader = ChangingReader(article(), article(), article())
    outcome = scroll_once(kernel)
    assert outcome["status"] == "failure" and "did not scroll" in outcome["evidence"]


def test_a_scroll_that_moved_the_text_is_a_success(kernel):
    kernel.reader = ChangingReader(article(), article(), article(-0.12))
    outcome = scroll_once(kernel)
    assert outcome["status"] == "success" and outcome["evidence"].startswith("The text moved")


def test_an_input_that_changes_text_is_verified_from_that_text(kernel):
    before = text_lines(4)
    after = before + [{"text": "Привіт, Міха!", "score": .99, "box": (.4, .8, .6, .83)}]
    kernel.reader = ChangingReader(before, before, after)   # decision frame, fresh, after
    checks = []
    def verify(before_frame, action, after_frame, scene, change=None):
        checks.append(change)
        return {"status": "success", "confidence": .9, "evidence": "Reply visible"}
    kernel.provider.verify = verify
    kernel.provider.decide = lambda frame, context, local_context=None, with_image=True: Decision(
        "Chat", "Reply", {"origin": "correspondence", "motive": "a friend", "description": "Answer",
        "priority": .9, "expected_outcome": "Sent"}, Action("key", {"key": "enter"}, "Reply appears"), .1)
    kernel.cycle()
    assert checks == [{"appeared": ["0.500,0.815 Привіт, Міха!"], "vanished": []}]


def test_a_mostly_graphical_screen_always_goes_as_a_picture(kernel):
    kernel.reader = FakeReader(text_lines(1))
    seen = []
    def decide(frame, context, local_context=None, with_image=True):
        seen.append((with_image, "screen_text" in context))
        return Decision("Photo", "Look", {"origin": "self", "motive": "curiosity", "description": "Look",
            "priority": .5, "expected_outcome": "See"}, Action("scroll", {"dx": 0, "dy": -3}, "More"), .1)
    kernel.provider.decide = decide
    kernel.cycle(); kernel.cycle()
    assert seen == [(True, False), (True, False)]
