"""The only desktop boundary: monitor pixels and native input events."""

from __future__ import annotations

import importlib
import os
import re
import sys
import threading
import time

from soma.core import Action, Monitor, ScreenFrame


class BodyUnavailable(RuntimeError):
    pass


class InputInhibited(RuntimeError):
    pass


class OwnInterfaceTarget(ValueError):
    """SOMA's own widget, tray menu and dialogs are the product shell, not her world."""


class OwnInterface:
    """Where SOMA's own Qt windows are, in physical pixels, and whether one has focus.

    Published by SOMA's own GUI thread from its own widgets only; no OS window
    enumeration, and nothing about other applications. Used solely to refuse
    input aimed at the product shell; it never reaches cognition."""

    COVER_CELL = 24      # physical pixels
    COVER_DIFF = 48      # mean difference (0..255) of a cell that shows something else
    COVER_SHARE = 0.12   # of the window: a window in front, not a status line that changed

    def __init__(self):
        self._lock = threading.Lock()
        self._published = ((), False)
        self._looks = ()

    def publish(self, rectangles, focused: bool):
        with self._lock:
            self._published = (tuple(tuple(int(v) for v in r) for r in rectangles), bool(focused))

    def publish_looks(self, looks):
        """How SOMA's own windows look now: ((left, top, right, bottom), width, height, RGBX bytes)."""
        with self._lock:
            self._looks = tuple(looks)

    def snapshot(self):
        with self._lock:
            return self._published

    def covered(self, points, frame) -> bool:
        """Whether something else lies in front of SOMA's own window at every one of these
        points, judged by pixels only: around each, the screen looks nothing like the window
        (live, a Windows "pin Wikipedia to your taskbar?" toast lay over her widget and seven
        clicks on its "No, thanks" were refused as clicks on her own widget)."""
        from io import BytesIO
        from PIL import Image, ImageChops, ImageStat
        with self._lock:
            looks = self._looks
        screen_image = None
        for x, y in points:
            look_here = next((look for look in looks if look[0][0] <= x < look[0][2] and look[0][1] <= y < look[0][3]), None)
            if look_here is None:
                return False  # no picture of her own window: it stays hers
            (left, top, right, bottom), width, height, data = look_here
            if screen_image is None:
                with Image.open(BytesIO(frame.png)) as image:
                    screen_image = image.convert("RGB")
            screen = screen_image.crop((left - frame.x, top - frame.y, right - frame.x, bottom - frame.y))
            look = Image.frombuffer("RGBX", (width, height), data, "raw", "RGBX", 0, 1).convert("RGB")
            difference = ImageChops.difference(screen, look.resize(screen.size)).convert("L")
            cell = self.COVER_CELL
            columns, rows = max(1, screen.width // cell), max(1, screen.height // cell)
            covered = {(c, r) for c in range(columns) for r in range(rows)
                       if ImageStat.Stat(difference.crop((c * cell, r * cell, (c + 1) * cell, (r + 1) * cell))).mean[0]
                       > self.COVER_DIFF}
            cx, cy = min(columns - 1, (x - left) // cell), min(rows - 1, (y - top) // cell)
            block = all((c, r) in covered for c in range(cx - 1, cx + 2) for r in range(cy - 1, cy + 2)
                        if 0 <= c < columns and 0 <= r < rows)
            if len(covered) < self.COVER_SHARE * columns * rows or not block:
                return False
        return True


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


KEY_ALIASES = {
    "win": "cmd", "windows": "cmd", "super": "cmd", "meta": "cmd", "control": "ctrl", "option": "alt",
    "return": "enter", "escape": "esc", "pageup": "page_up", "pagedown": "page_down", "pgup": "page_up",
    "pgdn": "page_down", "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "arrow_up": "up", "arrow_down": "down", "arrow_left": "left", "arrow_right": "right", "del": "delete",
    "ins": "insert", "bksp": "backspace", "spacebar": "space", "capslock": "caps_lock", "numlock": "num_lock",
    "scrolllock": "scroll_lock", "printscreen": "print_screen", "prtsc": "print_screen",
}
NAVIGATION_KEYS = {"page_up", "page_down", "up", "down", "left", "right", "home", "end"}
EDITING_KEYS = NAVIGATION_KEYS | {"delete", "backspace", "enter", "tab", "esc", "insert", "ctrl", "shift", "alt"}


def key_names_only(text: str) -> bool:
    """Text that is nothing but key names ("delete delete", "ctrl+a backspace"): keys meant
    to be pressed, not words to type (live, "delete delete" landed in a Discord message box)."""
    tokens = [token for token in re.split(r"[\s,;+]+", text.strip()) if token]
    return 0 < len(tokens) <= 8 and all(canonical_key(token) in EDITING_KEYS or
                                        (len(token) == 1 and "+" in text) for token in tokens)


def canonical_key(key: str) -> str:
    """One spelling per named key: "PgDn", "Page Down" and "page-down" are page_down."""
    if len(key) == 1:
        return key
    name = key.strip().lower().replace(" ", "_").replace("-", "_")
    return KEY_ALIASES.get(name, name)


def _capture_factory():
    import mss
    return mss.mss()


def _png(rgb, size):
    from mss.tools import to_png
    # Fast zlib level: ~124 ms instead of ~273 ms for a 1920x1080 frame on an
    # i7-1255U, for ~13 % larger files. Pixels are identical (lossless).
    return to_png(rgb, size, level=1)


class HumanInterfacePort:
    def __init__(self, own_interface: OwnInterface | None = None):
        self._lock = threading.RLock()
        self._observing = False
        self._closed = False
        self._pressed_keys = set()
        self._pressed_buttons = set()
        self.own_interface = own_interface or OwnInterface()
        self._pointer = None  # Last position the inhabitant holding the body moved the pointer to.
        self.backend = _platform_backend()
        try:
            self._mouse, self._keyboard, self._buttons, self._keys = _input_devices(self.backend)
        except Exception as exc:
            raise BodyUnavailable(f"Native {self.backend} input initialization failed: {exc}") from exc

    @property
    def pointer(self):
        """Where the inhabitant holding the body last moved the pointer (desktop pixels), if anywhere."""
        return self._pointer

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
        self._pointer = (x, y)

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
        name = canonical_key(key)
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
        """Validate native input, geometry and the own-shell exclusion; emits nothing."""
        action = Action.parse(action.to_dict())
        args, kind = action.args, action.kind
        if kind == "hotkey" and any(len(key) > 1 and "+" in key for key in args["keys"]):
            # One chord written as one string ("Alt+Tab", live) is the same chord.
            keys = [part.strip().lower() if len(part.strip()) == 1 else part.strip() for key in args["keys"]
                    for part in (key.split("+") if len(key) > 1 and "+" in key else [key]) if part.strip()]
            action = Action.parse({**action.to_dict(), "args": {**args, "keys": keys}})
            args = action.args
        if kind in {"type_secret", "type_new_secret"}:
            # Only the kernel turns these into keystrokes, after taking the
            # password from her vault; the hand never sees the account name.
            raise ValueError("A password is typed only as text taken from the vault")
        points = []
        if kind in {"click", "double_click", "move", "drag"}:
            start = frame.point(args["x"], args["y"])
            points.append(start)
        if kind == "drag":
            end = frame.point(args["x2"], args["y2"])
            # Check at physical-pixel resolution, including narrow gaps that
            # could fall between the twenty emitted drag movement samples.
            steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
            for step in range(1, steps):
                points.append(frame.point(args["x"] + (args["x2"] - args["x"]) * step / steps,
                                          args["y"] + (args["y2"] - args["y"]) * step / steps))
            points.append(end)
        if kind == "scroll":
            if "x" in args:
                points.append(frame.point(args["x"], args["y"]))
            elif self._pointer:
                points.append(self._pointer)
        if kind == "type_text" and key_names_only(args["text"]):
            raise ValueError(f"'{args['text']}' names keys, it is not text to type: press them with key "
                             "(e.g. backspace, repeated) or hotkey (e.g. ctrl+a)")
        for key in (args["keys"] if kind == "hotkey" else [args["key"]] if kind == "key" else args["text"] if kind == "type_text" else []):
            self._resolve_key(key)
        if kind != "wait":
            rectangles, focused = self.own_interface.snapshot()
            on_own = [(x, y) for x, y in points
                      if any(left <= x < right and top <= y < bottom for left, top, right, bottom in rectangles)]
            # A point over SOMA's own window is hers to click only where something else
            # visibly lies in front of it (a system notification over her widget).
            covered = getattr(self.own_interface, "covered", None)
            if on_own and not (covered is not None and covered(on_own, frame)):
                raise OwnInterfaceTarget("The target is SOMA's own widget or dialog, not her environment")
            if focused and kind in {"key", "hotkey", "type_text"}:
                raise OwnInterfaceTarget("A SOMA dialog or menu has keyboard focus; focus another program first")
        return action

    def execute(self, action: Action, frame: ScreenFrame, cancel_event=None):
        action = self.validate_action(action, frame)
        args, kind = action.args, action.kind
        if kind in {"click", "double_click", "move", "drag"} or (kind == "scroll" and "x" in args):
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
                # As a hand does it: hover first (overlay scrollbars and handles
                # appear only then), press, pause so the program registers the
                # grab, move in steps, pause, release.
                self._wait(0.15, cancel_event)
                self._button(args.get("button", "left"), True, cancel_event)
                self._wait(0.08, cancel_event)
                for point in points:
                    self._move(*point, cancel_event)
                    self._wait(0.015, cancel_event)
                self._wait(0.08, cancel_event)
                self._button(args.get("button", "left"), False, cancel_event)
            elif kind == "scroll":
                if "x" in args:
                    # The hand rests over what it is about to scroll first.
                    self._move(*start, cancel_event)
                    self._wait(0.05, cancel_event)
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
