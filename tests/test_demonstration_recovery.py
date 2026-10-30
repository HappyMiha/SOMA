import json
from pathlib import Path
import tempfile
import time
import tracemalloc
import unittest

from soma.core import ScreenFrame
from soma.demonstration import DemonstrationRecorder, reconstruct_interrupted_demonstrations
from soma.memory import MemoryStore


class FixturePort:
    def __init__(self):
        self.observing = False

    def set_observing(self, observing):
        self.observing = observing


class DemonstrationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="soma-demo-crash-")
        self.path = Path(self.directory.name)
        self.store = MemoryStore(self.path)
        self.port = FixturePort()
        # No real hooks/threads: abandoning this object simulates process loss.
        self.recorder = DemonstrationRecorder(self.store, self.port, hook_factory=lambda callback: [])

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def restart_without_stop(self):
        self.store.close()
        self.store = MemoryStore(self.path)
        return reconstruct_interrupted_demonstrations(self.store.events(100000))

    def frame(self, content=b"fixture PNG bytes"):
        return ScreenFrame(content, 10, 10)

    def test_restart_during_demo_recovers_known_pairs_and_marks_unpaired_tail(self):
        demonstration_id = self.recorder.start()
        before = self.frame(b"before")
        self.recorder.capture(before)
        self.recorder.record_input("key_down", {"key": "a"})
        after = self.frame(b"after")
        self.recorder.capture(after)
        self.recorder.record_input("key_up", {"key": "a"})
        recovered = self.restart_without_stop()
        self.assertEqual(len(recovered), 1)
        trace = recovered[0]
        self.assertEqual(trace["id"], demonstration_id)
        self.assertTrue(trace["interrupted"])
        self.assertIsNone(trace["ended_at"])
        self.assertEqual(trace["steps"][0]["before_frame_id"], before.frame_id)
        self.assertEqual(trace["steps"][0]["after_frame_id"], after.frame_id)
        self.assertIsNone(trace["steps"][1]["after_frame_id"])
        self.assertEqual(trace["steps"][1]["incomplete_reason"], "interrupted_before_after_frame")
        self.assertTrue(all(Path(frame["path"]).is_file() for frame in trace["frames"]))
        self.assertTrue(self.port.observing)

    def test_each_accepted_input_is_durable_before_callback_returns(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.assertTrue(self.recorder.record_input("key_down", {"key": "observed"}))
        journal = self.store.events(1)[0]
        self.assertEqual(journal["kind"], "demonstration_input")
        self.assertEqual(journal["data"]["step"]["input"]["args"]["key"], "observed")
        self.assertEqual(journal["data"]["index"], 0)
        self.assertNotIn("frames", journal["data"])
        self.assertNotIn("steps", journal["data"])
        self.assertEqual(len(self.restart_without_stop()[0]["steps"]), 1)

    def test_coalesced_move_delta_updates_same_step_and_bounded_input_count(self):
        self.recorder = DemonstrationRecorder(self.store, self.port, hook_factory=lambda callback: [], max_events=2)
        self.recorder.start()
        self.recorder.capture(self.frame())
        timestamp = time.monotonic()
        self.recorder.record_input("mouse_move", {"x": 1, "y": 1}, timestamp)
        self.assertFalse(self.recorder.record_input("mouse_move", {"x": 2, "y": 2}, timestamp + 0.01))
        self.recorder.record_input("mouse_move", {"x": 3, "y": 3}, timestamp + 0.06)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "over-limit-value"}, timestamp + 0.1))
        deltas = [event["data"] for event in self.store.events(1000) if event["kind"] == "demonstration_input"]
        self.assertEqual([delta["index"] for delta in deltas], [0, 0])
        trace = self.restart_without_stop()[0]
        self.assertEqual(len(trace["steps"]), 1)
        self.assertEqual(trace["steps"][0]["input"]["args"], {"x": 3, "y": 3})
        self.assertEqual(trace["accepted_inputs"], 2)
        self.assertTrue(trace["truncated"])
        self.assertNotIn("over-limit-value", json.dumps(self.store.events(1000)))

    def test_interrupted_private_segment_retains_only_gap_metadata(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.recorder.record_input("key_down", {"key": "public"})
        self.recorder.pause_recording(True)
        self.assertFalse(self.recorder.record_input("key_down", {"key": "PRIVATE-RAW-KEY"}))
        self.assertIsNone(self.recorder.capture(self.frame(b"PRIVATE-RAW-PIXELS")))
        trace = self.restart_without_stop()[0]
        self.assertEqual(trace["gaps"][0]["reason"], "sensitive")
        self.assertIsNone(trace["gaps"][0]["ended_at"])
        self.assertEqual(trace["steps"][0]["incomplete_reason"], "sensitive_gap")
        self.assertNotIn("PRIVATE-RAW-KEY", json.dumps(self.store.events(1000)))
        for path in self.store.frames_dir.glob("*.png"):
            self.assertNotIn(b"PRIVATE-RAW-PIXELS", path.read_bytes())

    def test_completed_acquired_unusable_and_failed_demos_are_excluded(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        self.recorder.record_input("key_down", {"key": "a"})
        trace = self.recorder.stop()
        self.assertEqual(reconstruct_interrupted_demonstrations(self.store.events(1000)), [])
        # The final episodic memory alone closes the journal even if the
        # process crashes before the subsequent demonstration_stopped event.
        before_stopped = [event for event in self.store.events(1000) if event["kind"] != "demonstration_stopped"]
        self.assertEqual(reconstruct_interrupted_demonstrations(before_stopped), [])
        for terminal, key in [("skill_acquired", "demonstration"), ("demonstration_unusable", "id"), ("demonstration_failed", "id")]:
            with self.subTest(terminal=terminal):
                interrupted = [event for event in self.store.events(1000)
                               if event["kind"] not in {"demonstration_stopped", "memory.added"}]
                interrupted.append({"id": 100000, "kind": terminal, "data": {key: trace["id"]}})
                self.assertEqual(reconstruct_interrupted_demonstrations(interrupted), [])

    def test_frame_journal_contains_only_one_frame_and_pair_delta(self):
        self.recorder.start()
        self.recorder.capture(self.frame())
        for index in range(8):
            self.recorder.record_input("key_down", {"key": str(index)})
            self.recorder.capture(self.frame())
        deltas = [event["data"] for event in self.store.events(1000) if event["kind"] == "demonstration_frame"]
        self.assertEqual(len(deltas), 9)
        self.assertEqual([delta["paired_steps"] for delta in deltas[1:]], [[index] for index in range(8)])
        self.assertTrue(all("frames" not in delta and "steps" not in delta for delta in deltas))
        self.assertLess(max(len(json.dumps(delta)) for delta in deltas), 1200)

    def test_streaming_completed_history_does_not_retain_every_old_trace(self):
        def journal():
            event_id = 0
            for demonstration in range(1000):
                demonstration_id = "old-demo-" + str(demonstration)
                yield {"id": event_id, "kind": "demonstration_started", "data": {"id": demonstration_id}}
                event_id += 1
                for index in range(10):
                    yield {"id": event_id, "kind": "demonstration_input", "data": {
                        "id": demonstration_id, "index": index, "accepted_inputs": index + 1,
                        "step": {"before_frame_id": None, "after_frame_id": None,
                                 "input": {"kind": "key_down", "args": {"key": ("value-%s-%s-" % (demonstration, index)) * 3},
                                           "timestamp": float(index)}}}}
                    event_id += 1
                yield {"id": event_id, "kind": "demonstration_unusable", "data": {"id": demonstration_id}}
                event_id += 1

        tracemalloc.start()
        try:
            self.assertEqual(reconstruct_interrupted_demonstrations(journal()), [])
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # A thousand completed examples must not accumulate a thousand traces.
        self.assertLess(peak, 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
