"""The only desktop boundary: monitor pixels and native input events."""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time

from soma.core import Action, Monitor, ScreenFrame


class BodyUnavailable(RuntimeError):
    pass


class InputInhibited(RuntimeError):
    pass


def _platform_backend() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform.startswith("linux"):
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            raise BodyUnavailable("Wayland capture/input is unavailable: a tested ScreenCast/RemoteDesktop portal adapter is required.")
        if not os.environ.get("DISPLAY"):
            raise BodyUnavailable("An interactive Linux X11 session with DISPLAY is required.")
        return "xorg"
    raise BodyUnavailable("SOMA currently supports Windows and Linux/X11 desktop adapters.")


def _input_devices(backend):
    # Pynput must never silently select uinput or an unrelated fallback backend.
    os.environ["PYNPUT_BACKEND_MOUSE"] = backend
    os.environ["PYNPUT_BACKEND_KEYBOARD"] = backend
    mouse = importlib.import_module("pynput.mouse")
    keyboard = importlib.import_module("pynput.keyboard")
    if not all(module.Controller.__module__.endswith("_" + backend) for module in (mouse, keyboard)):
        raise BodyUnavailable("Pynput was already initialized with a different input backend.")
    return mouse.Controller(), keyboard.Controller(), mouse.Button, keyboard.Key


def _check_desktop():
    if sys.platform != "win32":
        return
    # Desktop identity is session/security state, never application metadata.
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    desktop = user32.OpenInputDesktop(0, False, 0x0101)
    if not desktop:
        raise BodyUnavailable("The interactive Windows desktop is locked, secure, or unavailable.")
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)) or name.value.lower() != "default":
            raise BodyUnavailable("SOMA cannot capture or emit input on a secure Windows desktop.")
    finally:
        user32.CloseDesktop(desktop)


def _capture_factory():
    import mss
    return mss.mss()


def _png(rgb, size):
    from mss.tools import to_png
    return to_png(rgb, size)


class HumanInterfacePort:
    def __init__(self):
        self._lock = threading.RLock()
        self._observing = False
        self._closed = False
        self._pressed_keys = set()
        self._pressed_buttons = set()
        self.backend = _platform_backend()
        try:
            self._mouse, self._keyboard, self._buttons, self._keys = _input_devices(self.backend)
        except Exception as exc:
            raise BodyUnavailable(f"Native {self.backend} input initialization failed: {exc}") from exc

    def _ensure_active(self, cancel_event=None):
        if self._closed or self._observing or (cancel_event is not None and cancel_event.is_set()):
            raise InputInhibited("Input is inhibited during teaching, cancellation, or shutdown.")

    def set_observing(self, observing: bool):
        if type(observing) is not bool:
            raise ValueError("Observing must be a boolean")
        with self._lock:
            self._observing = observing
            if observing:
                self.release_all()

    def capture_monitor_pixels(self) -> ScreenFrame:
        with self._lock:
            if self._closed:
                raise BodyUnavailable("Desktop port is closed")
            _check_desktop()
            try:
                # Creation and disposal occur on the capture thread. MSS uses
                # thread-local native handles; never create it on the UI thread.
                with _capture_factory() as capture:
                    geometry = capture.monitors[0]
                    monitors = tuple(Monitor(m["left"], m["top"], m["width"], m["height"]) for m in capture.monitors[1:])
                    captured_monotonic = time.monotonic()
                    pixels = capture.grab(geometry)
                    return ScreenFrame(_png(pixels.rgb, pixels.size), geometry["width"], geometry["height"], geometry["left"], geometry["top"], monitors, captured_monotonic=captured_monotonic)
            except Exception as exc:
                raise BodyUnavailable(f"Screen pixel capture failed: {exc}") from exc

    def _emit(self, callback, cancel_event=None):
        with self._lock:
            self._ensure_active(cancel_event)
            _check_desktop()
            callback()

    def move_mouse(self, x: int, y: int):
        self._move(x, y)

    def _move(self, x, y, cancel_event=None):
        if type(x) is not int or type(y) is not int:
            raise ValueError("Mouse coordinates must be integers")
        self._emit(lambda: setattr(self._mouse, "position", (x, y)), cancel_event)

    def mouse_button(self, button: str, down: bool):
        self._button(button, down)

    def _button(self, button, down, cancel_event=None):
        if button not in {"left", "right", "middle"} or type(down) is not bool:
            raise ValueError("Invalid button event")
        native = getattr(self._buttons, button)

        def emit():
            if down:
                self._pressed_buttons.add(native)
                self._mouse.press(native)
            else:
                self._mouse.release(native)
                self._pressed_buttons.discard(native)
        self._emit(emit, cancel_event)

    def scroll_mouse(self, dx: int, dy: int):
        Action.parse({"kind": "scroll", "args": {"dx": dx, "dy": dy}})
        self._emit(lambda: self._mouse.scroll(dx, dy))

    def _resolve_key(self, key):
        if not isinstance(key, str) or not key:
            raise ValueError("Invalid key")
        if len(key) == 1:
            if key == "\n":
                return self._keys.enter
            if key == "\t":
                return self._keys.tab
            if ord(key) < 32 or 0xD800 <= ord(key) <= 0xDFFF:
                raise ValueError("Unsupported control character")
            return key
        aliases = {"win": "cmd", "super": "cmd", "control": "ctrl", "return": "enter", "escape": "esc", "pageup": "page_up", "pagedown": "page_down"}
        name = aliases.get(key.lower(), key.lower())
        supported = {"alt", "alt_l", "alt_r", "alt_gr", "backspace", "caps_lock", "cmd", "cmd_l", "cmd_r", "ctrl", "ctrl_l", "ctrl_r", "delete", "down", "end", "enter", "esc", "home", "insert", "left", "menu", "num_lock", "page_down", "page_up", "pause", "print_screen", "right", "scroll_lock", "shift", "shift_l", "shift_r", "space", "tab", "up"} | {f"f{i}" for i in range(1, 25)}
        if name not in supported or not hasattr(self._keys, name):
            raise ValueError(f"Unsupported keyboard key: {key}")
        return getattr(self._keys, name)

    def keyboard_key(self, key: str, down: bool):
        self._key(self._resolve_key(key), down)

    def _key(self, native, down, cancel_event=None):
        if type(down) is not bool:
            raise ValueError("Key state must be a boolean")

        def emit():
            if down:
                self._pressed_keys.add(native)
                self._keyboard.press(native)
            else:
                self._keyboard.release(native)
                self._pressed_keys.discard(native)
        self._emit(emit, cancel_event)

    def type_text(self, text: str):
        self._type_text(text)

    def _type_text(self, text, cancel_event=None):
        Action.parse({"kind": "type_text", "args": {"text": text}})
        # Validate the whole text before emitting its first event.
        keys = [self._resolve_key(char) for char in text]
        try:
            for key in keys:
                self._key(key, True, cancel_event)
                self._key(key, False, cancel_event)
                # Let the target process Unicode/IME packets before the next
                # character. Zero-delay Windows input can reorder WM_CHAR.
                self._wait(0.01, cancel_event)
        finally:
            self.release_all()

    def _wait(self, seconds, cancel_event):
        deadline = time.monotonic() + seconds
        while True:
            with self._lock:
                self._ensure_active(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.01, remaining))

    def validate_action(self, action: Action, frame: ScreenFrame) -> Action:
        """Validate native input and geometry without reading or emitting state."""
        action = Action.parse(action.to_dict())
        args, kind = action.args, action.kind
        if kind in {"click", "double_click", "move", "drag"}:
            start = frame.point(args["x"], args["y"])
        if kind == "drag":
            end = frame.point(args["x2"], args["y2"])
            # Check at physical-pixel resolution, including narrow gaps that
            # could fall between the twenty emitted drag movement samples.
            steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
            for step in range(1, steps):
                frame.point(args["x"] + (args["x2"] - args["x"]) * step / steps,
                            args["y"] + (args["y2"] - args["y"]) * step / steps)
        for key in (args["keys"] if kind == "hotkey" else [args["key"]] if kind == "key" else args["text"] if kind == "type_text" else []):
            self._resolve_key(key)
        return action

    def execute(self, action: Action, frame: ScreenFrame, cancel_event=None):
        action = self.validate_action(action, frame)
        args, kind = action.args, action.kind
        if kind in {"click", "double_click", "move", "drag"}:
            start = frame.point(args["x"], args["y"])
        if kind == "drag":
            points = [frame.point(args["x"] + (args["x2"] - args["x"]) * step / 20,
                                  args["y"] + (args["y2"] - args["y"]) * step / 20)
                      for step in range(1, 21)]
        keys = [self._resolve_key(k) for k in (args["keys"] if kind == "hotkey" else [args["key"]] if kind == "key" else [])]
        try:
            if kind in {"click", "double_click", "move", "drag"}:
                self._move(*start, cancel_event)
            if kind in {"click", "double_click"}:
                for count in range(2 if kind == "double_click" else 1):
                    if count:
                        self._wait(0.08, cancel_event)
                    self._button(args.get("button", "left"), True, cancel_event)
                    self._button(args.get("button", "left"), False, cancel_event)
            elif kind == "drag":
                self._button(args.get("button", "left"), True, cancel_event)
                for point in points:
                    self._move(*point, cancel_event)
                    self._wait(0.01, cancel_event)
                self._button(args.get("button", "left"), False, cancel_event)
            elif kind == "scroll":
                self._emit(lambda: self._mouse.scroll(args["dx"], args["dy"]), cancel_event)
            elif kind in {"hotkey", "key"}:
                for key in keys:
                    self._key(key, True, cancel_event)
                for key in reversed(keys):
                    self._key(key, False, cancel_event)
            elif kind == "type_text":
                self._type_text(args["text"], cancel_event)
            elif kind == "wait":
                self._wait(args["seconds"], cancel_event)
        finally:
            self.release_all()

    def release_all(self):
        with self._lock:
            errors = []
            for native in tuple(self._pressed_keys):
                try:
                    self._keyboard.release(native)
                    self._pressed_keys.discard(native)
                except Exception as exc:
                    errors.append(exc)
            for native in tuple(self._pressed_buttons):
                try:
                    self._mouse.release(native)
                    self._pressed_buttons.discard(native)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise BodyUnavailable(f"Could not release held native input: {errors[0]}") from errors[0]

    def close(self):
        with self._lock:
            self._closed = True
            self.release_all()
