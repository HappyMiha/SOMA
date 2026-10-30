"""Visible, bounded pixels/input demonstrations. No application introspection."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import uuid
from copy import deepcopy

from .core import ScreenFrame, utc_now


INPUT_FIELDS = {
    "mouse_move": {"x", "y"},
    "mouse_down": {"x", "y", "button"},
    "mouse_up": {"x", "y", "button"},
    "scroll": {"x", "y", "dx", "dy"},
    "key_down": {"key"},
    "key_up": {"key"},
}


def learning_evidence(trace: dict, selected_frames: list[dict]) -> dict:
    """Bound visual evidence for inference; this never produces executable input."""
    compact = []
    for index, step in enumerate(trace.get("steps", [])):
        event = step["input"]
        previous = compact[-1] if compact else None
        continuous = previous and not previous.get("incomplete_reason") and not step.get("incomplete_reason") and (
            previous["before_frame_id"] == step.get("before_frame_id") or
            previous["after_frame_id"] == step.get("before_frame_id"))
        if event["kind"] == "mouse_move" and previous and previous["input"]["kind"] == "mouse_path" and continuous:
            previous["input"]["end"] = event["args"]
            previous["input"]["count"] += 1
            previous["source_steps"][1] = index
            previous["after_frame_id"] = step.get("after_frame_id")
        elif event["kind"] == "mouse_move":
            compact.append({"source_steps": [index, index], "before_frame_id": step.get("before_frame_id"),
                "after_frame_id": step.get("after_frame_id"), "input": {"kind": "mouse_path",
                "start": event["args"], "end": event["args"], "count": 1},
                **({"incomplete_reason": step["incomplete_reason"]} if "incomplete_reason" in step else {})})
        else:
            compact.append({"source_steps": [index, index], "before_frame_id": step.get("before_frame_id"),
                "after_frame_id": step.get("after_frame_id"), "input": deepcopy(event),
                **({"incomplete_reason": step["incomplete_reason"]} if "incomplete_reason" in step else {})})
    budget = min(128, len(compact))
    result = {"id": trace.get("id"), "started_at": trace.get("started_at"), "ended_at": trace.get("ended_at"),
        "gaps": trace.get("gaps", [])[:64], "truncated": trace.get("truncated", False),
        "interrupted": trace.get("interrupted", False),
        "recorded_step_count": len(trace.get("steps", [])), "compressed_step_count": len(compact),
        "frames": selected_frames,
        "evidence_limits": "Only attached images are visible evidence. Other frame IDs have no attached pixels. "
            "Input coordinates describe demonstrations only; re-ground each learned step on a fresh screenshot. "
            "Omitted input and private gaps are unknown; do not infer their content."}
    while True:
        indices = sorted({round(index * (len(compact) - 1) / max(1, budget - 1)) for index in range(budget)})
        result["steps"] = [compact[index] for index in indices]
        result["omitted_compressed_steps"] = len(compact) - len(indices)
        if len(json.dumps(result, ensure_ascii=False)) <= 24000 or budget <= 1:
            return result
        budget //= 2


def reconstruct_interrupted_demonstrations(events) -> list[dict]:
    """Rebuild observations after a crash; never resumes hooks or replays input.

    ``events`` is an ordered iterable of MemoryStore event envelopes with parsed
    ``data`` dictionaries. Each delta contains only one frame, input, or gap.
    """
    traces = {}
    for envelope in events:
        kind, data = envelope["kind"], envelope["data"]
        if kind == "memory.added":
            content = data.get("content", {})
            completed = content.get("demonstration") if isinstance(content, dict) else None
            if isinstance(completed, dict) and completed.get("ended_at"):
                traces.pop(completed["id"], None)
            continue
        if kind == "skill_acquired":
            traces.pop(data.get("demonstration"), None)
            continue
        elif kind in {"demonstration_stopped", "demonstration_unusable", "demonstration_failed"}:
            traces.pop(data.get("id"), None)
            continue
        demonstration_id = data.get("id")
        if kind == "demonstration_started":
            traces[demonstration_id] = {"id": demonstration_id, "started_at": data.get("started_at", envelope.get("timestamp")),
                "ended_at": None, "clock": "monotonic", "frames": {}, "steps": {}, "gaps": {},
                "omitted_inputs_no_frame": 0, "accepted_inputs": 0, "truncated": False, "interrupted": True}
        trace = traces.get(demonstration_id)
        if trace is None:
            continue
        trace["last_journal_event_id"] = envelope.get("id")
        if kind == "demonstration_input":
            trace["steps"][data["index"]] = deepcopy(data["step"])
            trace["accepted_inputs"] = data["accepted_inputs"]
        elif kind == "demonstration_frame":
            trace["frames"][data["index"]] = deepcopy(data["frame"])
            trace["omitted_inputs_no_frame"] = data["omitted_inputs_no_frame"]
            for index in data["paired_steps"]:
                if index in trace["steps"]:
                    trace["steps"][index]["after_frame_id"] = data["frame"]["frame_id"]
        elif kind in {"demonstration_privacy", "demonstration_limit"} and "gap" in data:
            trace["gaps"][data["gap_index"]] = deepcopy(data["gap"])
            reason = "capacity_limit" if kind == "demonstration_limit" else "sensitive_gap"
            for index in data.get("incomplete_steps", []):
                if index in trace["steps"]:
                    trace["steps"][index]["incomplete_reason"] = reason
            if kind == "demonstration_limit":
                trace["truncated"] = True
    recovered = []
    for demonstration_id, trace in traces.items():
        trace["frames"] = [value for _, value in sorted(trace["frames"].items())]
        trace["steps"] = sorted(trace["steps"].values(), key=lambda step: step["input"]["timestamp"])
        trace["gaps"] = [value for _, value in sorted(trace["gaps"].items())]
        frames = {frame["frame_id"]: frame for frame in trace["frames"]}
        for step in trace["steps"]:
            timestamp = step["input"]["timestamp"]
            before, after = frames.get(step["before_frame_id"]), frames.get(step["after_frame_id"])
            if before is None or before["available_at"] > timestamp:
                step["before_frame_id"] = None
                step["incomplete_reason"] = "missing_before_frame"
            if after is None or after["captured_at"] < timestamp or before is after:
                step["after_frame_id"] = None
                step.setdefault("incomplete_reason", "interrupted_before_after_frame")
        recovered.append(trace)
    return recovered


class _XorgStopMixin:
    def _stop_platform(self):
        # pynput 1.x queues disable on the blocked RECORD connection. Use its
        # separate control connection and flush so join does not need new input.
        if hasattr(self, "_context"):
            self._display_stop.record_disable_context(self._context)
            self._display_stop.flush()


def native_hooks(callback):
    """Construct listeners only when a demonstration explicitly starts."""
    if sys.platform == "win32":
        backend = "win32"
    elif sys.platform.startswith("linux"):
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            raise RuntimeError("Demonstration input recording requires X11; Wayland is not supported")
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("Demonstration input recording requires an interactive X11 session")
        backend = "xorg"
    else:
        raise RuntimeError("Demonstration input recording supports Windows and Linux X11")
    # Prevent pynput from selecting an alternate input backend such as uinput.
    os.environ["PYNPUT_BACKEND"] = backend
    os.environ["PYNPUT_BACKEND_KEYBOARD"] = backend
    os.environ["PYNPUT_BACKEND_MOUSE"] = backend
    from pynput import keyboard, mouse

    if any(not listener.__module__.endswith("._" + backend) for listener in (mouse.Listener, keyboard.Listener)):
        raise RuntimeError("pynput already loaded an unsupported input backend")
    mouse_listener, keyboard_listener = mouse.Listener, keyboard.Listener
    if backend == "xorg":
        class MouseListener(_XorgStopMixin, mouse.Listener):
            pass

        class KeyboardListener(_XorgStopMixin, keyboard.Listener):
            pass

        mouse_listener, keyboard_listener = MouseListener, KeyboardListener

    def key_name(key):
        value = key.char if getattr(key, "char", None) else str(key)
        # Win32 can expose one UTF-16 surrogate unit. Keep an explicit token,
        # never invalid Unicode or a guessed character assembled across events.
        return "".join("U+%04X" % ord(char) if 0xD800 <= ord(char) <= 0xDFFF else char for char in value)

    def dispatch(kind, args):
        # pynput interprets a False callback return as an instruction to stop.
        callback(kind, args, time.monotonic())

    listeners = [
        mouse_listener(
            on_move=lambda x, y: dispatch("mouse_move", {"x": x, "y": y}),
            on_click=lambda x, y, button, pressed: dispatch(
                "mouse_down" if pressed else "mouse_up",
                {"x": x, "y": y, "button": button.name}),
            on_scroll=lambda x, y, dx, dy: dispatch("scroll", {"x": x, "y": y, "dx": dx, "dy": dy})),
        keyboard_listener(
            on_press=lambda key: dispatch("key_down", {"key": key_name(key)}),
            on_release=lambda key: dispatch("key_up", {"key": key_name(key)})),
    ]
    return listeners


class DemonstrationRecorder:
    """Hooks exist only during start..stop; the runtime controls motor resume.

    Input timestamps and captured_at use one monotonic clock. Geometry retains
    the frame's wall-clock timestamp separately. An input needs a preceding
    saved frame; the following capture supplies its after_frame_id.
    """

    def __init__(self, store, port, *, hook_factory=native_hooks,
                 max_events=10000, max_frames=600, max_frame_bytes=128 * 1024 * 1024):
        if min(max_events, max_frames, max_frame_bytes) <= 0:
            raise ValueError("Demonstration bounds must be positive")
        self.store, self.port = store, port
        self._hook_factory = hook_factory
        self._max_events, self._max_frames = max_events, max_frames
        self._max_frame_bytes = max_frame_bytes
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._active = False
        self._paused = False
        self._hooks = []
        self._trace = None
        self._context_frames = []
        self._pending = []
        self._bytes = 0
        self._accepted_inputs = 0

    @property
    def active(self):
        with self._lock:
            return self._active

    @property
    def paused(self):
        with self._lock:
            return self._paused

    def start(self) -> str:
        with self._lifecycle:
            with self._lock:
                if self._active or self._hooks:
                    raise RuntimeError("A demonstration is already active")
                # The port's action lock must finish any in-flight action first.
                self.port.set_observing(True)
                self._pending, self._bytes, self._accepted_inputs = [], 0, 0
                self._context_frames = []
                self._paused = False
                self._trace = {"id": str(uuid.uuid4()), "started_at": utc_now(),
                               "ended_at": None, "clock": "monotonic", "frames": [],
                               "steps": [], "gaps": [], "omitted_inputs_no_frame": 0,
                               "truncated": False, "accepted_inputs": 0}
                self.store.append_event("demonstration_started", {"id": self._trace["id"],
                    "started_at": self._trace["started_at"], "clock": "monotonic",
                    "limits": {"inputs": self._max_events, "frames": self._max_frames,
                               "frame_bytes": self._max_frame_bytes, "private_segments": 128}})
                self._active = True
            try:
                hooks = list(self._hook_factory(self.record_input))
                self._hooks = hooks
                for hook in hooks:
                    hook.start()
                # pynput 1.x wait() has no timeout. Its readiness condition lets
                # startup fail visibly rather than hang if OS hook setup fails.
                for hook in hooks:
                    condition = getattr(hook, "_condition", None)
                    if condition is not None:
                        with condition:
                            condition.wait_for(lambda: hook._ready or not hook.is_alive(), timeout=3)
                            if not hook._ready or not hook.is_alive():
                                raise RuntimeError("Native demonstration listener did not become ready")
            except BaseException:
                with self._lock:
                    self._active = False
                self._stop_hooks()
                self.store.append_event("demonstration_failed", {"id": self._trace["id"], "stage": "hooks"})
                raise
            return self._trace["id"]

    def _stop_hooks(self):
        hooks = self._hooks
        errors = []
        for hook in hooks:
            try:
                hook.stop()
            except Exception as error:
                errors.append(error)
        for hook in hooks:
            try:
                hook.join(timeout=2)
                if getattr(hook, "is_alive", lambda: False)():
                    errors.append(RuntimeError("Demonstration hook did not stop"))
            except RuntimeError as error:
                # Joining a listener whose start failed is harmless if not alive.
                # pynput also reraises callback RuntimeErrors after thread exit;
                # those must not be mistaken for a never-started Thread.join.
                if not (isinstance(hook, threading.Thread) and hook.ident is None):
                    errors.append(error)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError("Could not confirm that demonstration hooks stopped") from errors[0]
        self._hooks = []

    def _break_context(self, reason):
        for index in self._pending:
            self._trace["steps"][index]["incomplete_reason"] = reason
        self._pending = []
        self._context_frames = []

    def pause_recording(self, paused: bool):
        """Omit both pixels and input during a visible sensitive segment."""
        if type(paused) is not bool:
            raise ValueError("paused must be a boolean")
        with self._lock:
            if not self._active:
                raise RuntimeError("No demonstration is active")
            if paused == self._paused:
                return
            if self._trace["truncated"]:
                self._paused = paused
                return
            if paused:
                self._paused = True
                if len(self._trace["gaps"]) >= 128:
                    self._truncate()
                    return
                gap = {"started_at": time.monotonic(), "ended_at": None, "reason": "sensitive"}
                self.store.append_event("demonstration_privacy", {"id": self._trace["id"], "paused": True,
                    "gap_index": len(self._trace["gaps"]), "gap": gap, "incomplete_steps": list(self._pending)})
                self._break_context("sensitive_gap")
                self._trace["gaps"].append(gap)
            else:
                index = next(index for index in reversed(range(len(self._trace["gaps"])))
                             if self._trace["gaps"][index]["reason"] == "sensitive" and self._trace["gaps"][index]["ended_at"] is None)
                gap = {**self._trace["gaps"][index], "ended_at": time.monotonic()}
                self.store.append_event("demonstration_privacy", {"id": self._trace["id"], "paused": False,
                    "gap_index": index, "gap": gap, "incomplete_steps": []})
                self._trace["gaps"][index] = gap
                self._paused = False

    def _truncate(self):
        gap = {"started_at": time.monotonic(), "ended_at": None, "reason": "capacity_limit"}
        self.store.append_event("demonstration_limit", {"id": self._trace["id"],
            "gap_index": len(self._trace["gaps"]), "gap": gap, "incomplete_steps": list(self._pending)})
        self._trace["truncated"] = True
        self._break_context("capacity_limit")
        self._trace["gaps"].append(gap)

    def capture(self, frame: ScreenFrame):
        available_at = time.monotonic()
        with self._lock:
            if not self._active or self._paused or self._trace["truncated"]:
                return None
            if len(self._trace["frames"]) >= self._max_frames or self._bytes + len(frame.png) > self._max_frame_bytes:
                self._truncate()
                return None
            captured_at = getattr(frame, "captured_monotonic", available_at)
            if type(captured_at) not in (int, float) or not math.isfinite(captured_at):
                raise ValueError("Frame capture time must be finite monotonic time")
            # A slow grab can begin before a privacy toggle and return after it.
            # Reject the entire capture interval, including an already-ended gap.
            if any(gap["reason"] == "sensitive" and captured_at <= (gap["ended_at"] or available_at)
                   and available_at >= gap["started_at"] for gap in self._trace["gaps"]):
                return None
            path = self.store.save_frame(frame)
            record = {"frame_id": frame.frame_id, "path": str(path), "captured_at": captured_at,
                      "available_at": available_at, "geometry": frame.geometry()}
            paired = [index for index in self._pending if self._trace["steps"][index]["input"]["timestamp"] <= captured_at]
            self.store.append_event("demonstration_frame", {"id": self._trace["id"],
                "index": len(self._trace["frames"]), "frame": record, "paired_steps": paired,
                "omitted_inputs_no_frame": self._trace["omitted_inputs_no_frame"]})
            self._bytes += len(frame.png)
            self._trace["frames"].append(record)
            self._context_frames.append(self._trace["frames"][-1])
            remaining = []
            for index in self._pending:
                step = self._trace["steps"][index]
                if step["input"]["timestamp"] <= captured_at:
                    step["after_frame_id"] = frame.frame_id
                else:
                    remaining.append(index)
            self._pending = remaining
            return frame.frame_id

    def record_input(self, kind: str, args: dict, timestamp=None):
        """Native hook callback; public injection supports deterministic tests."""
        with self._lock:
            # Do not inspect, copy, or validate key data outside visible recording.
            if not self._active or self._paused or self._trace["truncated"]:
                return False
            timestamp = time.monotonic() if timestamp is None else timestamp
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError("Input timestamp must be finite monotonic time")
            if any(gap["reason"] == "sensitive" and gap["started_at"] <= timestamp <= (gap["ended_at"] or timestamp)
                   for gap in self._trace["gaps"]):
                return False
            if kind not in INPUT_FIELDS or not isinstance(args, dict) or set(args) != INPUT_FIELDS[kind]:
                raise ValueError("Invalid demonstration input fields")
            if "key" in args and (not isinstance(args["key"], str) or not 1 <= len(args["key"]) <= 64):
                raise ValueError("Invalid demonstration key")
            if "key" in args:
                args = {"key": "".join("U+%04X" % ord(char) if 0xD800 <= ord(char) <= 0xDFFF else char for char in args["key"])}
            for field in ("x", "y", "dx", "dy"):
                if field in args and (type(args[field]) not in (int, float) or not math.isfinite(args[field])):
                    raise ValueError("Input coordinates must be finite numbers")
            if "button" in args and args["button"] not in {"left", "right", "middle", "x1", "x2"}:
                raise ValueError("Invalid demonstration mouse button")
            before = next((frame for frame in reversed(self._context_frames) if frame["available_at"] <= timestamp), None)
            if before is None:
                self._trace["omitted_inputs_no_frame"] += 1
                return False
            before_index = self._context_frames.index(before)
            after = next((frame for frame in self._context_frames[before_index + 1:]
                          if frame["captured_at"] >= timestamp), None)
            event = {"kind": kind, "args": dict(args), "timestamp": timestamp}
            if self._accepted_inputs >= self._max_events:
                self._truncate()
                return False
            if kind == "mouse_move" and self._pending:
                previous = self._trace["steps"][self._pending[-1]]
                interval = timestamp - previous["input"]["timestamp"]
                if previous["input"]["kind"] == kind and previous["before_frame_id"] == before["frame_id"] and 0 <= interval <= 0.075:
                    # Sampling pointer motion at <=20 Hz keeps the durable journal
                    # bounded; click/drag/button/key boundaries are never skipped.
                    if interval < 0.05:
                        return False
                    updated = {**previous, "input": event}
                    self.store.append_event("demonstration_input", {"id": self._trace["id"],
                        "index": self._pending[-1], "step": updated, "accepted_inputs": self._accepted_inputs + 1})
                    previous["input"] = event
                    self._accepted_inputs += 1
                    self._trace["accepted_inputs"] = self._accepted_inputs
                    return True
            step = {"before_frame_id": before["frame_id"], "after_frame_id": after["frame_id"] if after else None, "input": event}
            self.store.append_event("demonstration_input", {"id": self._trace["id"],
                "index": len(self._trace["steps"]), "step": step, "accepted_inputs": self._accepted_inputs + 1})
            if after is None:
                self._pending.append(len(self._trace["steps"]))
            self._trace["steps"].append(step)
            self._accepted_inputs += 1
            self._trace["accepted_inputs"] = self._accepted_inputs
            return True

    def stop(self) -> dict:
        with self._lifecycle:
            with self._lock:
                if not self._active:
                    raise RuntimeError("No demonstration is active")
                self._active = False
            # Callbacks racing with stop now discard their input. Never resume
            # autonomy until every listener has stopped and the trace is durable.
            self._stop_hooks()
            with self._lock:
                ended_at = time.monotonic()
                self._break_context("no_after_frame")
                for gap in self._trace["gaps"]:
                    if gap["ended_at"] is None:
                        gap["ended_at"] = ended_at
                self._trace["ended_at"] = utc_now()
                self._trace["steps"].sort(key=lambda step: step["input"]["timestamp"])
                self._paused = False
                trace = deepcopy(self._trace)
                memory_id = self.store.add_memory("episodic", {"demonstration": trace},
                    {"demonstration_id": trace["id"], "evidence": "pixels_and_input"}, confidence=1.0)
                self.store.append_event("demonstration_stopped", {"id": trace["id"], "memory_id": memory_id,
                    "steps": len(trace["steps"]), "frames": len(trace["frames"]), "truncated": trace["truncated"]})
                return trace
