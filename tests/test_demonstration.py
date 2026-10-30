import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from soma.core import ScreenFrame
from soma.demonstration import DemonstrationRecorder, _XorgStopMixin, native_hooks


class FakeStore:
    def __init__(self):
        self.events = []
        self.frames = {}
        self.memories = []

    def append_event(self, kind, data):
        self.events.append((kind, data))
        return len(self.events)

    def save_frame(self, frame):
        self.frames[frame.frame_id] = frame.png
        return "/own-data/frames/" + frame.frame_id + ".png"

    def add_memory(self, kind, content, source, confidence=0.5):
        self.memories.append((kind, content, source, confidence))
        return "memory-1"


class FakePort:
    def __init__(self):
        self.observing = False

    def set_observing(self, observing):
        self.observing = observing


class FakeHook:
    def __init__(self, callback, port):
        self.callback, self.port = callback, port
        self.started = self.stopped = self.joined = False

    def start(self):
        assert self.port.observing
        self.started = True

    def stop(self):
        assert self.port.observing
        self.stopped = True
        self.callback("key_down", {"key": "after-stop-secret"})

    def join(self, timeout=None):
        self.joined = True


class DemonstrationTests(unittest.TestCase):
    def setUp(self):
        self.store, self.port, self.hooks = FakeStore(), FakePort(), []

        def hook_factory(callback):
            self.assertTrue(self.port.observing)
            self.hooks = [FakeHook(callback, self.port), FakeHook(callback, self.port)]
            return self.hooks

        self.factory = hook_factory
        self.recorder = DemonstrationRecorder(self.store, self.port, hook_factory=hook_factory)

    def frame(self, content=b"pixels"):
        return ScreenFrame(content, 100, 100, x=-100)

    def test_no_hooks_or_recording_before_start(self):
        self.assertFalse(self.recorder.active)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "before-secret"}))
        self.assertIsNone(self.recorder.capture(self.frame(b"before-secret")))
        self.assertEqual(self.hooks, [])
        self.assertEqual(self.store.frames, {})

    def test_synchronized_before_input_after_and_explicit_resume(self):
        demonstration_id = self.recorder.start()
        before = self.frame(b"before")
        self.recorder.capture(before)
        self.assertTrue(self.recorder.record_input("mouse_down", {"x": -50, "y": 10, "button": "left"}))
        after = self.frame(b"after")
        self.recorder.capture(after)
        trace = self.recorder.stop()
        self.assertEqual(trace["id"], demonstration_id)
        self.assertEqual(trace["steps"][0]["before_frame_id"], before.frame_id)
        self.assertEqual(trace["steps"][0]["after_frame_id"], after.frame_id)
        self.assertEqual(trace["steps"][0]["input"]["args"]["x"], -50)
        self.assertTrue(all(hook.stopped and hook.joined for hook in self.hooks))
        self.assertFalse(self.recorder.active)
        self.assertTrue(self.port.observing)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "later-secret"}))
        self.assertNotIn("after-stop-secret", json.dumps(self.store.memories))
        self.assertNotIn("later-secret", json.dumps(self.store.memories))

    def test_sensitive_segment_omits_pixels_and_keys_and_breaks_pairing(self):
        self.recorder.start()
        before, secret = self.frame(), self.frame(b"private-screen")
        self.recorder.capture(before)
        self.recorder.record_input("key_down", {"key": "a"})
        self.recorder.pause_recording(True)
        self.assertTrue(self.port.observing)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "private-key"}))
        self.recorder.capture(secret)
        self.recorder.pause_recording(False)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "no-context-key"}))
        # Windows monotonic can share a coarse tick with the closed gap; use
        # explicit later times so this tests resumed input, not boundary omission.
        later = time.monotonic() + 0.1
        with patch("soma.demonstration.time.monotonic", return_value=later) as clock:
            after = ScreenFrame(b"resumed", 100, 100, captured_monotonic=later)
            self.recorder.capture(after)
            self.recorder.record_input("key_up", {"key": "b"})
            clock.return_value = later + 0.1
            final = ScreenFrame(b"resumed-after", 100, 100, captured_monotonic=later + 0.1)
            self.recorder.capture(final)
        trace = self.recorder.stop()
        self.assertNotIn(secret.frame_id, self.store.frames)
        self.assertNotIn("private-key", json.dumps(self.store.memories))
        self.assertNotIn("private-screen", json.dumps(self.store.memories))
        self.assertEqual(trace["steps"][0]["incomplete_reason"], "sensitive_gap")
        self.assertIsNone(trace["steps"][0]["after_frame_id"])
        self.assertEqual(trace["steps"][1]["before_frame_id"], after.frame_id)
        self.assertEqual(trace["steps"][1]["after_frame_id"], final.frame_id)
        self.assertEqual(trace["gaps"][0]["reason"], "sensitive")
        self.assertIsNotNone(trace["gaps"][0]["ended_at"])

    def test_no_fabricated_after_frame_or_before_frame(self):
        self.recorder.start()
        self.assertFalse(self.recorder.record_input("key_down", {"key": "not-retained"}))
        self.recorder.capture(self.frame())
        self.recorder.record_input("key_down", {"key": "a"})
        trace = self.recorder.stop()
        self.assertEqual(trace["omitted_inputs_no_frame"], 1)
        self.assertEqual(trace["steps"][0]["incomplete_reason"], "no_after_frame")
        self.assertIsNone(trace["steps"][0]["after_frame_id"])
        self.assertNotIn("not-retained", json.dumps(trace))

    def test_mouse_move_coalescing_does_not_drop_key_boundaries(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        timestamp = time.monotonic()
        self.recorder.record_input("mouse_move", {"x": 1, "y": 2}, timestamp)
        self.recorder.record_input("mouse_move", {"x": 3, "y": 4}, timestamp + 0.06)
        self.recorder.record_input("key_down", {"key": "x"}, timestamp + 0.07)
        self.recorder.record_input("mouse_move", {"x": 5, "y": 6}, timestamp + 0.08)
        trace = self.recorder.stop()
        self.assertEqual(len(trace["steps"]), 3)
        self.assertEqual(trace["steps"][0]["input"]["args"], {"x": 3, "y": 4})

    def test_event_frame_and_byte_limits_keep_motor_inhibited(self):
        for bounds in [{"max_events": 1}, {"max_frames": 1}, {"max_frame_bytes": 6}]:
            with self.subTest(bounds=bounds):
                recorder = DemonstrationRecorder(self.store, self.port, hook_factory=self.factory, **bounds)
                recorder.start()
                recorder.capture(self.frame())
                recorder.record_input("key_down", {"key": "a"})
                recorder.record_input("key_up", {"key": "a"})
                recorder.capture(self.frame())
                trace = recorder.stop()
                self.assertTrue(trace["truncated"])
                self.assertTrue(self.port.observing)
                self.assertEqual(trace["gaps"][-1]["reason"], "capacity_limit")

    def test_input_schema_cannot_accept_window_or_dom_metadata(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        for kind, args in [("window", {"title": "x"}), ("mouse_move", {"x": 1, "y": 2, "window": "x"}),
                           ("key_down", {"key": "x", "element": "x"}),
                           ("mouse_move", {"x": float("nan"), "y": 2})]:
            with self.assertRaises(ValueError):
                self.recorder.record_input(kind, args)
        self.recorder.stop()

    def test_hook_start_failure_stops_all_listeners_and_keeps_inhibited(self):
        def factory(callback):
            self.hooks = [FakeHook(callback, self.port), FakeHook(callback, self.port)]
            self.hooks[1].start = lambda: (_ for _ in ()).throw(RuntimeError("fixture failure"))
            return self.hooks

        recorder = DemonstrationRecorder(self.store, self.port, hook_factory=factory)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            recorder.start()
        self.assertFalse(recorder.active)
        self.assertTrue(self.port.observing)
        self.assertTrue(all(hook.stopped and hook.joined for hook in self.hooks))

    def test_concurrent_stop_waits_for_start_and_no_callback_leaks(self):
        entered, release = threading.Event(), threading.Event()

        def factory(callback):
            hook = FakeHook(callback, self.port)
            original_start = hook.start

            def start():
                original_start()
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test barrier timed out")

            hook.start = start
            return [hook]

        recorder = DemonstrationRecorder(self.store, self.port, hook_factory=factory)
        errors = []

        def run(operation):
            try:
                operation()
            except Exception as error:
                errors.append(error)

        starter = threading.Thread(target=run, args=(recorder.start,))
        stopper = threading.Thread(target=run, args=(recorder.stop,))
        starter.start()
        self.assertTrue(entered.wait(2))
        stopper.start()
        release.set()
        starter.join(3)
        stopper.join(3)
        self.assertFalse(starter.is_alive() or stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(recorder.active)
        self.assertTrue(self.port.observing)
        self.assertEqual(len(self.store.memories), 1)

    def test_second_start_after_stop_gets_new_identity(self):
        first = self.recorder.start()
        with self.assertRaises(RuntimeError):
            self.recorder.start()
        self.recorder.stop()
        second = self.recorder.start()
        self.assertNotEqual(first, second)
        self.assertEqual(self.recorder.stop()["steps"], [])

    def test_native_callbacks_do_not_stop_listeners_when_input_is_omitted(self):
        class MouseListener:
            def __init__(self, **callbacks):
                self.callbacks = callbacks

        class KeyboardListener(MouseListener):
            pass

        MouseListener.__module__ = "pynput.mouse._win32"
        KeyboardListener.__module__ = "pynput.keyboard._win32"
        fake = SimpleNamespace(mouse=SimpleNamespace(Listener=MouseListener), keyboard=SimpleNamespace(Listener=KeyboardListener))
        with patch("soma.demonstration.sys.platform", "win32"), patch.dict("sys.modules", {"pynput": fake}), patch.dict("os.environ", clear=False):
            hooks = native_hooks(lambda *args: False)
        self.assertIsNone(hooks[0].callbacks["on_move"](1, 2))
        self.assertIsNone(hooks[1].callbacks["on_press"](SimpleNamespace(char="a")))

    def test_wayland_is_rejected_before_importing_listeners(self):
        with patch("soma.demonstration.sys.platform", "linux"), patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            with self.assertRaisesRegex(RuntimeError, "Wayland"):
                native_hooks(lambda *args: None)

    def test_surrogate_key_units_are_explicit_utf8_safe_tokens(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.recorder.record_input("key_down", {"key": "\ud83d"})
        self.recorder.record_input("key_down", {"key": "\ude00"})
        trace = self.recorder.stop()
        self.assertEqual([step["input"]["args"]["key"] for step in trace["steps"]], ["U+D83D", "U+DE00"])
        json.dumps(trace, ensure_ascii=False).encode("utf-8")

    def test_frame_begun_before_input_cannot_be_its_after_evidence(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        timestamp = time.monotonic()
        self.recorder.record_input("key_down", {"key": "a"}, timestamp)
        overlapped = ScreenFrame(b"during-input", 100, 100, captured_monotonic=timestamp - 0.1)
        self.recorder.capture(overlapped)
        final = ScreenFrame(b"after", 100, 100, captured_monotonic=timestamp + 0.1)
        self.recorder.capture(final)
        trace = self.recorder.stop()
        self.assertEqual(trace["steps"][0]["after_frame_id"], final.frame_id)

    def test_delayed_private_frame_and_input_are_rejected_after_resume(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.recorder.pause_recording(True)
        private_time = time.monotonic()
        private_frame = ScreenFrame(b"delayed-private-pixels", 100, 100, captured_monotonic=private_time)
        self.recorder.pause_recording(False)
        self.assertIsNone(self.recorder.capture(private_frame))
        # A queued native callback can arrive after another thread resumed recording.
        self.assertFalse(self.recorder.record_input("key_down", {"key": "delayed-private-key"}, private_time))
        trace = self.recorder.stop()
        self.assertNotIn(private_frame.frame_id, self.store.frames)
        self.assertNotIn("delayed-private-key", json.dumps(trace))

    def test_private_gap_metadata_is_bounded(self):
        self.recorder.start()
        for _ in range(200):
            self.recorder.pause_recording(True)
            self.recorder.pause_recording(False)
        trace = self.recorder.stop()
        self.assertTrue(trace["truncated"])
        self.assertLessEqual(len(trace["gaps"]), 129)
        self.assertTrue(self.port.observing)

    def test_xorg_stop_uses_control_connection_and_flushes_without_input(self):
        calls = []
        control = SimpleNamespace(record_disable_context=lambda value: calls.append(("disable", value)),
                                  flush=lambda: calls.append(("flush",)))
        listener = SimpleNamespace(_context=42, _display_stop=control)
        _XorgStopMixin._stop_platform(listener)
        self.assertEqual(calls, [("disable", 42), ("flush",)])

    def test_stopped_listener_callback_runtime_error_is_not_suppressed(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.hooks[0].join = lambda timeout=None: (_ for _ in ()).throw(RuntimeError("listener callback failed"))
        self.hooks[0].is_alive = lambda: False
        with self.assertRaisesRegex(RuntimeError, "Could not confirm") as caught:
            self.recorder.stop()
        self.assertEqual(str(caught.exception.__cause__), "listener callback failed")
        self.assertTrue(self.port.observing)
        self.assertEqual(self.store.memories, [])

    def test_only_never_started_thread_join_error_is_ignored(self):
        class NeverStarted(threading.Thread):
            def stop(self):
                pass

        listener = NeverStarted()
        self.assertIsNone(listener.ident)
        self.recorder._hooks = [listener]
        self.recorder._stop_hooks()
        self.assertEqual(self.recorder._hooks, [])


if __name__ == "__main__":
    unittest.main()
