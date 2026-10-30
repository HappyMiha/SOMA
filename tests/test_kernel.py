from io import BytesIO
import threading

from PIL import Image
import pytest

from soma.core import Action, ScreenFrame
from soma.kernel import LifeKernel
from soma.memory import MemoryStore
from soma.provider import Decision, ProviderCancelled


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
    def _request(self, prompt, frames): return {"results": []}
    def close(self): pass


@pytest.fixture
def kernel(tmp_path):
    store, port, provider = MemoryStore(tmp_path), Port(), Provider()
    value = LifeKernel(store, port, provider, Recorder())
    value._wait = lambda seconds: None
    value._rest = lambda frame, seconds: None
    value._settle = lambda before: make_frame()
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
    def reject(action, frame): raise ValueError("Unsupported native key")
    kernel.port.validate_action = reject
    with pytest.raises(ValueError): kernel.cycle()
    assert not kernel.store.pending_actions()
    assert not kernel.port.executed


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
    kernel.port.frames = [make_frame("black")]
    LifeKernel._rest(kernel, make_frame("white"), 10)
    assert clock[0] < 3
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
