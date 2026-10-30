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
