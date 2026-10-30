from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from soma.core import LifeState, ScreenFrame
from soma.demonstration import DemonstrationRecorder, learning_evidence
from soma.kernel import LifeKernel
from soma.memory import MemoryStore


class FixturePort:
    def __init__(self, store):
        self.store = store
        self.observing = False
        self.capture_count = 0
        self.fail_capture = False
        self.resume_checkpoints = []

    def set_observing(self, observing):
        self.observing = observing
        if not observing:
            self.resume_checkpoints.append(self.store.latest_checkpoint())

    def capture_monitor_pixels(self):
        if self.fail_capture:
            raise RuntimeError("fixture desktop unavailable")
        self.capture_count += 1
        output = BytesIO()
        Image.new("RGB", (64, 32), (self.capture_count % 255, 0, 0)).save(output, format="PNG")
        return ScreenFrame(output.getvalue(), 64, 32)

    def release_all(self):
        pass

    def close(self):
        pass

    def execute(self, *args):
        raise AssertionError("Learning must never execute a coordinate macro")


class FixtureHook:
    def __init__(self):
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        pass


class FixtureProvider:
    def __init__(self):
        self.metrics = {}
        self.cancel = threading.Event()
        self.lessons = []
        self.proposal = {"name": "Visible form workflow", "purpose": "Fill a visible form with new values",
            "principles": ["Read current labels before selecting a field"],
            "visual_preconditions": ["A form and its labels are visible"],
            "steps": [{"purpose": "Choose the current field", "visible_target": "Field identified by its visible label",
                       "expected_visual_result": "The field shows focus", "coordinate_macro": {"x": 0.2, "y": 0.3}}],
            "recovery": "Inspect a fresh screenshot if focus differs", "confidence": 0.6,
            "execute": [{"kind": "click", "args": {"x": 0.2, "y": 0.3}}]}

    def learn_demonstration(self, evidence, frames):
        self.lessons.append((deepcopy(evidence), list(frames)))
        return deepcopy(self.proposal)

    def close(self):
        pass


class LearningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="soma-learning-test-")
        self.store = MemoryStore(Path(self.directory.name))
        self.port, self.provider, self.hooks = FixturePort(self.store), FixtureProvider(), []

        def factory(callback):
            self.hooks = [FixtureHook(), FixtureHook()]
            return self.hooks

        self.recorder = DemonstrationRecorder(self.store, self.port, hook_factory=factory)
        self.kernel = LifeKernel(self.store, self.port, self.provider, self.recorder)

    def tearDown(self):
        if self.recorder.active:
            self.recorder.stop()
        self.kernel._executor.shutdown(wait=True, cancel_futures=True)
        self.store.close()
        self.directory.cleanup()

    def start(self):
        self.kernel.request_teaching()
        self.kernel._controls()

    def finish(self):
        self.kernel.finish_teaching()
        self.kernel._controls()

    def test_initial_and_final_pixels_are_saved_and_checkpoint_precedes_resume(self):
        self.start()
        self.assertEqual(self.port.capture_count, 1)
        self.recorder.record_input("key_down", {"key": "a"})
        self.finish()
        self.assertEqual(self.port.capture_count, 2)
        self.assertFalse(self.recorder.active)
        self.assertTrue(all(hook.stopped for hook in self.hooks))
        trace = self.kernel._lessons[0]
        self.assertIsNotNone(trace["steps"][0]["after_frame_id"])
        self.assertEqual(self.port.resume_checkpoints[-1]["pending_lessons"][0]["id"], trace["id"])
        self.assertTrue(any("demonstration" in memory["content"] for memory in self.store.recall("", 20)))

    def test_sensitive_mode_never_captures_or_persists_its_pixel_and_key_content(self):
        self.start()
        self.recorder.record_input("key_down", {"key": "a"})
        self.kernel.set_sensitive(True)
        self.recorder.record_input("key_down", {"key": "private-login-value"})
        self.recorder.capture(ScreenFrame(b"private-pixel-value", 1, 1))
        self.kernel._last_demo_capture = 0
        self.kernel._controls()
        self.finish()
        self.assertEqual(self.port.capture_count, 1)
        serialized = json.dumps(self.store.events(1000), ensure_ascii=False)
        self.assertNotIn("private-login-value", serialized)
        for image in self.store.frames_dir.glob("*.png"):
            self.assertNotIn(b"private-pixel-value", image.read_bytes())
        self.assertEqual(self.kernel._lessons[0]["gaps"][0]["reason"], "sensitive")

    def test_initial_and_final_capture_failure_still_stop_hooks(self):
        for initial in (True, False):
            with self.subTest(initial=initial):
                self.port.fail_capture = initial
                if not initial:
                    self.start()
                    self.recorder.record_input("key_down", {"key": "a"})
                    self.port.fail_capture = True
                    self.kernel.finish_teaching()
                else:
                    self.kernel.request_teaching()
                with self.assertRaisesRegex(RuntimeError, "fixture desktop unavailable"):
                    self.kernel._controls()
                self.assertFalse(self.recorder.active)
                self.assertTrue(all(hook.stopped for hook in self.hooks))
                self.assertTrue(self.store.latest_checkpoint()["pending_lessons"])
                self.port.fail_capture = False

    def test_session_suspend_stops_hooks_without_capturing_locked_desktop(self):
        self.start()
        self.recorder.record_input("key_down", {"key": "a"})
        self.kernel.suspend()
        self.port.fail_capture = True
        self.kernel._controls()
        self.assertFalse(self.recorder.active)
        self.assertTrue(self.port.observing)
        self.assertEqual(self.kernel.state, LifeState.ASLEEP)
        self.assertEqual(self.port.capture_count, 1)
        self.assertTrue(all(hook.stopped for hook in self.hooks))

    def test_learning_reads_actual_frames_and_stores_semantic_fields_only(self):
        self.start()
        for index in range(12):
            self.recorder.record_input("key_down", {"key": chr(97 + index)})
            self.recorder.capture(self.port.capture_monitor_pixels())
        self.finish()
        trace = self.kernel._lessons[0]
        self.kernel._learn()
        evidence, frames = self.provider.lessons[0]
        self.assertEqual(len(frames), 8)
        self.assertEqual([item["frame_id"] for item in evidence["frames"]], [frame.frame_id for frame in frames])
        self.assertEqual(frames[0].frame_id, trace["frames"][0]["frame_id"])
        self.assertEqual(frames[-1].frame_id, trace["frames"][-1]["frame_id"])
        self.assertTrue(all("path" not in item for item in evidence["frames"]))
        self.assertLessEqual(len(json.dumps(evidence, ensure_ascii=False)), 24000)
        procedural = next(memory for memory in self.store.recall("", 50) if memory["kind"] == "procedural")
        self.assertNotIn("execute", procedural["content"])
        self.assertNotIn("coordinate_macro", procedural["content"]["steps"][0])
        self.assertEqual(self.store.latest_checkpoint()["pending_lessons"], [])

    def test_executable_macro_response_is_not_admitted_as_a_skill(self):
        self.start()
        self.recorder.record_input("key_down", {"key": "a"})
        self.finish()
        self.provider.proposal = {"name": "Macro", "steps": [{"kind": "click", "args": {"x": 0.3, "y": 0.4}}]}
        with self.assertRaises(Exception):
            self.kernel._learn()
        self.assertEqual(len(self.kernel._lessons), 1)
        self.assertFalse(any(memory["kind"] == "procedural" for memory in self.store.recall("", 50)))

    def test_pending_lesson_restores_from_real_checkpoint_on_restart(self):
        self.start()
        self.recorder.record_input("key_down", {"key": "a"})
        self.finish()
        demonstration_id = self.kernel._lessons[0]["id"]
        restarted = LifeKernel(self.store, self.port, self.provider, self.recorder)
        restarted.stop_event.set()
        restarted.run()
        self.assertEqual(restarted._lessons[0]["id"], demonstration_id)
        self.assertEqual(self.store.latest_checkpoint()["pending_lessons"][0]["id"], demonstration_id)

    def test_completed_lesson_in_stale_checkpoint_is_not_learned_twice(self):
        self.start()
        self.recorder.record_input("key_down", {"key": "a"})
        self.finish()
        trace = self.kernel._lessons[0]
        self.store.append_event("skill_acquired", {"demonstration": trace["id"], "name": "Known"})
        restarted = LifeKernel(self.store, self.port, self.provider, self.recorder)
        restarted.stop_event.set()
        restarted.run()
        self.assertEqual(restarted._lessons, [])

    def test_large_input_trace_is_bounded_and_movement_summarized(self):
        steps = [{"before_frame_id": "b", "after_frame_id": "a",
                  "input": {"kind": "mouse_move", "args": {"x": index, "y": 1}, "timestamp": index}}
                 for index in range(5000)]
        steps.extend({"before_frame_id": "b", "after_frame_id": "a",
                      "input": {"kind": "key_down", "args": {"key": "x" * 64}, "timestamp": 5000 + index}}
                     for index in range(5000))
        evidence = learning_evidence({"id": "fixture", "steps": steps}, [])
        self.assertEqual(evidence["steps"][0]["input"]["count"], 5000)
        self.assertLessEqual(len(evidence["steps"]), 128)
        self.assertLessEqual(len(json.dumps(evidence, ensure_ascii=False)), 24000)
        self.assertGreater(evidence["omitted_compressed_steps"], 0)

    def test_movement_summary_cannot_bridge_a_private_gap(self):
        trace = {"steps": [
            {"before_frame_id": "before", "after_frame_id": None, "incomplete_reason": "sensitive_gap",
             "input": {"kind": "mouse_move", "args": {"x": 1, "y": 2}}},
            {"before_frame_id": "resumed", "after_frame_id": "after",
             "input": {"kind": "mouse_move", "args": {"x": 3, "y": 4}}},
        ]}
        evidence = learning_evidence(trace, [])
        self.assertEqual(len(evidence["steps"]), 2)
        self.assertEqual(evidence["steps"][0]["incomplete_reason"], "sensitive_gap")


if __name__ == "__main__":
    unittest.main()
