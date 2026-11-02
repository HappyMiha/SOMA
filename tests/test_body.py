import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from soma.body import BodyUnavailable, HumanInterfacePort, InputInhibited, _platform_backend
from soma.core import Action, Monitor, ScreenFrame


class FakeMouse:
    def __init__(self, events):
        self.events = events

    @property
    def position(self):
        raise AssertionError("The body should not read cursor state")

    @position.setter
    def position(self, point):
        self.events.append(("move", point))

    def press(self, button):
        self.events.append(("button_down", button))

    def release(self, button):
        self.events.append(("button_up", button))

    def scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))


class FakeKeyboard:
    def __init__(self, events):
        self.events = events
        self.after_press = None

    def press(self, key):
        self.events.append(("key_down", key))
        if self.after_press:
            self.after_press()

    def release(self, key):
        self.events.append(("key_up", key))


class BodyTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.keyboard = FakeKeyboard(self.events)
        self.mouse = FakeMouse(self.events)
        keys = SimpleNamespace(ctrl="CTRL", enter="ENTER", tab="TAB", shift="SHIFT", cmd="WIN")
        buttons = SimpleNamespace(left="LEFT", right="RIGHT", middle="MIDDLE")
        self.patches = [patch("soma.body._platform_backend", return_value="win32"), patch("soma.body._check_desktop"), patch("soma.body._input_devices", return_value=(self.mouse, self.keyboard, buttons, keys))]
        for item in self.patches:
            item.start()
        self.body = HumanInterfacePort()
        self.frame = ScreenFrame(b"png", 200, 100, -100, 0, (Monitor(-100, 0, 200, 100),))

    def tearDown(self):
        self.body.close()
        for item in reversed(self.patches):
            item.stop()

    def test_click_maps_negative_monitor_origin(self):
        self.body.execute(Action("click", {"x": 0, "y": 1}), self.frame)
        self.assertEqual(self.events, [("move", (-100, 99)), ("button_down", "LEFT"), ("button_up", "LEFT")])

    def test_direct_constructed_actions_revalidated(self):
        for action in [Action("shell", {"command": "x"}), Action("click", {"x": float("nan"), "y": 0}), Action("type_text", {"text": "x", "clipboard": True})]:
            with self.assertRaises(ValueError):
                self.body.execute(action, self.frame)
        self.assertEqual(self.events, [])

    def test_unicode_is_individual_key_events(self):
        self.body.type_text("Привіт\n")
        self.assertEqual(self.events[:4], [("key_down", "П"), ("key_up", "П"), ("key_down", "р"), ("key_up", "р")])
        self.assertEqual(self.events[-2:], [("key_down", "ENTER"), ("key_up", "ENTER")])

    def test_all_text_is_validated_before_input(self):
        with self.assertRaises(ValueError):
            self.body.type_text("valid\x00")
        self.assertEqual(self.events, [])

    def test_teaching_interrupts_in_flight_typing_and_releases(self):
        self.keyboard.after_press = lambda: self.body.set_observing(True)
        with self.assertRaises(InputInhibited):
            self.body.type_text("abc")
        self.assertEqual(self.events, [("key_down", "a"), ("key_up", "a")])
        with self.assertRaises(InputInhibited):
            self.body.move_mouse(1, 2)
        self.keyboard.after_press = None
        self.body.set_observing(False)
        self.body.keyboard_key("b", True)
        self.body.keyboard_key("b", False)
        self.assertEqual(self.events[-2:], [("key_down", "b"), ("key_up", "b")])

    def test_cancel_event_blocks_first_input(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InputInhibited):
            self.body.execute(Action("hotkey", {"keys": ["ctrl", "a"]}), self.frame, cancel)
        self.assertEqual(self.events, [])

    def test_hotkey_validates_all_keys_then_releases_in_reverse(self):
        with self.assertRaises(ValueError):
            self.body.execute(Action("hotkey", {"keys": ["ctrl", "unknown_key"]}), self.frame)
        self.assertEqual(self.events, [])
        self.body.execute(Action("hotkey", {"keys": ["ctrl", "a"]}), self.frame)
        self.assertEqual(self.events, [("key_down", "CTRL"), ("key_down", "a"), ("key_up", "a"), ("key_up", "CTRL")])
        self.events.clear()
        self.body.execute(Action("hotkey", {"keys": ["Ctrl+A"]}), self.frame)   # live: "Alt+Tab" as one string
        self.assertEqual(self.events, [("key_down", "CTRL"), ("key_down", "a"), ("key_up", "a"), ("key_up", "CTRL")])

    def test_native_validation_is_pure_and_available_while_observing(self):
        self.body.set_observing(True)
        action = Action("type_text", {"text": "Привіт 🦆"})
        with patch("soma.body._check_desktop", side_effect=AssertionError("Validation must not query desktop state")):
            self.assertEqual(self.body.validate_action(action, self.frame), action)
        self.assertEqual(self.events, [])

    def test_unknown_native_keys_rejected_before_any_emission(self):
        for action in [Action("key", {"key": "unsupported"}), Action("hotkey", {"keys": ["ctrl", "unsupported"]})]:
            with self.assertRaises(ValueError):
                self.body.validate_action(action, self.frame)
            with self.assertRaises(ValueError):
                self.body.execute(action, self.frame)
        self.assertEqual(self.events, [])

    def test_surrogate_text_rejected_before_any_emission(self):
        for text in ["valid\ud800", "valid\udfff", "valid\x00"]:
            action = Action("type_text", {"text": text})
            with self.assertRaises(ValueError):
                self.body.validate_action(action, self.frame)
            with self.assertRaises(ValueError):
                self.body.execute(action, self.frame)
        self.assertEqual(self.events, [])

    def test_session_lock_blocks_capture_and_input(self):
        with patch("soma.body._check_desktop", side_effect=BodyUnavailable("locked")):
            with self.assertRaises(BodyUnavailable):
                self.body.move_mouse(1, 2)
            with self.assertRaises(BodyUnavailable):
                self.body.capture_monitor_pixels()
        self.assertEqual(self.events, [])

    def test_capture_lazily_opens_and_closes_on_calling_thread(self):
        calls = []
        geometry = {"left": -100, "top": 0, "width": 200, "height": 100}

        class Capture:
            monitors = [geometry, geometry]

            def __enter__(self):
                calls.append(("open", threading.get_ident()))
                return self

            def __exit__(self, *args):
                calls.append(("close", threading.get_ident()))

            def grab(self, region):
                self.assert_region = region
                return SimpleNamespace(rgb=b"rgb", size=(200, 100))

        with patch("soma.body._capture_factory", return_value=Capture()), patch("soma.body._png", return_value=b"pixel-png"):
            self.body.set_observing(True)
            frame = self.body.capture_monitor_pixels()
        self.assertEqual(frame.png, b"pixel-png")
        self.assertEqual((frame.x, frame.width), (-100, 200))
        self.assertEqual(calls, [("open", threading.get_ident()), ("close", threading.get_ident())])

    def test_teaching_interrupts_drag_and_releases_button(self):
        original_setter = FakeMouse.position.fset

        def stop_drag(point):
            original_setter(self.mouse, point)
            if any(event[0] == "button_down" for event in self.events):
                self.body.set_observing(True)
        with patch.object(FakeMouse, "position", property(fset=lambda _, point: stop_drag(point))):
            with self.assertRaises(InputInhibited):
                self.body.execute(Action("drag", {"x": 0, "y": 0, "x2": 1, "y2": 1}), self.frame)
        self.assertEqual(self.events[-1], ("button_up", "LEFT"))
        self.assertEqual(sum(event[0] == "move" for event in self.events), 2)

    def test_monitor_gap_rejected_before_move(self):
        frame = ScreenFrame(b"png", 300, 100, 0, 0, (Monitor(0, 0, 100, 100), Monitor(200, 0, 100, 100)))
        with self.assertRaises(ValueError):
            self.body.execute(Action("click", {"x": 0.5, "y": 0.5}), frame)
        self.assertEqual(self.events, [])

    def test_drag_across_narrow_monitor_gap_rejected_before_emission(self):
        frame = ScreenFrame(b"png", 300, 100, 0, 0, (Monitor(0, 0, 101, 100), Monitor(103, 0, 197, 100)))
        action = Action("drag", {"x": 0, "y": .5, "x2": 1, "y2": .5})
        with self.assertRaises(ValueError):
            self.body.validate_action(action, frame)
        with self.assertRaises(ValueError):
            self.body.execute(action, frame)
        self.assertEqual(self.events, [])

    def test_simulated_screen_scaling_mapping(self):
        # Geometry math only. This does not claim real multi-DPI validation.
        for width, height in [(1920, 1080), (3840, 2160)]:
            frame = ScreenFrame(b"png", width, height, -width, 0, (Monitor(-width, 0, width, height),))
            self.assertEqual(frame.point(0, 0), (-width, 0))
            self.assertEqual(frame.point(1, 1), (-1, height - 1))
            self.assertEqual(frame.point(0.5, 0.5), (-width // 2, height // 2))

    def test_platform_does_not_silently_use_xwayland(self):
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            with self.assertRaisesRegex(BodyUnavailable, "Wayland"):
                _platform_backend()
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(BodyUnavailable, "DISPLAY"):
                _platform_backend()
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"DISPLAY": ":0", "XDG_SESSION_TYPE": "Wayland"}, clear=True):
            with self.assertRaisesRegex(BodyUnavailable, "Wayland"):
                _platform_backend()


if __name__ == "__main__":
    unittest.main()


class OwnInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        keys = SimpleNamespace(ctrl="CTRL", enter="ENTER", tab="TAB", shift="SHIFT", cmd="WIN")
        buttons = SimpleNamespace(left="LEFT", right="RIGHT", middle="MIDDLE")
        self.patches = [patch("soma.body._platform_backend", return_value="win32"), patch("soma.body._check_desktop"),
                        patch("soma.body._input_devices", return_value=(FakeMouse(self.events), FakeKeyboard(self.events), buttons, keys))]
        for item in self.patches:
            item.start()
        self.shell = SimpleNamespace(state=(((50, 20, 100, 60),), False))
        self.shell.snapshot = lambda: self.shell.state
        self.body = HumanInterfacePort(self.shell)
        self.frame = ScreenFrame(b"png", 200, 100)

    def tearDown(self):
        self.body.close()
        for item in reversed(self.patches):
            item.stop()

    def test_pointer_actions_on_own_widget_are_refused_before_any_event(self):
        from soma.body import OwnInterfaceTarget
        inside = Action("click", {"x": 75 / 199, "y": 40 / 99})
        drag_through = Action("drag", {"x": 0, "y": .4, "x2": 1, "y2": .4})
        for action in (inside, drag_through, Action("move", {"x": 75 / 199, "y": .4})):
            with self.subTest(action=action.kind), self.assertRaises(OwnInterfaceTarget):
                self.body.execute(action, self.frame)
        self.assertEqual(self.events, [])
        self.body.execute(Action("click", {"x": 0, "y": 0}), self.frame)
        self.assertEqual(self.events[0], ("move", (0, 0)))

    def test_keyboard_is_refused_while_own_widget_has_focus(self):
        from soma.body import OwnInterfaceTarget
        self.shell.state = ((), True)
        for action in (Action("type_text", {"text": "x"}), Action("key", {"key": "enter"}), Action("hotkey", {"keys": ["ctrl", "v"]})):
            with self.subTest(action=action.kind), self.assertRaises(OwnInterfaceTarget):
                self.body.validate_action(action, self.frame)
        self.body.validate_action(Action("click", {"x": 0, "y": 0}), self.frame)
        self.body.validate_action(Action("wait", {"seconds": 1}), self.frame)

    def test_scroll_where_own_pointer_rests_on_widget_is_refused(self):
        from soma.body import OwnInterfaceTarget
        self.shell.state = ((), False)
        self.body.execute(Action("move", {"x": 75 / 199, "y": .4}), self.frame)
        self.shell.state = (((50, 20, 100, 60),), False)
        with self.assertRaises(OwnInterfaceTarget):
            self.body.validate_action(Action("scroll", {"dx": 0, "dy": -3}), self.frame)

    def test_the_hand_never_types_an_account_name_as_a_password(self):
        self.shell.state = ((), False)
        for action in (Action("type_secret", {"account": "a1"}), Action("type_new_secret", {"service": "X", "login": "y"})):
            with self.subTest(action=action.kind), self.assertRaises(ValueError):
                self.body.execute(action, self.frame)
        self.assertEqual(self.events, [])

    def test_scroll_at_a_point_first_brings_the_hand_there(self):
        from soma.body import OwnInterfaceTarget
        self.shell.state = (((50, 20, 100, 60),), False)
        self.body.execute(Action("scroll", {"dx": 0, "dy": -3, "x": 0.1, "y": 0.9}), self.frame)
        moves = [e for e in self.events if e[0] == "move"]
        self.assertEqual(moves[-1], ("move", (round(0.1 * 199), round(0.9 * 99))))
        self.assertEqual(self.events[-1], ("scroll", 0, -3))
        self.assertEqual(self.body.pointer, moves[-1][1])
        # Scrolling at the widget is refused like any pointer action, before any event.
        count = len(self.events)
        with self.assertRaises(OwnInterfaceTarget):
            self.body.execute(Action("scroll", {"dx": 0, "dy": -3, "x": 75 / 199, "y": .4}), self.frame)
        self.assertEqual(len(self.events), count)
        with self.assertRaises(ValueError):
            Action.parse({"kind": "scroll", "args": {"dx": 0, "dy": -3, "x": .5}, "expected": ""})


@unittest.skipUnless(sys.platform == "win32", "compares against the native window rectangle")
class OwnShellGeometryTests(unittest.TestCase):
    """Test-only native cross-check of the Qt-published physical geometry."""

    def native_rect(self, widget):
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.assertTrue(user32.GetWindowRect(int(widget.winId()), ctypes.byref(rect)))
        return rect.left, rect.top, rect.right, rect.bottom

    def test_published_frames_match_physical_pixels_and_cover_shell_dialogs(self):
        from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
        from soma.app import SHELL_DIALOG, own_windows
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        widget.setGeometry(120, 140, 300, 200)
        widget.show()
        dialog = QFileDialog(widget, "Резервна копія")
        dialog.setOptions(SHELL_DIALOG)
        dialog.show()
        for _ in range(5):
            app.processEvents()
        try:
            rectangles, _ = own_windows()
            native = self.native_rect(widget)
            # DWM adds invisible resize borders to the native rectangle.
            self.assertTrue(any(all(abs(a - b) <= 12 for a, b in zip(r, native)) for r in rectangles),
                            (rectangles, native))
            self.assertTrue(any(all(abs(a - b) <= 12 for a, b in zip(r, self.native_rect(dialog)))
                                for r in rectangles))
        finally:
            dialog.close()
            widget.close()
            app.processEvents()


def test_status_widget_never_holds_the_keyboard_but_a_modal_dialog_does():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
    from soma.app import own_windows
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    widget.show()
    widget.activateWindow()
    app.processEvents()
    try:
        rectangles, keyboard = own_windows()
        assert rectangles and not keyboard
        dialog = QDialog(widget)
        dialog.setModal(True)
        dialog.show()
        app.processEvents()
        assert own_windows()[1]
        dialog.close()
    finally:
        widget.close()
        app.processEvents()


def test_common_key_spellings_resolve_to_one_native_key():
    from soma.body import canonical_key
    for spelling, expected in [("PgDn", "page_down"), ("Page Down", "page_down"), ("page-up", "page_up"),
                               ("PAGEDOWN", "page_down"), ("ArrowLeft", "left"), ("Del", "delete"),
                               ("Escape", "esc"), ("Windows", "cmd")]:
        assert canonical_key(spelling) == expected, spelling
    assert canonical_key("A") == "A"


def test_a_notification_lying_over_her_widget_can_be_clicked_but_her_widget_cannot():
    from io import BytesIO
    from PIL import Image, ImageDraw
    from soma.body import OwnInterface
    widget = Image.new("RGB", (300, 200), (248, 246, 255))
    draw = ImageDraw.Draw(widget)
    draw.rectangle((10, 10, 290, 120), fill=(40, 30, 90))          # her painting
    draw.rectangle((10, 140, 120, 160), fill=(20, 20, 30))         # her name
    shell = OwnInterface()
    shell.publish(((100, 100, 400, 300),), False)
    shell.publish_looks([((100, 100, 400, 300), 300, 200, widget.convert("RGBX").tobytes())])
    def screen(paint):
        image = Image.new("RGB", (800, 500), (255, 255, 255))
        image.paste(widget, (100, 100))
        paint(ImageDraw.Draw(image))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return ScreenFrame(buffer.getvalue(), 800, 500)
    as_it_is = screen(lambda draw: None)
    assert not shell.covered([(350, 280)], as_it_is)                           # her own widget: hers alone
    toast = screen(lambda draw: draw.rectangle((180, 170, 420, 320), fill=(230, 120, 160)))   # "pin to taskbar?"
    assert shell.covered([(350, 280)], toast)                                  # its "No, thanks" is clickable
    assert not shell.covered([(120, 115)], toast)                              # the uncovered corner is not
    new_status = screen(lambda draw: draw.rectangle((110, 265, 390, 283), fill=(250, 60, 60)))   # a line changed
    assert not shell.covered([(250, 274)], new_status)
    assert not OwnInterface().covered([(250, 274)], toast)                     # no picture of it: stays hers


def test_key_names_typed_as_text_are_refused_as_a_mix_up():
    from soma.body import key_names_only
    for mistaken in ("delete delete", "Backspace", "ctrl+a backspace", "Enter", "del, del, del"):
        assert key_names_only(mistaken), mistaken
    for words in ("Тепер я знаю, що ти син Міхи", "delete this later", "Enter the room", "a", "230"):
        assert not key_names_only(words), words


def test_drag_hovers_and_pauses_like_a_hand():
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    events = []
    class Mouse:
        position = property(lambda self: None, lambda self, p: events.append(("move", time.monotonic())))
        def press(self, b): events.append(("down", time.monotonic()))
        def release(self, b): events.append(("up", time.monotonic()))
    keys = SimpleNamespace(ctrl="CTRL", enter="ENTER", tab="TAB", shift="SHIFT", cmd="WIN")
    buttons = SimpleNamespace(left="LEFT", right="RIGHT", middle="MIDDLE")
    with patch("soma.body._platform_backend", return_value="win32"), patch("soma.body._check_desktop"), \
            patch("soma.body._input_devices", return_value=(Mouse(), None, buttons, keys)):
        body = HumanInterfacePort()
        body.execute(Action("drag", {"x": .1, "y": .1, "x2": .9, "y2": .9}), ScreenFrame(b"png", 200, 100))
    kinds = [k for k, _ in events]
    assert kinds[0] == "move" and kinds[1] == "down" and kinds[-1] == "up" and kinds.count("move") == 21
    times = dict((k, t) for k, t in events if k in ("down", "up"))
    first_move = events[0][1]
    second_move = next(t for k, t in events[2:] if k == "move")
    assert times["down"] - first_move >= 0.14      # hovered before grabbing
    assert second_move - times["down"] >= 0.07     # paused after pressing
