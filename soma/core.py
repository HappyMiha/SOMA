"""Data crossing the cognitive/body boundary. No application metadata."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import math
import time
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LifeState(StrEnum):
    BIRTH = "BIRTH"
    AUTONOMOUS = "AWAKE/AUTONOMOUS"
    OBSERVE_AND_LEARN = "OBSERVE_AND_LEARN"
    SHUTDOWN_CHECKPOINT = "SHUTDOWN_CHECKPOINT"
    ASLEEP = "ASLEEP"
    WAKE_RECOVER = "WAKE_RECOVER"


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ScreenFrame:
    png: bytes
    width: int
    height: int
    x: int = 0
    y: int = 0
    monitors: tuple[Monitor, ...] = ()
    timestamp: str = field(default_factory=utc_now)
    frame_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    captured_monotonic: float = field(default_factory=time.monotonic)

    def geometry(self) -> dict:
        return {"width": self.width, "height": self.height, "x": self.x,
                "y": self.y, "monitors": [asdict(m) for m in self.monitors],
                "frame_id": self.frame_id, "timestamp": self.timestamp}

    def point(self, x: float, y: float) -> tuple[int, int]:
        px = self.x + round(x * (self.width - 1))
        py = self.y + round(y * (self.height - 1))
        if self.monitors and not any(m.x <= px < m.x + m.width and
                                     m.y <= py < m.y + m.height for m in self.monitors):
            raise ValueError("Point falls between physical monitors")
        return px, py


ACTION_FIELDS = {
    "click": {"x", "y", "button"},
    "double_click": {"x", "y", "button"},
    "move": {"x", "y"},
    "drag": {"x", "y", "x2", "y2", "button"},
    "scroll": {"dx", "dy", "x", "y"},
    "key": {"key"},
    "hotkey": {"keys"},
    "type_text": {"text"},
    # Keyboard events whose text is a password from her vault: the brain names
    # the account, never the password, and the journal records only that name.
    "type_secret": {"account"},
    "type_new_secret": {"service", "login"},
    "wait": {"seconds"},
}
# Arguments an action may leave out. A wheel turns whatever is under the
# pointer, so a scroll may first bring the pointer to x,y, as a hand does.
OPTIONAL_FIELDS = {"click": {"button"}, "double_click": {"button"}, "drag": {"button"}, "scroll": {"x", "y"}}


@dataclass(frozen=True)
class Action:
    kind: str
    args: dict = field(default_factory=dict)
    expected: str = ""

    @classmethod
    def parse(cls, value: dict) -> "Action":
        if not isinstance(value, dict) or set(value) - {"kind", "args", "expected"}:
            raise ValueError("Action must contain only kind, args, expected")
        kind, args = value.get("kind"), value.get("args", {})
        if kind not in ACTION_FIELDS or not isinstance(args, dict):
            raise ValueError("Unknown input action")
        if set(args) - ACTION_FIELDS[kind]:
            raise ValueError("Unexpected action arguments")
        required = ACTION_FIELDS[kind] - OPTIONAL_FIELDS.get(kind, set())
        if not required <= set(args) or ("x" in args) != ("y" in args):
            raise ValueError("Missing action arguments")
        for name in ("x", "y", "x2", "y2"):
            if name in args and (type(args[name]) not in (float, int) or
                                 not math.isfinite(args[name]) or not 0 <= args[name] <= 1):
                raise ValueError("Coordinates must be finite normalized numbers")
        if "button" in args and args["button"] not in {"left", "right", "middle"}:
            raise ValueError("Invalid mouse button")
        for name in ("dx", "dy"):
            if name in args and (type(args[name]) is not int or abs(args[name]) > 20):
                raise ValueError("Scroll must be integer steps in [-20,20]")
        if "seconds" in args and (type(args["seconds"]) not in (int, float) or
                                   not math.isfinite(args["seconds"]) or
                                   not 0 <= args["seconds"] <= 30):
            raise ValueError("Wait must be within 0..30 seconds")
        if "text" in args and (not isinstance(args["text"], str) or len(args["text"]) > 4000):
            raise ValueError("Text must contain at most 4000 characters")
        if "key" in args and (not isinstance(args["key"], str) or not 1 <= len(args["key"]) <= 24):
            raise ValueError("Invalid key")
        if "keys" in args and (not isinstance(args["keys"], list) or
                               not 1 <= len(args["keys"]) <= 5 or
                               any(not isinstance(k, str) or not 1 <= len(k) <= 24 for k in args["keys"])):
            raise ValueError("Hotkey must have 1..5 keys")
        for name in ("account", "service", "login"):
            if name in args and (not isinstance(args[name], str) or not 1 <= len(args[name].strip()) <= 200):
                raise ValueError("An account is named by a short non-empty text")
        expected = value.get("expected", "")
        if not isinstance(expected, str) or len(expected) > 2000:
            raise ValueError("Invalid expected visual result")
        return cls(kind, dict(args), expected)

    def to_dict(self) -> dict:
        return asdict(self)
