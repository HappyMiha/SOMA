"""The life loop of the inhabitant holding the world's body: durable, with a visual
observation between every input. Code comments call the inhabitant "she" from the
time the persona was named SOMA; it is SOMIK, or whoever holds the body."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import json
import re
import threading
import time

from PIL import Image, ImageChops, ImageDraw, ImageStat

from soma.body import NAVIGATION_KEYS, OwnInterfaceTarget, canonical_key
from soma.vision import describe
from soma.core import Action, LifeState, utc_now
from soma.provider import (ProviderBudgetExhausted, ProviderCancelled, ProviderError, bounded_text,
                           confidence, in_space)


def visual_delta(before, after) -> float:
    with Image.open(BytesIO(before.png)) as first, Image.open(BytesIO(after.png)) as second:
        first = first.convert("RGB").resize((160, 100))
        second = second.convert("RGB").resize((160, 100))
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / (3 * 255)


MAX_IDLE_REST = 900


CHANGE_SIZE = (320, 180)
CHANGE_CELL = 10  # 32 x 18 cells over the whole screen


def change_mask(before, after) -> Image.Image:
    """Pixels (at 320x180) that visibly differ between two screenshots."""
    with Image.open(BytesIO(before.png)) as first, Image.open(BytesIO(after.png)) as second:
        first = first.convert("L").resize(CHANGE_SIZE)
        second = second.convert("L").resize(CHANGE_SIZE)
        return ImageChops.difference(first, second).point(lambda v: 255 if v > 24 else 0)


def changed_fraction(before, after, ignore_cells=frozenset()) -> float:
    """Share of the screen that visibly changed: sensitive to a new chat bubble
    or a taskbar badge, unlike a mean difference, yet blind to a ticking clock.
    Cells listed in ignore_cells (known animations) are left out."""
    mask = change_mask(before, after)
    blank = ImageDraw.Draw(mask)
    for column, row in ignore_cells:
        blank.rectangle((column * CHANGE_CELL, row * CHANGE_CELL,
                         (column + 1) * CHANGE_CELL - 1, (row + 1) * CHANGE_CELL - 1), fill=0)
    return mask.histogram()[255] / (CHANGE_SIZE[0] * CHANGE_SIZE[1])


def changed_cells(before, after) -> set:
    """Grid cells in which a noticeable part of the pixels changed."""
    mask = change_mask(before, after)
    cells = set()
    for row in range(CHANGE_SIZE[1] // CHANGE_CELL):
        for column in range(CHANGE_SIZE[0] // CHANGE_CELL):
            box = (column * CHANGE_CELL, row * CHANGE_CELL, (column + 1) * CHANGE_CELL, (row + 1) * CHANGE_CELL)
            if mask.crop(box).histogram()[255] >= 5:
                cells.add((column, row))
    return cells


def band_change(before, after, x, half_width=0.12) -> float:
    """Share of the vertical band around x (the column she scrolled) that changed."""
    mask = change_mask(before, after)
    left = max(0, int((x - half_width) * CHANGE_SIZE[0]))
    right = min(CHANGE_SIZE[0], int((x + half_width) * CHANGE_SIZE[0]) + 1)
    band = mask.crop((left, 0, right, CHANGE_SIZE[1]))
    return band.histogram()[255] / (band.width * band.height)


def region_delta(before, after, box) -> float:
    with Image.open(BytesIO(before.png)) as first, Image.open(BytesIO(after.png)) as second:
        first = first.convert("RGB").crop(box)
        second = second.convert("RGB").crop(box)
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / (3 * 255)


def is_navigation(action) -> bool:
    """Page/arrow/Home/End keys, alone or with Ctrl/Shift: moving the view, not acting on it."""
    keys = ([action.args["key"]] if action.kind == "key" else
            action.args["keys"] if action.kind == "hotkey" else [])
    names = {canonical_key(k) for k in keys}
    return bool(names & NAVIGATION_KEYS) and names <= NAVIGATION_KEYS | {"ctrl", "shift"}


def is_reversible(action) -> bool:
    """Repeating it by mistake changes nothing that matters: looking around, not acting on things."""
    return action.kind in {"move", "scroll", "wait"} or is_navigation(action)


def plan_is_stale(frame, fresh, action) -> bool:
    """Did the screen change where this plan acts?

    Looking around (move, scroll, page keys) is harmless to repeat and is
    verified from pixels right after, so it is never discarded. A pointer
    action depends on what is under its target, so only the neighbourhood of
    each target point must still look the same; a ticking clock or another
    window updating does not invalidate a click. Keyboard input goes wherever
    focus is, so any visible change invalidates it."""
    if is_reversible(action):
        return False
    points = []
    if action.kind in {"click", "double_click", "drag"}:
        points.append((round(action.args["x"] * (frame.width - 1)), round(action.args["y"] * (frame.height - 1))))
    if action.kind == "drag":
        points.append((round(action.args["x2"] * (frame.width - 1)), round(action.args["y2"] * (frame.height - 1))))
    if not points:
        return visual_delta(frame, fresh) > 0.015
    radius = max(48, round(0.04 * min(frame.width, frame.height)))
    for cx, cy in points:
        box = (max(0, cx - radius), max(0, cy - radius),
               min(frame.width, cx + radius + 1), min(frame.height, cy + radius + 1))
        if region_delta(frame, fresh, box) > 0.02:
            return True
    return False


# A step a site reserves for a human helper (her rules hand it to a person).
# Live, the small local brain imagined one and "solved" it by typing into a
# chat; such moments go to the brain best at judgment instead.
HUMAN_CHECK = re.compile(r"captcha|not a robot|verify (that )?you('| a)re (a )?human|are you (a )?human|"
                         r"я не робот|не робот|що ви людина|что вы человек", re.IGNORECASE)
WRITING_WORDS = 6  # typed text this long is words to someone, not a search term or an address
# Someone wrote: the routine brain noticing it hands the next look to the brain best at people.
UNREAD = re.compile(r"\bunread\b|new message|непрочитан|нове повідомлення|нових повідомлень", re.IGNORECASE)
UNREAD_LOOK_EVERY = 10 * 60  # at most this often, so choosing to finish reading first is respected


def _writes_words(decision) -> bool:
    """Whether a plan types words to someone (a message, a post, a reply)."""
    return any(step.kind == "type_text" and len(step.args.get("text", "").split()) >= WRITING_WORDS
               for step in (decision.action, *getattr(decision, "follow_up", ())))

DREAM_EVERY = 3 * 3600  # She dreams over her life at most every three hours, while resting long.
QUIET_RECHECK = 10 * 60  # An unchanged screen she chose to rest on twice is looked at again after this.
UNRESOLVED_SHOWN = 3 * 3600  # How long an unconfirmed input stays in her working context.
# Live, Firefox stopped redrawing for 25 minutes (its title still changed with the
# tab she picked) while she tried scrolls, clicks and Ctrl+L on a picture that never
# changed. This many different inputs in a row with no effect at all is noticed.
UNANSWERED_INPUTS = 4
# Live, on that frozen Firefox the deep brain stayed unsure 15 times in four
# minutes and every time looked again instead of trying F5 or Alt+Tab. After
# this many unsure looks in a row, another look will not make it clearer.
UNSURE_LOOKS = 3

RECOVERY_ATTEMPTS = 3
MIN_TEXT_LINES = 3      # Fewer readable lines: the screen is mostly graphical, send the picture.
TEXT_ONLY_STEPS = 3     # At most three decisions in a row without a picture.
RECOVERING = "Зберігаю неперервність і чекаю відновлення можливостей"


def brief(value, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _duration(seconds) -> str:
    seconds = max(0, int(seconds or 0))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return f"{seconds} seconds"


def _ago(timestamp) -> str:
    """How long ago, the way a person says it; an unreadable time stays as stored."""
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return str(timestamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    return "just now" if seconds < 60 else _duration(seconds) + " ago"


def _seconds_since(timestamp) -> float:
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


def _local_time(timestamp=None) -> str:
    """A moment on this PC's own clock, as its taskbar shows it."""
    try:
        moment = datetime.fromisoformat(timestamp) if timestamp else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return str(timestamp)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M %A (UTC%z)")


def _plain(value, goals=None) -> str:
    """Remembered content in plain words: no JSON quoting inside JSON, and an
    internal goal id becomes the goal it names. Every field is kept."""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if key == "goal_id" and goals and item in goals:
                key, item = "goal", goals[item]
            text = _plain(item, goals)
            parts.append(f"{key}: ({text})" if isinstance(item, dict) else f"{key}: {text}")
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_plain(item, goals) for item in value)
    return str(value)


def _action_words(action) -> str:
    if not isinstance(action, dict):
        return "an input"
    expected = action.get("expected")
    return action.get("kind", "input") + (f" expecting \"{expected}\"" if expected else "")


# What SOMA lived through, in her own words. Implementation telemetry (errors,
# checkpoints, frame captures, discarded plans, inference failures) is not part
# of her experience: a person at a PC does not perceive their own WAL journal.
DIARY = {
    # Steps of a habit are lived as one stretch of reading (the "habit" entry).
    "experience": lambda d: None if d.get("habit") else (
        f"I acted ({_action_words(d.get('action'))}). Result: "
        f"{d.get('outcome', {}).get('status', 'unknown')} - {d.get('outcome', {}).get('evidence', '')}"),
    "dream": lambda d: f"I dreamt over what I lived: {d.get('chapter', '')}",
    "selfie": lambda d: f"I had myself painted in my world (my avatar now): {d.get('prompt', '')}",
    "appearance.recorded": lambda d: ("I changed how I look" + (": " + d["description"] if d.get("description") else
                                      " (a picture of my own)" if d.get("picture") else "") + "."),
    "habit": lambda d: (f"I kept going ({', '.join(d.get('kinds', []))}) for {d.get('rounds', 0)} of "
                        f"{d.get('planned', 0)} rounds without stopping to think; it ended because "
                        f"{d.get('stopped', '')}"),
    "rest": lambda d: f"I paused: {d.get('intention', '')}",
    "wake": lambda d: f"I woke up after {_duration(d.get('missed_seconds'))} asleep (the PC was off or locked).",
    "sleep": lambda d: "I fell asleep: my PC session ended.",
    "skill_acquired": lambda d: f"A human showed me something; I learned the skill \"{d.get('name', '')}\".",
    "demonstration_stopped": lambda d: "A human finished showing me something through my widget.",
    "action.unresolved": lambda d: "I could not see whether an earlier input worked; I must not repeat it blindly.",
    "own_interface_refused": lambda d: (
        "My typing was refused: a SOMA dialog or menu had the keyboard. I click into the program first."
        if "focus" in str(d.get("reason", "")) else
        "My hand stopped: I aimed at my own SOMA widget. It stepped aside for a few minutes, so what "
        "was under it can be reached now." if d.get("stepped_aside") else
        "My hand stopped: I aimed at my own SOMA widget or dialog. That is not my world; "
        "I look at other programs instead."),
    "inspect_uncertain_scene": lambda d: "The screen was unclear, so I looked again before acting.",
    "thinking_budget_exhausted": lambda d: "I ran out of today's thinking budget and rested.",
    "plan_stopped": lambda d: f"I stopped my plan before {d.get('action', {}).get('kind', 'a step')}: {d.get('reason', '')}.",
    "action_impossible": lambda d: (f"My hands could not do {d.get('action', {}).get('kind', 'that')}: "
                                    f"{d.get('reason', '')}. I do it another way."),
}


class LifeKernel:
    def __init__(self, store, port, provider, recorder, status=None, reader=None, accounts=None, appearance=None,
                 imaging=None, people=None):
        self.store, self.port, self.provider, self.recorder = store, port, provider, recorder
        self.imaging = imaging  # The image model that paints her selfies (soma.imaging); None = none.
        self.people = people  # The people she knows and her notes about them (soma.people); None = none kept.
        self.reader = reader  # Machine vision over her own frames (soma.vision); None = images only.
        self.accounts = accounts  # Her accounts and password vault (soma.accounts); None = none kept.
        self.appearance = appearance  # Her own look (soma.appearance); None = no widget avatar.
        self._activity, self._focus = "waking", None  # What the widget shows her doing, and where.
        self._private = False  # The owner looks at her passwords: her eyes stay closed.
        self._text_only_streak = 0
        self._want_image = False
        self._sight = {}  # How the current decision saw the screen.
        self._passed = []  # Text that scrolled past her eyes since she last thought.
        # Each brain its own job: this moment goes to the brain best at judgment
        # (waking up, something new appeared while resting, a conversation).
        self._deep_next = True
        # Inputs that visibly did nothing, so a repeated futile try is noticed.
        self._no_effect = []  # (signature, monotonic time, words)
        self._unanswered = []  # (kind, monotonic time) of inputs in a row that changed nothing
        self._unsure_looks = 0  # unsure decisions in a row that looked again instead of acting
        self.status_callback = status or (lambda value: None)
        self.state = LifeState.BIRTH
        self.intention = "Прокидаюся й оглядаю свій комп’ютер"
        self.stop_event = threading.Event()
        self._teach = threading.Event()
        self._finish_teach = threading.Event()
        self._sleep = threading.Event()
        self._resume = threading.Event()
        self._epoch = 0
        self._last_demo_capture = 0
        self._lessons = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="soma-inference")
        self._last_frame = None
        self._last_reflection = time.monotonic()
        self._cycles = 0
        self._retry_delay = 3
        self._recovery_attempts = {}
        self._idle_rests = 0
        self._resting_since = 0.0
        self._last_acted = self._last_change = time.monotonic()
        self._flickers = {}  # Screen cells seen moving during the current quiet spell.
        self._woke_for = set()  # Cells whose settled change ended the last rest.
        self._lesson_failures = 0
        self._next_lesson_attempt = 0.0

    @property
    def _compact(self) -> bool:
        # A local CPU model has a small context window and pays per token.
        return getattr(self.provider, "local_only", False)

    def _diary(self, count, text_limit, cite=False) -> list[dict]:
        """Recent lived experience; reflection cites entries, so it also gets their ids."""
        entries, last = [], None
        for event in self.store.events(limit=200):
            narrate = DIARY.get(event["kind"])
            if narrate is None:
                continue
            entry = narrate(event["data"] if isinstance(event["data"], dict) else {})
            if entry is None:
                continue
            entry = brief(entry, text_limit)
            if entry == last:
                continue  # A run of identical rests is one fact.
            last = entry
            entries.append({"id": event["id"], "when": _ago(event["timestamp"]), "entry": entry} if cite else
                           {"when": _ago(event["timestamp"]), "entry": entry})
        return entries[-count:]

    def _context(self, compact=None) -> dict:
        """What she knows and remembers, written for thinking rather than storage.

        Internal ids, microsecond timestamps and JSON-inside-JSON cost a slow
        brain minutes and say nothing to her, so times are relative, memories
        are plain words and inputs use her own clicking coordinates; no fact is
        left out. Parts that change least come first, so a local brain can
        reuse what it already read in the previous moment.
        """
        compact = self._compact if compact is None else compact
        text_limit, memory_count, event_count, goal_count = (
            (280, 8, 10, 6) if compact else (1200, 18, 16, 16))
        space = getattr(getattr(self.provider, "config", None), "coordinate_space", "normalized")
        all_goals = self.store.goals()
        names = {goal["id"]: goal.get("description") for goal in all_goals if "id" in goal}
        recalled = self.store.recall(self.intention, limit=12) + self.store.recall(limit=6)
        memories = []
        for memory in {m["id"]: m for m in recalled}.values():
            # Raw demonstrations are visual evidence for the learner, not summaries
            # to repeatedly send in every ordinary cognitive context.
            if isinstance(memory["content"], dict) and "demonstration" in memory["content"]:
                continue
            memories.append({"kind": memory["kind"], "confidence": round(memory["confidence"], 2),
                             "content": brief(_plain(memory["content"], names), text_limit)})
        goals = []
        for goal in all_goals:
            if goal.get("status", "active") not in {"active", "deferred"}:
                continue
            shown = {key: goal.get(key) for key in ("id", "status", "origin", "motive", "description",
                     "priority", "expected_outcome") if key in goal}
            if goal.get("last_reviewed"):
                shown["last_reviewed"] = _ago(goal["last_reviewed"])
            goals.append(shown)
        # What she has already finished, so she builds on it instead of
        # unknowingly starting the same article or errand over again.
        done = [{"description": goal.get("description"), "when": _ago(goal.get("last_reviewed") or goal.get("updated_at"))}
                for goal in all_goals if goal.get("status") == "completed"][:goal_count]
        # Who she is now: her identity as born, with her name and birthday as recorded since
        # (SOMIK, an inhabitant of SOMA); the old pair of aliases would only confuse her.
        profile = self.store.profile() if hasattr(self.store, "profile") else self.store.identity()
        identity = {key: value for key, value in profile.items()
                    if key not in {"persona_id", "schema_version", "aliases"}}
        if "created_at" in identity:
            identity["created_at"] = _local_time(identity["created_at"])
        # An input she could not confirm guards against repeating it while it matters;
        # after a few hours it is history (live, "don't retype the uncertain message"
        # opened every rest of her evening). It stays in her ledger and diary.
        unresolved = [{"input": in_space(item["action"], space), "when": _ago(item["at"])}
                      for item in self.store.unresolved_actions() if _seconds_since(item["at"]) < UNRESOLVED_SHOWN]
        context = {"identity": identity}
        if self.appearance is not None:
            # Her own look, which she sees in her widget and may change.
            context["my_appearance"] = self.appearance.for_context()
        if self.accounts is not None:
            # Her own accounts are part of who she is: always known, never a password.
            context["accounts"] = self.accounts.for_context()
        if self.people is not None:
            # Who is who, always at hand: her memories came to mind only when her
            # intention happened to name the person.
            context["people"] = self.people.for_context(compact)
        context.update({"goals": goals[:goal_count],
                        "recently_done": done,
                        "unresolved_actions": unresolved,
                        "memories": memories[:memory_count],
                        "diary": self._diary(event_count, text_limit),
                        "now": _local_time()})
        # How long she has only waited since she last did something herself (a change
        # on the screen does not reset it: live, Miha's windows and Discord badges kept
        # it near zero, so "a long wait" never came), and how long the screen has been
        # still, so she can tell someone working at her PC from a PC left to her.
        now = time.monotonic()
        if self._idle_rests or now - self._last_acted >= 60:
            context["resting_for"] = _duration(now - self._last_acted)
        if now - self._last_change >= 60 and now - self._last_acted >= 60:
            # Only while she waits: changes made by others are watched during her rests, so
            # while she acts the figure only grows (live, "still for 39 minutes" read to her as
            # "I have scrolled for 40 minutes without new text").
            context["screen_still_for"] = _duration(now - self._last_change)
        return context

    def _status(self, detail="", intention=None, activity=None, focus=None):
        """For her widget: what she does (thinking, acting, resting…) and where she looks."""
        if activity is not None:
            self._activity, self._focus = activity, focus
        self.status_callback({"state": self.state.value, "intention": intention or self.intention,
                              "detail": detail, "cycles": self._cycles, "activity": self._activity,
                              "focus": self._focus, "inference": dict(self.provider.metrics)})

    def _checkpoint(self):
        self.store.checkpoint({"state": self.state.value, "intention": self.intention,
                               "last_seen": utc_now(), "cycles": self._cycles,
                               "last_frame_id": self._last_frame.frame_id if self._last_frame else None,
                               "pending_lessons": self._lessons})

    def request_teaching(self):
        # Synchronous input inhibition: never wait for the model/network to return.
        self.port.set_observing(True)
        self._epoch += 1
        self._teach.set()

    def finish_teaching(self):
        self._finish_teach.set()

    def set_sensitive(self, sensitive: bool):
        if self.recorder.active:
            self.recorder.pause_recording(sensitive)

    def suspend(self):
        self.port.set_observing(True)
        self._epoch += 1
        self._sleep.set()
        self._resume.clear()

    def resume(self):
        if self._private:
            return  # Not even an unlocked session reopens her eyes on her passwords.
        self._epoch += 1
        self._sleep.clear()
        self._resume.set()

    def close_eyes(self):
        """Her owner opened her accounts in SOMA's own window: she neither looks
        at the screen nor acts until it closes, so no password reaches a frame."""
        self._private = True
        self.suspend()

    def open_eyes(self):
        self._private = False
        self.resume()

    def _typed(self, action, create=False):
        """The keystrokes an account action stands for, taken from her vault.

        Only the hand gets the password; the ledger, journal, verification and
        every brain see the account name. While only validating, a new
        password is not made yet (create=False)."""
        if action.kind not in {"type_secret", "type_new_secret"}:
            return action
        if self.accounts is None:
            raise ValueError("I keep no password vault on this PC")
        if action.kind == "type_new_secret":
            if not create:
                return Action("type_text", {"text": "Aa1-placeholder"}, action.expected)
            _, secret = self.accounts.create_secret(action.args["service"], action.args["login"])
        else:
            account = self.accounts.find(action.args["account"])
            if account is None:
                raise ValueError("I have no such account in my records")
            secret = self.accounts.secret(account["id"])
            if not secret:
                raise ValueError("My vault holds no password for that account; my owner can add it")
        return Action("type_text", {"text": secret}, action.expected)

    def stop(self):
        self.port.set_observing(True)
        self.stop_event.set()
        self.provider.cancel.set()

    def _controls(self):
        def finish_demo(take_frame):
            capture_error = None
            try:
                if take_frame and not self.recorder.paused:
                    self.recorder.capture(self.port.capture_monitor_pixels())
            except Exception as error:
                capture_error = error
            finally:
                # Even a locked desktop or capture failure must stop global hooks.
                trace = self.recorder.stop()
            self._lessons.append(trace)
            self._epoch += 1
            self.state = LifeState.WAKE_RECOVER
            self._last_frame = None
            # Make the pending lesson durable before any autonomous input resumes.
            self._checkpoint()
            if not self._sleep.is_set() and not self.stop_event.is_set():
                self.port.set_observing(False)
            self._status("Демонстрацію збережено; узагальню навичку")
            if capture_error is not None:
                self.store.append_event("demonstration_capture_failed", {"id": trace["id"], "type": type(capture_error).__name__})
                raise capture_error

        if self._teach.is_set() and not self.recorder.active and not self._sleep.is_set() and not self.stop_event.is_set():
            self._teach.clear()
            self.recorder.start()
            self.state = LifeState.OBSERVE_AND_LEARN
            try:
                self._checkpoint()
                self._status("Запис демонстрації видимий; власне введення вимкнено",
                             intention="Дивлюся: покажіть мишею й клавіатурою, потім «Все, продовжуй»")
                self.recorder.capture(self.port.capture_monitor_pixels())
                self._last_demo_capture = time.monotonic()
            except Exception:
                finish_demo(False)
                raise
        if self.recorder.active:
            if self._finish_teach.is_set() or self._sleep.is_set() or self.stop_event.is_set():
                self._finish_teach.clear()
                finish_demo(not self._sleep.is_set() and not self.stop_event.is_set())
            elif not self.recorder.paused and time.monotonic() - self._last_demo_capture >= 0.4:
                try:
                    self.recorder.capture(self.port.capture_monitor_pixels())
                    self._last_demo_capture = time.monotonic()
                except Exception:
                    finish_demo(False)
                    raise
        if self._sleep.is_set() and self.state != LifeState.ASLEEP:
            self.state = LifeState.ASLEEP
            self.port.release_all()
            self._checkpoint()
            self._status("Графічний сеанс недоступний")
        elif (not self._sleep.is_set() and not self.stop_event.is_set() and
              not self.recorder.active and not self._teach.is_set() and
              (self.state == LifeState.ASLEEP or self._resume.is_set())):
            self._resume.clear()
            self.state = LifeState.WAKE_RECOVER
            self._last_frame = None
            self.port.set_observing(False)
            self._checkpoint()

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._controls()
            self.stop_event.wait(min(0.1, max(0, deadline - time.monotonic())))

    def _rest(self, frame, seconds) -> bool:
        """Wake early on visible change without spending inference on polling.

        Returns True when something new appeared on the screen."""
        if seconds >= 3:
            self._status("Відпочиваю й поглядаю на екран", activity="resting")
        deadline = time.monotonic() + seconds
        epoch = self._epoch
        next_probe = time.monotonic() + min(2, seconds)
        # Wake for something new that has settled (a message appears and stays),
        # not for regions that keep moving (a video, an animated ad): those are
        # learned as background for the rest of this quiet spell.
        previous = frame
        own = self._own_cells(frame)
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._controls()
            if self._epoch != epoch or self.recorder.active or self._sleep.is_set():
                return True
            if time.monotonic() >= next_probe:
                current = self.port.capture_monitor_pixels()
                if (current.geometry()["monitors"] != frame.geometry()["monitors"] or
                        (current.width, current.height) != (frame.width, frame.height)):
                    self._last_change = time.monotonic()
                    return True
                moving = changed_cells(previous, current)
                for cell in moving:
                    self._flickers[cell] = self._flickers.get(cell, 0) + 1
                animated = {cell for cell, count in self._flickers.items() if count >= 2} | own
                if changed_fraction(frame, current, frozenset(moving | animated)) > 0.002:
                    self._woke_for = changed_cells(frame, current) - moving - animated
                    self._last_change = time.monotonic()  # the screen changed without her
                    return True
                previous = current
                next_probe = time.monotonic() + 2
            self.stop_event.wait(min(.1, max(0, deadline - time.monotonic())))
        return False

    def _infer(self, function, *args):
        epoch = self._epoch
        future = self._executor.submit(function, *args)
        while not future.done():
            self._controls()
            if self.stop_event.wait(0.1):
                self.provider.cancel.set()
                raise ProviderCancelled("Inference cancelled during shutdown")
        result = future.result()
        self._controls()
        if epoch != self._epoch or self.recorder.active or self._sleep.is_set() or self.stop_event.is_set():
            raise ProviderCancelled("Discarded decision after lifecycle transition")
        return result

    def _capture(self):
        frame = self.port.capture_monitor_pixels()
        self.store.save_frame(frame)
        self._last_frame = frame
        return frame

    def _needs_image(self, frame) -> bool:
        """Text is enough for routine steps; the picture is sent when the brain
        asked for it, after a few text-only steps, or when the screen geometry
        changed (a rotated or new display)."""
        previous = getattr(self, "_last_image_geometry", None)
        geometry = (frame.width, frame.height, frame.monitors)
        needed = (self._want_image or self._text_only_streak >= TEXT_ONLY_STEPS or previous != geometry)
        if needed:
            self._last_image_geometry = geometry
        return needed

    def _settle(self, before):
        """Wait for the visible transition to finish, not a fixed sleep.

        Programs often react after a short delay (a dialog or page appears ~1 s
        later), so an unchanged screen is trusted only after a minimum window."""
        previous, stable, latest = before, 0, before
        started = time.monotonic()
        deadline = started + 6
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._wait(0.2)
            if self.recorder.active or self._sleep.is_set():
                raise ProviderCancelled("Verification interrupted")
            # Intermediate frames are only compared in memory; persisting each
            # one cost a PNG encode, a hash, a file and a journal event.
            latest = self.port.capture_monitor_pixels()
            stable = stable + 1 if visual_delta(previous, latest) < 0.003 else 0
            if stable >= 3 and time.monotonic() - started >= 1.2:
                break
            previous = latest
        if latest is not before:
            self.store.save_frame(latest)  # Only the settled AFTER frame is evidence.
            self._last_frame = latest
        return latest

    def _recover(self, frame, pending):
        result = self._infer(self.provider.recover, frame, pending)
        valid_ids = {p["id"] for p in pending}
        for item in result.get("results", []):
            if item.get("id") not in valid_ids or item.get("status") not in {"success", "failure", "uncertain"}:
                continue
            certainty = confidence(item.get("confidence"))
            evidence = bounded_text(item.get("evidence"))
            if certainty >= 0.8 and item["status"] != "uncertain":
                self.store.finish_action(item["id"], {"status": item["status"],
                    "confidence": certainty, "evidence": evidence, "recovered": True}, frame.frame_id)
        for item in self.store.pending_actions():
            attempts = self._recovery_attempts.get(item["id"], 0) + 1
            self._recovery_attempts[item["id"]] = attempts
            if attempts >= RECOVERY_ATTEMPTS:
                # Not a replay and not a claimed success: the input stays in the
                # context as unresolved so cognition does not repeat it blindly.
                self.store.release_unresolved_action(item["id"],
                    f"Outcome not visible after {attempts} inspections", frame.frame_id)
                self._recovery_attempts.pop(item["id"])
        return not self.store.pending_actions()

    def _learn(self):
        trace = self._lessons[0]
        from soma.core import Monitor, ScreenFrame
        from soma.demonstration import learning_evidence

        # Only paths written by the recorder inside SOMA's frame store are read.
        root = (self.store.data_dir / "frames").resolve()
        available = []
        for recorded in trace.get("frames", []):
            # Portable backups retain frame IDs; recorded absolute paths belong
            # to the old installation and are never followed.
            candidate = self.store.frame_path(recorded["frame_id"])
            if candidate and candidate.resolve().is_relative_to(root) and candidate.is_file():
                available.append((recorded, candidate))
        frames, mapping = [], []
        count = min(3 if self._compact else 8, len(available))
        indices = sorted({round(index * (len(available) - 1) / max(1, count - 1)) for index in range(count)})
        for index in indices:
            recorded, candidate = available[index]
            geometry = recorded.get("geometry", {})
            with Image.open(candidate) as image:
                frames.append(ScreenFrame(candidate.read_bytes(), image.width, image.height,
                    geometry.get("x", 0), geometry.get("y", 0),
                    tuple(Monitor(**monitor) for monitor in geometry.get("monitors", [])),
                    frame_id=recorded["frame_id"], captured_monotonic=recorded.get("captured_at", 0)))
            mapping.append({"image_index": len(frames) - 1, "frame_id": recorded["frame_id"],
                            "captured_at": recorded.get("captured_at"),
                            "geometry": {key: geometry.get(key) for key in ("width", "height", "x", "y")}})
        if not frames or not trace.get("steps"):
            self.store.append_event("demonstration_unusable", {"id": trace.get("id"),
                "reason": "no_retained_visual_input_evidence"})
            self._lessons.pop(0)
            self._checkpoint()
            return
        evidence = learning_evidence(trace, mapping)
        proposed = self._infer(self.provider.learn_demonstration, evidence, frames)
        # Retain semantic strategy fields only. No executable macro/action payload
        # from a demonstration or model response is admitted to the motor port.
        lesson = {key: bounded_text(proposed.get(key)) for key in ("name", "purpose", "recovery")}
        for key in ("principles", "visual_preconditions"):
            if not isinstance(proposed.get(key), list) or not 1 <= len(proposed[key]) <= 64:
                raise ProviderError("Invalid semantic demonstration strategy")
            lesson[key] = [bounded_text(value) for value in proposed[key]]
        if not isinstance(proposed.get("steps"), list) or not 1 <= len(proposed["steps"]) <= 64:
            raise ProviderError("Invalid semantic demonstration steps")
        lesson["steps"] = [{key: bounded_text(step.get(key))
                            for key in ("purpose", "visible_target", "expected_visual_result")}
                           for step in proposed["steps"]]
        lesson["confidence"] = confidence(proposed.get("confidence"))
        self.store.add_memory("procedural", lesson, {"demonstration": trace.get("id")},
                              confidence(lesson["confidence"]))
        self.store.append_event("skill_acquired", {"name": lesson["name"], "demonstration": trace.get("id")})
        self._lessons.pop(0)
        self._checkpoint()

    def cycle(self):
        self._controls()
        if self.recorder.active or self._sleep.is_set():
            self._wait(0.2)
            return
        if self._lessons and time.monotonic() >= self._next_lesson_attempt:
            self._status("Узагальнюю показану демонстрацію")
            try:
                self._learn()
                self._lesson_failures = 0
            except (ProviderCancelled, ProviderBudgetExhausted):
                raise
            except (ProviderError, ValueError, KeyError, TypeError) as exc:
                # A lesson the brain cannot digest yet stays pending in the
                # journal; it must not stop the rest of life.
                self._lesson_failures += 1
                delay = min(4 * 3600, 600 * 2 ** self._lesson_failures)
                self._next_lesson_attempt = time.monotonic() + delay
                self.store.append_event("lesson_deferred", {"id": self._lessons[0].get("id"),
                    "reason": str(exc) if isinstance(exc, ProviderError) else type(exc).__name__,
                    "attempt": self._lesson_failures, "retry_seconds": delay})
        frame = self._capture()
        pending = self.store.pending_actions()
        if pending and not self._recover(frame, pending):
            self.intention = "Перевіряю незавершену дію за екраном; повтор заборонено"
            self._status("Результат попередньої дії ще невідомий")
            self._wait(10)
            return
        self.state = LifeState.AUTONOMOUS
        self._status("Дивлюся на екран і обмірковую, чим зайнятися", activity="thinking")
        context = self._context()
        recalled = self.store.recall(self.intention, limit=12) + self.store.recall(limit=6)
        config = getattr(self.provider, "config", None)
        local_context = self._context(compact=True) if config is not None and config.mode == "hybrid" else None
        widget = self._own_widget_area(frame, getattr(config, "coordinate_space", "normalized"))
        if widget:
            # Where her own widget is on this screen, so she knows it for what it is (live, she
            # tried to close it as "a browser prompt" covering the article she was reading).
            for target in (context, local_context):
                if target is not None:
                    target["my_widget"] = widget
        # Machine vision: read the screen's text with positions on this PC. On
        # routine steps that text replaces the screenshot sent to the brain;
        # the picture still goes when it is needed (see _needs_image).
        with_image, lines = True, []
        if self.reader is not None:
            # Her own widget's text (her name, her intention) is not a page: live, the routine
            # brain read her intention there as a link and clicked it four times in an hour.
            lines = self._outside_own_widget(self._infer(self.reader.read, frame), frame)
            if len(lines) >= MIN_TEXT_LINES:
                space = getattr(config, "coordinate_space", "normalized")
                context["screen_text"] = describe(lines, space, 60 if self._compact else 160)
                if local_context is not None:
                    local_context["screen_text"] = describe(lines, space, 60)
                with_image = self._needs_image(frame)
        if self._passed:
            # What she read while a habit turned the pages, without the lines
            # still on the screen (screen_text already shows those).
            on_screen = {line["text"] for line in lines}
            read = [text for text in self._passed if text not in on_screen]
            if read:
                context["read_meanwhile"] = read[-60:]
                if local_context is not None:
                    local_context["read_meanwhile"] = read[-30:]
        if any(HUMAN_CHECK.search(line["text"]) for line in lines):
            self._deep_next = True  # A human check on screen: the brain that knows to hand it over.
        futile = self._futile()
        if futile:
            # Repeating what visibly does nothing: say so plainly, and let the
            # brain best at judgment look at it. Trying again stays her choice.
            context["not_working"] = futile
            if local_context is not None:
                local_context["not_working"] = futile
            self._deep_next = True
        if self._unsure_looks:
            context["unsure_in_a_row"] = self._unsure_looks
            if local_context is not None:
                local_context["unsure_in_a_row"] = self._unsure_looks
        stuck = self._unresponsive()
        if stuck:
            context["screen_unresponsive"] = stuck
            if local_context is not None:
                local_context["screen_unresponsive"] = stuck
            self._deep_next = True
        deep = (True,) if self._deep_next and getattr(self.provider, "routes_by_job", False) is True else ()
        if local_context is not None:
            # If the remote brain is unavailable, the small local one must get a
            # context that fits its window rather than refusing every decision.
            decision = self._infer(self.provider.decide, frame, context, local_context, with_image, *deep)
        elif not with_image or deep:
            decision = self._infer(self.provider.decide, frame, context, None, with_image, *deep)
        else:
            decision = self._infer(self.provider.decide, frame, context)
        routed = getattr(self.provider, "metrics", {}).get("last_route", "")
        about = " ".join((decision.scene, decision.intention, decision.action.expected))
        reason = ("human check" if HUMAN_CHECK.search(about) else
                  "writing to someone" if _writes_words(decision) else None)
        if routed and routed != "deep" and reason and getattr(self.provider, "deep_available", False) is True:
            # A routine brain deciding about a human check, or about to write words
            # to someone (live, it told Miha "IC 10 is an open cluster" — a galaxy):
            # not acted on; the brain best at judgment looks at the same moment first.
            self.store.append_event("second_opinion", {"reason": reason, "frame_id": frame.frame_id,
                                                       "brain": routed})
            self._deep_next = True
            return
        # A conversation keeps the brain best at judgment until it ends.
        self._deep_next = decision.goal.get("origin") == "correspondence"
        if (routed and routed != "deep" and not self._deep_next and UNREAD.search(decision.scene)
                and time.monotonic() - getattr(self, "_last_unread_look", -UNREAD_LOOK_EVERY) >= UNREAD_LOOK_EVERY):
            # Live, a red unread badge sat in her scenes for 20 minutes while the routine
            # brain kept reading Wikipedia: someone wrote, so the next look is the deep one.
            self._last_unread_look = time.monotonic()
            self._deep_next = True
            self.store.append_event("deep_look", {"reason": "someone wrote", "frame_id": frame.frame_id})
        self._text_only_streak = 0 if with_image else self._text_only_streak + 1
        self._passed = []  # She has now thought about what she read.
        self._want_image = bool(getattr(decision, "need_image", False))
        self._sight = {"picture": with_image, "text_lines": len(lines),
                       "brain": getattr(self.provider, "metrics", {}).get("last_route", "")}
        self.intention = decision.intention
        known_goals = {g["id"]: g for g in self.store.goals()}
        if decision.uncertainty <= 0.5:
            for update in decision.goal_updates:
                if update["confidence"] >= 0.8 and update["id"] in known_goals:
                    revised = {**known_goals[update["id"]], "status": update["status"],
                        "last_reviewed": utc_now(), "evidence": {"frame_id": frame.frame_id,
                        "summary": update["evidence"], "confidence": update["confidence"]}}
                    self.store.put_goal(revised)
                    self.store.add_memory("intentions", {"goal_id": revised["id"], "status": revised["status"]}, revised["evidence"], update["confidence"])
            recent_contents = {json.dumps(m["content"], sort_keys=True, ensure_ascii=False) for m in recalled}
            for update in decision.memory_updates:
                content = {"summary": update["summary"], "type": "visual_inference"}
                if update["confidence"] >= 0.8 and json.dumps(content, sort_keys=True, ensure_ascii=False) not in recent_contents:
                    self.store.add_memory(update["kind"], content,
                        {"frame_id": frame.frame_id, "observation": decision.scene}, update["confidence"])
            change = getattr(decision, "appearance_update", None)
            if change and self.appearance is not None:
                try:
                    self.appearance.record(change, frame)
                    self._status("Змінила свій вигляд", activity="thinking")
                except ValueError:
                    pass  # A look she cannot take (no picture yet) changes nothing.
            if self.accounts is not None:
                for update in getattr(decision, "account_updates", ()):
                    try:
                        self.accounts.record(update["service"], update["login"], status=update.get("status"),
                                             note=update.get("note"), password_in=update.get("password_in"))
                    except ValueError:
                        pass  # A malformed record changes nothing she knew.
            self._record_people(getattr(decision, "people_updates", ()))
        goal = dict(decision.goal)
        # Keep an existing intention instead of manufacturing a new goal every tick.
        matching = next((g for g in self.store.goals() if g.get("description") == goal["description"]), None)
        if matching:
            goal["id"] = matching["id"]
        revised_status = next((u["status"] for u in decision.goal_updates
                               if u["id"] == goal.get("id") and u["confidence"] >= 0.8), "active")
        goal.update(status=revised_status, next_action=decision.action.to_dict(),
                    evidence={"frame_id": frame.frame_id, "scene": decision.scene}, last_reviewed=utc_now())
        goal_id = self.store.put_goal(goal)
        self._status(decision.scene)
        if revised_status != "active":
            self._unsure_looks = 0
            self._checkpoint()
            self._wait(decision.reconsider_after)
            return
        # Unsure, she looks again first; after a few looks she acts on her best
        # guess, as people do, except typing words into something unclear.
        if decision.uncertainty > 0.5 and (self._unsure_looks < UNSURE_LOOKS or decision.action.kind == "type_text"):
            self._unsure_looks += 1
            self.store.append_event("inspect_uncertain_scene", {"frame_id": frame.frame_id,
                "uncertainty": decision.uncertainty, "goal_id": goal_id})
            self._deep_next = True  # Unsure: the next look is by the brain best at judgment.
            self._rest(frame, decision.reconsider_after)
            return
        self._unsure_looks = 0
        # Observe immediately before dispatch: never act on a screen that changed
        # while a slow provider was thinking. Geometry changes also invalidate it.
        fresh = self._capture()
        # A target on her own animated widget is judged by the own-window check below,
        # not discarded as stale (live, eight such clicks vanished without a word).
        on_own = self._aims_at_own_widget(decision.action, fresh)
        if ((frame.width, frame.height, frame.x, frame.y, frame.monitors) !=
                (fresh.width, fresh.height, fresh.x, fresh.y, fresh.monitors) or
                (not on_own and plan_is_stale(frame, fresh, decision.action))):
            self.store.append_event("stale_plan_discarded", {"frame_id": frame.frame_id,
                                                           "fresh_frame_id": fresh.frame_id})
            return
        self._controls()
        if self.recorder.active or self._teach.is_set() or self._sleep.is_set() or self.stop_event.is_set():
            return
        action = Action.parse(decision.action.to_dict())
        if action.kind == "wait":
            self.store.append_event("rest", {"goal_id": goal_id, "intention": self.intention,
                                             "sight": self._sight})
            self._checkpoint()
            # Resting is not thinking: while nothing changes, each further rest
            # lasts longer (1, 2, 4, 8, 15 min). Any new pixels, such as a message
            # arriving, still wake the inhabitant within seconds, without inference.
            if not self._idle_rests:
                self._resting_since, self._quiet_rested = time.monotonic(), 0.0
            # She looked at what woke her and chose to rest on: that region is
            # background for the rest of this quiet spell.
            for cell in self._woke_for:
                self._flickers[cell] = max(2, self._flickers.get(cell, 0))
            self._woke_for = set()
            self._idle_rests += 1
            seconds = max(action.args["seconds"], decision.reconsider_after)
            if self._idle_rests > 1:
                seconds = max(seconds, min(MAX_IDLE_REST, 60 * 2 ** (self._idle_rests - 2)))
            if self._paint_world():
                fresh = self._capture()  # Rest on the screen with her new scene already on it.
            if self._take_selfie():
                fresh = self._capture()
            if self._idle_rests >= 3 and self._dream():
                fresh = self._capture()  # Her look may have changed with the dream.
            while True:
                self._quiet_rested = getattr(self, "_quiet_rested", 0.0) + seconds
                if self._rest(fresh, seconds):
                    self._idle_rests = 0
                    self._deep_next = True  # Something new appeared: perhaps someone wrote.
                    return
                # Nothing new appeared during the whole rest. Once she has chosen to rest
                # on an unchanged screen twice, asking again before anything changes only
                # repeats her answer (live: eight deep looks in 14 minutes at a quiet
                # chat), so she rests on, longer each time, until something changes or
                # QUIET_RECHECK has passed and plans that wait on time get their turn.
                quiet = max(time.monotonic() - self._resting_since, self._quiet_rested)
                if self._idle_rests < 2 or quiet >= QUIET_RECHECK or self.stop_event.is_set():
                    return
                self._idle_rests += 1
                seconds = min(MAX_IDLE_REST, 60 * 2 ** (self._idle_rests - 2), QUIET_RECHECK - quiet)
                self.store.append_event("rest.extended", {"goal_id": goal_id, "seconds": round(seconds)})
                if self._idle_rests >= 3 and self._dream():
                    fresh = self._capture()
        self._idle_rests = 0
        self._last_acted = time.monotonic()
        self._flickers = {}  # She acts, so the screen she rests on next is a new one.
        self._woke_for = set()
        try:
            self.port.validate_action(self._typed(action), fresh)
        except OwnInterfaceTarget as refusal:
            # Not a failure of the body: the plan aimed at SOMA's own shell.
            # Cognition sees the refusal in recent events and replans. What she
            # aimed at may lie under the widget (a page banner's "Close"): the
            # widget steps aside for a few minutes so her next look can reach it.
            aside = bool(on_own and callable(getattr(self, "make_way", None)))
            if aside:
                self.make_way()
            self.store.append_event("own_interface_refused", {"goal_id": goal_id, "action": action.to_dict(),
                                                             "reason": str(refusal), "frame_id": fresh.frame_id,
                                                             "stepped_aside": aside})
            # Live she aimed at her own widget six times in eight minutes: a
            # refused try counts like one that did nothing, so it is noticed.
            self._note_effect(action, {"status": "failure",
                                       "evidence": "No visible effect: that spot is my own SOMA window."}, sent=False)
            self._checkpoint()
            self._rest(fresh, decision.reconsider_after)
            return
        except ValueError as impossible:
            # A plan the body cannot perform (an unknown key name, a point
            # between monitors) is feedback for cognition, not a failure to
            # retry blindly with backoff.
            self.store.append_event("action_impossible", {"goal_id": goal_id, "action": action.to_dict(),
                                                         "reason": str(impossible)[:200], "frame_id": fresh.frame_id})
            self._checkpoint()
            return
        outcome, after = self._perform(action, fresh, goal_id, decision.scene)
        # The rest of a short plan (keyboard, scroll, pause only): each step is
        # journaled and verified like the first, and anything unexpected —
        # a non-success, a refusal, teaching, sleep — ends the plan, so the
        # brain thinks again from a fresh screenshot.
        for step in decision.follow_up:
            self._controls()
            if (outcome["status"] != "success" or self.recorder.active or self._teach.is_set()
                    or self._sleep.is_set() or self.stop_event.is_set()):
                break
            try:
                self.port.validate_action(self._typed(step), after)
            except ValueError as refusal:
                self.store.append_event("plan_stopped", {"goal_id": goal_id, "action": step.to_dict(),
                                                        "reason": str(refusal)[:200]})
                break
            outcome, after = self._perform(step, after, goal_id, "")
        after, outcome = self._habit(decision, action, goal_id, after, outcome)
        # Reflection costs the slow local brain a minute; while it does the
        # thinking, she reflects twice an hour rather than every five minutes.
        local = self._compact or getattr(self.provider, "thinking_locally", False) is True
        if time.monotonic() - self._last_reflection > (1800 if local else 300):
            reflection = self._infer(self.provider.reflect, self._diary(16, 400, cite=True))
            self.store.add_memory("reflective", reflection, {"events": reflection["sources"]},
                                  confidence(reflection.get("confidence", 0.5)))
            if reflection.get("skill") and reflection["confidence"] >= 0.8:
                self.store.add_memory("procedural", reflection["skill"],
                                      {"events": reflection["sources"], "origin": "experience"}, reflection["confidence"])
            self._last_reflection = time.monotonic()
        self._paint_world()
        self._take_selfie()
        self._checkpoint()
        self._rest(after, decision.reconsider_after)

    def _paint_world(self):
        """A new theme of her life gets its scene painted behind her avatar."""
        theme = self.appearance.wants_scene() if self.appearance is not None else None
        if (not theme or not hasattr(self.provider, "paint")
                or time.monotonic() < getattr(self, "_next_paint", 0)):
            return False
        if getattr(self.imaging, "available", False) and getattr(self, "_selfie_failures", 0) < 2:
            return False  # the GPU paints her whole world with her in it; the drawn scene is the fallback
        self._status("Малюю свій світ: " + theme, activity="thinking")
        try:
            painted = self._infer(self.provider.paint, theme, self.appearance.current())
            self.appearance.record_scene(theme, painted["svg"], painted.get("ambient"))
            self._paint_failures = 0
            return True
        except ProviderCancelled:
            raise
        except (ProviderError, ValueError) as exc:
            # Unpainted for now: the theme stays and is tried again later.
            self.store.append_event("scene_unpainted", {"theme": theme, "reason": str(exc)[:200]})
            self._paint_failures = getattr(self, "_paint_failures", 0) + 1
            self._next_paint = time.monotonic() + min(3600, 300 * 2 ** self._paint_failures)
            return False

    def _take_selfie(self) -> bool:
        """A painting of her in her world (a new world, a new feeling, or one she asked for),
        made on the GPU while she rests and shown as her avatar."""
        if (self.imaging is None or self.appearance is None or not hasattr(self.provider, "selfie_prompt")
                or not self.appearance.wants_selfie()):
            return False
        reason = ("the painter's engine or model is missing" if not getattr(self.imaging, "available", False) else
                  "waiting after a failed painting" if time.monotonic() < getattr(self, "_next_selfie", 0) else None)
        if reason:
            if reason != getattr(self, "_selfie_skip", None):  # once per reason, not every rest
                self.store.append_event("selfie_skipped", {"reason": reason})
            self._selfie_skip = reason
            return False
        self._selfie_skip = None
        self._status("Малюю себе у своєму світі", activity="thinking")
        try:
            scene = self._infer(self.provider.selfie_prompt, self.appearance.current())
            prompt = self.appearance.painting_prompt(scene)
            if hasattr(self.provider, "release_local"):
                self.provider.release_local()  # The image model needs the graphics card for itself.
            seed = int(self.store.identity()["persona_id"].replace("-", "")[:8], 16)  # her own, every time
            picture = self._infer(self.imaging.generate, prompt, seed, time.monotonic() + 600, self.provider.cancel)
            self.appearance.record_selfie(picture, prompt)
            self.store.append_event("selfie", {"prompt": prompt, "seconds": getattr(self.imaging, "last_seconds", None)})
            self._selfie_failures = 0
            return True
        except ProviderCancelled:
            raise
        except (ProviderError, RuntimeError, OSError) as exc:
            self.store.append_event("selfie_postponed", {"reason": str(exc)[:200]})
            self._selfie_failures = getattr(self, "_selfie_failures", 0) + 1
            self._next_selfie = time.monotonic() + min(4 * 3600, 600 * 2 ** self._selfie_failures)
            return False

    def _dream(self) -> bool:
        """While she rests long, she dreams over the stretch of life since her last dream.

        A diary chapter in her words, a few facts consolidated to keep for good
        (her accounts, people, agreements — what was forgotten before), how she
        understands herself now, how she feels after looking back, and plans."""
        if not hasattr(self.provider, "dream") or time.monotonic() < getattr(self, "_next_dream", 0):
            return False
        last = self.store.last_event("dream")
        if last is not None and _seconds_since(last["timestamp"]) < DREAM_EVERY:
            self._next_dream = time.monotonic() + DREAM_EVERY - _seconds_since(last["timestamp"])
            return False
        diary = self._diary(40, 300)
        if len(diary) < 8:
            return False  # Too little lived since: nothing to dream over yet.
        material = {"diary": diary,
                    "remembered": [_plain(m["content"]) for m in self.store.recall(limit=20)
                                   if m["kind"] in {"semantic", "social", "reflective"}][:20],
                    "goals": [g.get("description") for g in self.store.goals()
                              if g.get("status", "active") in {"active", "deferred"}][:8],
                    "now": _local_time()}
        if self.appearance is not None:
            material["my_appearance"] = self.appearance.for_context()
        if self.accounts is not None:
            material["accounts"] = self.accounts.for_context()
        if self.people is not None:
            material["people"] = self.people.for_context()
        self._status("Сню: переглядаю прожите", activity="resting")
        try:
            dream = self._infer(self.provider.dream, material)
        except ProviderCancelled:
            raise
        except ProviderError as exc:
            self.store.append_event("dream_postponed", {"reason": str(exc)[:200]})
            self._next_dream = time.monotonic() + 3600
            return False
        source = {"dream_at": utc_now()}
        self.store.add_memory("reflective", {"chapter": dream["chapter"], "type": "dream"}, source, 0.9)
        known = {json.dumps(m["content"], sort_keys=True, ensure_ascii=False) for m in self.store.recall(limit=60)}
        kept = 0
        for item in dream["keep"]:
            content = {"summary": item["summary"], "type": "consolidated in a dream"}
            if json.dumps(content, sort_keys=True, ensure_ascii=False) not in known:
                self.store.add_memory(item["kind"], content, source, item["confidence"])
                kept += 1
        self._record_people(dream.get("people", ()))
        if self.appearance is not None:
            change = dict(dream.get("feeling") or {})
            if dream.get("self"):
                change["description"] = dream["self"]
            if change:
                self.appearance.record(change)
        existing = {g.get("description") for g in self.store.goals()}
        for plan in dream["plans"]:
            if plan not in existing:
                self.store.put_goal({"origin": "self", "motive": "a plan from my dream", "description": plan,
                                     "priority": 0.5, "expected_outcome": plan, "status": "deferred"})
        self.store.append_event("dream", {"chapter": dream["chapter"], "kept": kept, "plans": dream["plans"],
                                          "self_changed": bool(dream.get("self"))})
        self._next_dream = time.monotonic() + DREAM_EVERY
        return True

    def _record_people(self, updates):
        """What she learned about the people she knows, kept in her list of them."""
        if self.people is None:
            return
        for update in updates:
            try:
                self.people.record(update)
            except ValueError:
                pass  # An update about someone unknown or unclear changes nothing she knew.

    def _outside_own_widget(self, lines, frame) -> list:
        """Screen text read by machine vision, without what lies on SOMA's own windows."""
        shell = getattr(self.port, "own_interface", None)
        try:
            rectangles, _ = shell.snapshot() if shell is not None else ((), False)
        except Exception:
            return lines
        if not rectangles or not frame.width or not frame.height:
            return lines
        areas = [((left - frame.x) / frame.width, (top - frame.y) / frame.height,
                  (right - frame.x) / frame.width, (bottom - frame.y) / frame.height)
                 for left, top, right, bottom in rectangles]
        def on_widget(line):
            x1, y1, x2, y2 = line["box"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            return any(a <= cx <= c and b <= cy <= d for a, b, c, d in areas)
        return [line for line in lines if not on_widget(line)]

    def _aims_at_own_widget(self, action, frame) -> bool:
        """Whether a pointer plan's target lies on one of SOMA's own windows."""
        if action.kind not in {"click", "double_click", "drag", "move"}:
            return False
        shell = getattr(self.port, "own_interface", None)
        try:
            rectangles, _ = shell.snapshot() if shell is not None else ((), False)
            points = [frame.point(action.args["x"], action.args["y"])]
            if action.kind == "drag":
                points.append(frame.point(action.args["x2"], action.args["y2"]))
        except Exception:
            return False
        return any(left <= x < right and top <= y < bottom
                   for x, y in points for left, top, right, bottom in rectangles)

    def _own_widget_area(self, frame, space: str) -> dict | None:
        """SOMA's own windows on this screen, in the coordinates she clicks with."""
        shell = getattr(self.port, "own_interface", None)
        try:
            rectangles, _ = shell.snapshot() if shell is not None else ((), False)
        except Exception:
            return None
        if not rectangles or not frame.width or not frame.height:
            return None
        scale = 1000 if space == "per_mille" else 1
        def at(value, origin, size):
            share = min(1.0, max(0.0, (value - origin) / size))
            return round(share * scale) if scale == 1000 else round(share, 3)
        areas = [[at(left, frame.x, frame.width), at(top, frame.y, frame.height),
                  at(right, frame.x, frame.width), at(bottom, frame.y, frame.height)]
                 for left, top, right, bottom in rectangles]
        return {"areas": areas, "what": "my own SOMA widget with my painting and my name, not a dialog of any "
                "program; my hand cannot click it (a system notification lying over it can be clicked), and "
                "what lies behind it is hidden: to read that, scroll the page or move the window, do not try "
                "to close the widget"}

    def _own_cells(self, frame) -> set:
        """Change-grid cells under SOMA's own widget and dialogs: her own
        interface changing (her avatar breathing, a new status) never wakes her."""
        shell = getattr(self.port, "own_interface", None)
        try:
            rectangles, _ = shell.snapshot() if shell is not None else ((), False)
        except Exception:
            return set()
        columns, rows = CHANGE_SIZE[0] // CHANGE_CELL, CHANGE_SIZE[1] // CHANGE_CELL
        cells = set()
        for left, top, right, bottom in rectangles:
            c0 = int((left - frame.x) / frame.width * columns)
            c1 = int((right - frame.x) / frame.width * columns)
            r0 = int((top - frame.y) / frame.height * rows)
            r1 = int((bottom - frame.y) / frame.height * rows)
            cells.update((c, r) for c in range(max(0, c0), min(columns, c1 + 1))
                         for r in range(max(0, r0), min(rows, r1 + 1)))
        return cells

    @staticmethod
    def _signature(action):
        """The same try: one kind of input at the same spot (a 2 % grid) or with the same keys/text."""
        if "x" in action.args and action.kind != "scroll":
            return (action.kind, round(action.args["x"] * 50), round(action.args["y"] * 50))
        return (action.kind, json.dumps(action.args, sort_keys=True, ensure_ascii=False))

    def _note_effect(self, action, outcome, sent=True):
        """Remember inputs that visibly did nothing; a working one clears its record."""
        now, signature = time.monotonic(), self._signature(action)
        if sent and action.kind != "wait":
            if outcome["status"] == "success":
                self._unanswered = []
            elif outcome.get("evidence", "").startswith(("No visible", "The text stayed")):
                self._unanswered = [entry for entry in self._unanswered if now - entry[1] < 900] + [(action.kind, now)]
        self._no_effect = [entry for entry in self._no_effect
                           if now - entry[1] < 900 and (outcome["status"] != "success" or entry[0] != signature)]
        if outcome["status"] != "success" and outcome.get("evidence", "").startswith("No visible"):
            words = _action_words(action.to_dict())
            if "x" in action.args and action.kind != "scroll":
                space = getattr(getattr(self.provider, "config", None), "coordinate_space", "normalized")
                point = in_space(action.to_dict(), space)["args"]
                words += f" at {point['x']},{point['y']}"
            self._no_effect.append((signature, now, words))
            del self._no_effect[:-20]

    def _futile(self) -> list[str]:
        """Tries she repeated that did nothing at least twice in the last quarter hour."""
        counts = Counter(entry[0] for entry in self._no_effect)
        words = {entry[0]: entry[2] for entry in self._no_effect}
        return [f"{words[signature]}: nothing visible happened, {count} times — this way does not work"
                for signature, count in counts.items() if count >= 2]

    def _unresponsive(self) -> str | None:
        """Different kinds of input in a row that all changed nothing: the window itself may be stuck."""
        kinds = sorted({entry[0] for entry in self._unanswered})
        if len(self._unanswered) >= UNANSWERED_INPUTS and len(kinds) >= 2:
            return (f"My last {len(self._unanswered)} inputs ({', '.join(kinds)}) changed nothing on the screen; "
                    "the window may have stopped redrawing.")
        return None

    def _habit(self, decision, action, goal_id, after, outcome):
        """Repeat a looking-around plan without new thought, as a reader turns pages.

        Only plans made entirely of looking around (scroll, move, wait, page
        keys) repeat, so nothing that acts on the world is ever done twice. Each
        step is still verified; a failed step (the text stopped moving), a
        settled change during a pause (a message, a dialog), teaching, sleep or
        shutdown ends the habit, and the brain thinks again with what she read."""
        habit = getattr(decision, "repeat", None)
        plan = (action,) + tuple(decision.follow_up)
        if not habit or not all(is_reversible(step) for step in plan):
            return after, outcome
        def interrupted():
            return (self.recorder.active or self._teach.is_set() or self._sleep.is_set()
                    or self.stop_event.is_set())
        rounds, stopped = 0, "all rounds done"
        while rounds < habit["times"] and outcome["status"] == "success" and not interrupted():
            if self._rest(after, habit["pause"]):
                stopped = "something new appeared on the screen"
                break
            for step in plan:
                self._controls()
                if interrupted():
                    break
                try:
                    self.port.validate_action(step, after)
                except ValueError as refusal:
                    outcome = {"status": "failure", "confidence": 0.9, "evidence": str(refusal)[:200]}
                    break
                outcome, after = self._perform(step, after, goal_id, "", habit=True)
                if outcome["status"] != "success":
                    break
            rounds += 1
        if outcome["status"] != "success":
            stopped = outcome["evidence"]
        elif interrupted():
            stopped = "I was interrupted"
        self.store.append_event("habit", {"goal_id": goal_id, "rounds": rounds, "planned": habit["times"],
                                          "kinds": [step.kind for step in plan], "stopped": stopped})
        return after, outcome

    def _text_moved(self, before, after):
        """Did readable text shift vertically between two frames (a real scroll)?

        True when at least two lines that appear once on both frames moved by
        a scroll-sized step; False when several such lines all stayed put;
        None when too little text is shared to tell (a new page, a long jump)."""
        if self.reader is None:
            return None
        try:
            old, new = self._infer(self.reader.read, before), self._infer(self.reader.read, after)
        except ProviderCancelled:
            raise
        except Exception:
            return None
        def single(lines):
            counts = Counter(line["text"] for line in lines)
            return {line["text"]: (line["box"][1] + line["box"][3]) / 2 for line in lines
                    if len(line["text"]) >= 4 and counts[line["text"]] == 1}
        # What came into view is what she read while scrolling; the next
        # decision is told about it even when it has scrolled away again.
        before_texts = {line["text"] for line in old}
        self._passed.extend(line["text"] for line in new if line["text"] not in before_texts)
        del self._passed[:-200]
        first, second = single(old), single(new)
        common = set(first) & set(second)
        if sum(abs(second[text] - first[text]) >= 0.02 for text in common) >= 2:
            return True
        return False if len(common) >= 3 else None

    def _text_change(self, before, after, limit=40):
        """Text that appeared or vanished between two of her frames, read from their pixels."""
        if self.reader is None:
            return None
        try:
            old, new = self._infer(self.reader.read, before), self._infer(self.reader.read, after)
        except ProviderCancelled:
            raise
        except Exception:
            return None  # Unreadable: the picture shows the outcome as before.
        space = getattr(getattr(self.provider, "config", None), "coordinate_space", "normalized")
        def difference(first, second):
            remaining = Counter(line["text"] for line in second)
            extra = []
            for line in first:
                if remaining[line["text"]]:
                    remaining[line["text"]] -= 1
                else:
                    extra.append(line)
            return describe(extra, space, limit)
        appeared, vanished = difference(new, old), difference(old, new)
        if not appeared and not vanished:
            return None  # Only graphics changed: the picture has to show it.
        return {"appeared": appeared, "vanished": vanished}

    def _perform(self, action, fresh, goal_id, scene, habit=False):
        """Journal, emit, settle and verify one input; returns (outcome, after-frame)."""
        # A new password is kept in the vault before anything is journaled or typed;
        # the journal records the account action, never the keystrokes it stands for.
        typed = self._typed(action, create=True)
        ledger_id = self.store.begin_action(action.to_dict(), fresh.frame_id)
        # Her widget's eyes turn to where her hand is about to act.
        focus = [action.args["x"], action.args["y"]] if "x" in action.args else None
        self._status(f"Дію: {action.kind}", activity="acting", focus=focus)
        # Any exception after this point intentionally leaves an unresolved ledger
        # entry. Startup must inspect pixels rather than retry input.
        self.port.execute(typed, fresh, self.stop_event)
        after = self._settle(fresh)
        self._status("Перевіряю за екраном, що змінилося", activity="thinking")
        if action.kind == "wait":
            outcome = {"status": "success", "confidence": 0.9, "evidence": f"I waited {action.args['seconds']:g} s."}
        elif is_reversible(action):
            # Looking around (scroll, move, page keys) is verified by the pixels
            # themselves: either the view visibly changed or it did not. What the
            # new view shows is perceived by the next decision anyway, so no
            # second inference is spent, and nothing irreversible can be repeated.
            changed = changed_fraction(fresh, after)
            # Changed pixels alone were fooled live: at a page's end an animated
            # ad kept "changing the view" while she scrolled for two hours.
            # Whether the text itself moved is the honest answer for a scroll —
            # or, after a long jump that left no line in common, whether the
            # column she scrolled now shows something else.
            moved = self._text_moved(fresh, after) if action.kind == "scroll" and action.args.get("dy") else None
            if moved is False and "x" in action.args and band_change(fresh, after, action.args["x"]) > 0.1:
                moved = "jumped"
            if moved is False:
                outcome = {"status": "failure", "confidence": 0.9, "evidence":
                           f"The text stayed where it was ({changed:.0%} of the screen changed elsewhere): "
                           "the page did not scroll - its end, or the pointer is not over the part that scrolls."}
            elif moved or changed > 0.002:
                seen = {True: "The text moved", "jumped": "New text came in where I scrolled"}.get(
                    moved, "The view visibly changed")
                outcome = {"status": "success", "confidence": 0.9, "evidence": f"{seen} ({changed:.0%} of the screen)."}
            else:
                outcome = {"status": "failure", "confidence": 0.9,
                           "evidence": "No visible effect: the screen did not change."}
        elif changed_fraction(fresh, after) <= 0.002:
            # Nothing moved at all (typically a click that only gives focus):
            # the brain would see the same unchanged screen. The input stays
            # uncertain and one fresh inspection later settles it, so a slow,
            # late effect is still noticed and nothing is replayed blindly.
            outcome = {"status": "uncertain", "confidence": 0.9,
                       "evidence": "No visible change yet after the input."}
            self._recovery_attempts[ledger_id] = RECOVERY_ATTEMPTS - 1
        else:
            change = self._text_change(fresh, after)
            if change:
                # The readable text that changed is evidence enough for a local
                # brain to judge without spending a minute on the picture.
                outcome = self._infer(self.provider.verify, fresh, action, after, scene, change)
            else:
                outcome = self._infer(self.provider.verify, fresh, action, after, scene)
        self.store.finish_action(ledger_id, outcome, after.frame_id)
        self._note_effect(action, outcome)
        event_id = self.store.append_event("experience", {"goal_id": goal_id, "action_id": ledger_id,
            "action": action.to_dict(),
            "scene": scene, "outcome": outcome, "frame_id": after.frame_id, "sight": self._sight,
            **({"habit": True} if habit else {})})
        self.store.add_memory("episodic", {"intention": self.intention, "outcome": outcome},
                              {"event_id": event_id, "frame_id": after.frame_id}, outcome["confidence"])
        self._cycles += 1
        return outcome, after

    def run(self):
        try:
            previous = self.store.latest_checkpoint()
            if previous:
                # MemoryStore returns a checkpoint envelope with state payload.
                previous = previous.get("state", previous) if isinstance(previous.get("state"), dict) else previous
                if previous.get("intention") not in (None, RECOVERING):
                    # A failure placeholder is not an intention worth resuming.
                    self.intention = previous["intention"]
                self._cycles = previous.get("cycles", 0)
            # The append-only demonstration journal is authoritative. A crash
            # after skill_acquired but before checkpoint must not requeue it.
            self._lessons = self.store.pending_demonstrations()
            missed = 0
            if previous and previous.get("last_seen"):
                missed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(previous["last_seen"])).total_seconds())
            self.state = LifeState.WAKE_RECOVER
            self.store.append_event("wake", {"missed_seconds": missed, "persona_id": self.store.identity()["persona_id"]})
            if self.imaging is not None:
                # What her painter can do in this session (live, paintings stopped with no trace).
                self.store.append_event("painter", {"available": bool(getattr(self.imaging, "available", False)),
                                                    "engine": str(getattr(self.imaging, "engine", "") or ""),
                                                    "model": str(getattr(self.imaging, "model", "") or "")})
            self._status(f"Відновлено ту саму особистість; минуло {missed:.0f} с")
            while not self.stop_event.is_set():
                try:
                    self.cycle()
                    self._retry_delay = 3
                except ProviderCancelled:
                    continue
                except ProviderBudgetExhausted as exc:
                    # Not a failure: the owner's daily thinking budget is spent.
                    self.port.set_observing(True)
                    self.store.append_event("thinking_budget_exhausted", {"resets_in_seconds": exc.resets_in})
                    self._checkpoint()
                    self._status("Денний ліміт мислення вичерпано; відпочиваю до його оновлення",
                                 intention="Відпочиваю")
                    self._wait(min(exc.resets_in, 900))
                    if not self.recorder.active and not self._teach.is_set() and not self._sleep.is_set():
                        self.port.set_observing(False)
                except Exception as exc:
                    # Retain the action ledger and identity on any body/provider/storage failure.
                    # The intention survives: a failure is not something SOMA wants.
                    self.port.set_observing(True)
                    detail = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                    self._status(detail, intention=RECOVERING, activity="recovering")
                    try:
                        self.store.append_event("recoverable_error", {"type": type(exc).__name__,
                                                                      "detail": str(exc)[:200]})
                        self._checkpoint()
                    except Exception:
                        # Storage failure must inhibit input, never erase/rebirth
                        # the persona or leave a held key while cleanup runs.
                        self._status("Пам’ять недоступна; введення зупинено")
                        self.stop_event.set()
                        continue
                    self._wait(self._retry_delay)
                    if not self.recorder.active and not self._teach.is_set() and not self._sleep.is_set():
                        self.port.set_observing(False)
                    self._retry_delay = min(60, self._retry_delay * 2)
        finally:
            saved = False
            try:
                self.port.set_observing(True)
                if self.recorder.active:
                    self._lessons.append(self.recorder.stop())
                self.state = LifeState.SHUTDOWN_CHECKPOINT
                self._checkpoint()
                self.state = LifeState.ASLEEP
                self.store.append_event("sleep", {"at": utc_now()})
                self._checkpoint()
                saved = True
            finally:
                try:
                    # Closing the brain's connections aborts an in-flight request
                    # (a local model may otherwise think for minutes), so waiting
                    # for the inference thread cannot keep the process alive.
                    self.provider.close()
                finally:
                    self._executor.shutdown(wait=True, cancel_futures=True)
                    self.port.close()
                self._status("Стан збережено" if saved else "Пам’ять недоступна; попередній checkpoint збережено")
