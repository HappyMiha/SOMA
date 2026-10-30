"""Durability, provenance and crash-recovery guarantees using real SQLite/files."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from soma.core import ScreenFrame
from soma.memory import MEMORY_KINDS, MemoryIntegrityError, MemoryStore


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "data"
        self.store = MemoryStore(self.directory)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def reopen(self):
        self.store.close()
        self.store = MemoryStore(self.directory)

    def test_identity_and_checkpoint_survive_provider_change_and_restart(self):
        identity = self.store.identity()
        identity["aliases"].append("unrelated")
        self.assertEqual(self.store.identity()["aliases"], ["SOMA", "SOMIK"])
        persona_id = identity["persona_id"]
        self.store.checkpoint({"state": "ASLEEP", "provider": "old", "unfinished": ["learn"]})
        self.reopen()
        self.assertEqual(self.store.identity()["persona_id"], persona_id)
        self.assertEqual(self.store.latest_checkpoint()["unfinished"], ["learn"])
        self.store.checkpoint({"state": "AWAKE/AUTONOMOUS", "provider": "new"})
        self.reopen()
        self.assertEqual(self.store.identity()["persona_id"], persona_id)
        self.assertEqual(self.store.latest_checkpoint()["provider"], "new")

    def test_all_six_memory_kinds_preserve_unicode_provenance_and_uncertainty(self):
        for kind in MEMORY_KINDS:
            self.store.add_memory(kind, {"principle": "Навчання через видимий екран", "kind": kind},
                                  {"frame_id": "screen-1", "event_ids": [1], "classification": "inference"}, 0.42)
        matches = self.store.recall("НАВЧАННЯ екран", limit=12)
        self.assertEqual({record["kind"] for record in matches}, MEMORY_KINDS)
        self.assertTrue(all(record["confidence"] == 0.42 for record in matches))
        self.assertEqual(matches[0]["source"]["classification"], "inference")
        self.assertEqual(self.store.recall("nonexistent"), [])
        self.assertEqual(len(self.store.recall(limit=2)), 2)
        self.reopen()
        self.assertEqual(len(self.store.recall("навчання")), 6)

    def test_invalid_memory_cannot_enter_history(self):
        count = len(self.store.events(100))
        for confidence in (-0.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                self.store.add_memory("semantic", "claim", {"event_id": 1}, confidence)
        with self.assertRaises(ValueError):
            self.store.add_memory("semantic", "claim", {})
        with self.assertRaises(ValueError):
            self.store.add_memory("unknown", "claim", {"event_id": 1})
        self.assertEqual(len(self.store.events(100)), count)

    def test_goal_revisions_keep_past_history(self):
        goal_id = self.store.put_goal({"description": "Learn the visible application", "origin": "self"})
        self.store.put_goal({"id": goal_id, "description": "Learn the visible application", "status": "completed"})
        self.assertEqual(len(self.store.goals()), 1)
        self.assertEqual(self.store.goals()[0]["status"], "completed")
        revisions = [event for event in self.store.events() if event["kind"] == "goal.updated"]
        self.assertEqual([event["data"]["status"] for event in revisions], ["active", "completed"])

    def test_pending_action_is_persisted_before_dispatch_and_never_marked_success(self):
        action = {"kind": "click", "args": {"x": 0.5, "y": 0.2}, "expected": "Sent confirmation"}
        action_id = self.store.begin_action(action, "before")
        self.reopen()
        pending = self.store.pending_actions()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["action"], action)
        self.assertIsNone(pending[0]["outcome"])
        self.store.finish_action(action_id, {"status": "uncertain", "evidence": "No clear confirmation"}, "after")
        self.assertEqual(self.store.pending_actions()[0]["status"], "uncertain")
        self.assertEqual(self.store.events()[-1]["data"]["outcome"]["status"], "uncertain")
        self.reopen()
        self.assertEqual(self.store.pending_actions()[0]["outcome"]["status"], "uncertain")
        self.store.finish_action(action_id, {"status": "failure", "evidence": "Draft remains visible"}, "fresh")
        self.assertEqual(self.store.pending_actions(), [])
        with self.assertRaises(ValueError):
            self.store.finish_action(action_id, {"status": "success"}, "after")

    def test_intent_and_journal_insert_are_one_transaction(self):
        count = len(self.store.events(100))
        self.store._db.execute("CREATE TRIGGER reject_action BEFORE INSERT ON actions BEGIN SELECT RAISE(ABORT,'simulated disk transaction failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.begin_action({"kind": "click"}, "before")
        self.assertEqual(len(self.store.events(100)), count)
        self.assertEqual(self.store.pending_actions(), [])

    def test_real_process_crash_preserves_committed_wal_and_identity(self):
        persona_id = self.store.identity()["persona_id"]
        self.store.close()
        code = (
            "from pathlib import Path; import sys,os; from soma.memory import MemoryStore; "
            "s=MemoryStore(Path(sys.argv[1])); s.begin_action({'kind':'click'},'before-crash'); "
            "s.checkpoint({'state':'WAKE_RECOVER','unfinished':'verify before any repeat'}); os._exit(17)"
        )
        result = subprocess.run([sys.executable, "-c", code, str(self.directory)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.store = MemoryStore(self.directory)
        self.assertEqual(self.store.identity()["persona_id"], persona_id)
        self.assertEqual(len(self.store.pending_actions()), 1)
        self.assertEqual(self.store.latest_checkpoint()["unfinished"], "verify before any repeat")

    def test_append_only_triggers_and_startup_hash_verification(self):
        event_id = self.store.append_event("observation", {"visible": "original"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("DELETE FROM events WHERE id=?", (event_id,))
        self.store.close()
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute("DROP TRIGGER events_no_update")
            connection.execute("UPDATE events SET data=? WHERE id=?", ('{"visible":"changed"}', event_id))
            connection.commit()
        with self.assertRaisesRegex(MemoryIntegrityError, "hash chain"):
            MemoryStore(self.directory)

    def test_checkpoint_is_verified_against_history(self):
        self.store.checkpoint({"state": "ASLEEP"})
        self.store.close()
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute("DROP TRIGGER checkpoint_no_update")
            connection.execute("UPDATE checkpoints SET state=?", ('{"state":"invented"}',))
            connection.commit()
        with self.assertRaisesRegex(MemoryIntegrityError, "Checkpoint"):
            MemoryStore(self.directory)

    def test_rewritten_identity_is_rejected_instead_of_reborn(self):
        identity = self.store.identity()
        identity["persona_id"] = "replacement-persona"
        self.store.close()
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            connection.execute("DROP TRIGGER identity_no_update")
            connection.execute("UPDATE metadata SET value=? WHERE key='identity'", (json.dumps(identity),))
            connection.commit()
        with self.assertRaisesRegex(MemoryIntegrityError, "Identity"):
            MemoryStore(self.directory)

    def test_shared_store_serializes_worker_and_ui_writes(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda number: self.store.append_event("worker", {"number": number}), range(60)))
        self.assertEqual(len(set(ids)), 60)
        recent = self.store.events(limit=7)
        self.assertEqual([record["id"] for record in recent], sorted(ids)[-7:])
        self.reopen()
        self.assertEqual(len(self.store.events(100)), 61)
        self.assertEqual(self.store._db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.store._db.execute("PRAGMA synchronous").fetchone()[0], 2)

    def test_frame_quota_protects_pending_before_frame_and_records_pruning(self):
        self.store.max_frame_bytes = 10
        before = ScreenFrame(b"aaaa", 1, 1, frame_id="../outside")
        first_path = Path(self.store.save_frame(before))
        self.assertEqual(first_path.parent, self.store.frames_dir)
        self.store.begin_action({"kind": "wait"}, before.frame_id)
        second_path = Path(self.store.save_frame(ScreenFrame(b"bbbb", 1, 1)))
        third_path = Path(self.store.save_frame(ScreenFrame(b"cccc", 1, 1)))
        self.assertTrue(first_path.is_file())
        self.assertFalse(second_path.exists())
        self.assertTrue(third_path.is_file())
        self.assertIn("frame.pruned", [event["kind"] for event in self.store.events()])
        with self.assertRaises(ValueError):
            self.store.save_frame(ScreenFrame(b"changed", 1, 1, frame_id=before.frame_id))
        self.assertEqual(list(self.store.frames_dir.glob("*.tmp")), [])

    def test_backup_uses_consistent_database_and_only_app_owned_frames(self):
        frame_path = Path(self.store.save_frame(ScreenFrame(b"image", 1, 1)))
        self.store.add_memory("episodic", "I observed a screen", {"frame": frame_path.name})
        self.store.checkpoint({"state": "ASLEEP"})
        (self.directory / "unrelated.txt").write_text("not part of known app storage", encoding="utf-8")
        archive_path = self.directory / "backup.zip"
        self.store.backup(archive_path)
        restored_path = self.directory / "restored"
        with zipfile.ZipFile(archive_path) as archive:
            self.assertNotIn("unrelated.txt", archive.namelist())
            self.assertIn("frames/" + frame_path.name, archive.namelist())
            self.assertEqual(json.loads(archive.read("backup.json"))["schema_version"], 1)
            archive.extractall(restored_path)
        restored = MemoryStore(restored_path)
        try:
            self.assertEqual(restored.identity()["persona_id"], self.store.identity()["persona_id"])
            self.assertEqual(restored.latest_checkpoint(), {"state": "ASLEEP"})
            self.assertEqual(restored.recall("observed")[0]["kind"], "episodic")
        finally:
            restored.close()

    def test_restore_keeps_persona_pending_actions_and_previous_history(self):
        persona_id = self.store.identity()["persona_id"]
        self.store.begin_action({"kind": "click"}, "before")
        self.store.checkpoint({"state": "ASLEEP", "intention": "verify the result"})
        archive = self.directory / "backup.zip"
        self.store.backup(archive)
        self.store.append_event("after_backup", {"preserve": "this later history"})
        with self.assertRaisesRegex(ValueError, "Close"):
            MemoryStore.restore_backup(archive, self.directory)
        self.store.close()
        previous = MemoryStore.restore_backup(archive, self.directory)
        self.store = MemoryStore(self.directory)
        self.assertEqual(self.store.identity()["persona_id"], persona_id)
        self.assertEqual(len(self.store.pending_actions()), 1)
        self.assertEqual(self.store.latest_checkpoint()["intention"], "verify the result")
        self.assertTrue(previous.is_dir())
        older = MemoryStore(previous)
        try:
            self.assertIn("after_backup", [event["kind"] for event in older.events()])
        finally:
            older.close()

    def test_corrupt_restore_preserves_existing_identity_and_data(self):
        persona_id = self.store.identity()["persona_id"]
        archive = self.directory / "corrupt.zip"
        self.store.backup(archive)
        # Corrupt frame-free backup database bytes without touching live data.
        with zipfile.ZipFile(archive) as source:
            manifest = source.read("backup.json")
        with zipfile.ZipFile(archive, "w") as destination:
            destination.writestr("backup.json", manifest)
            destination.writestr("memory.sqlite3", b"not a SQLite database")
        self.store.close()
        with self.assertRaises(MemoryIntegrityError):
            MemoryStore.restore_backup(archive, self.directory)
        self.store = MemoryStore(self.directory)
        self.assertEqual(self.store.identity()["persona_id"], persona_id)
        self.assertEqual(list(self.directory.parent.glob("." + self.directory.name + "-restore-*")), [])

    def test_restore_rejects_traversal_and_symlink_entries(self):
        self.store.close()
        for filename, symlink in (("../escape", False), ("frames/" + "a" * 64 + ".png", True)):
            with self.subTest(filename=filename):
                archive = self.directory / "invalid.zip"
                with zipfile.ZipFile(archive, "w") as destination:
                    entry = zipfile.ZipInfo(filename)
                    if symlink:
                        entry.create_system = 3
                        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                    destination.writestr(entry, "external")
                with self.assertRaises(MemoryIntegrityError):
                    MemoryStore.restore_backup(archive, self.directory)
        self.store = MemoryStore(self.directory)

    def test_uncertain_actions_keep_before_and_after_pixels_during_pruning(self):
        self.store.max_frame_bytes = 12
        first = ScreenFrame(b"aaaa", 1, 1)
        second = ScreenFrame(b"bbbb", 1, 1)
        before_path = Path(self.store.save_frame(first))
        action_id = self.store.begin_action({"kind": "click"}, first.frame_id)
        after_path = Path(self.store.save_frame(second))
        self.store.finish_action(action_id, {"status": "uncertain"}, second.frame_id)
        self.store.save_frame(ScreenFrame(b"cccc", 1, 1))
        self.store.save_frame(ScreenFrame(b"dddd", 1, 1))
        self.assertTrue(before_path.is_file())
        self.assertTrue(after_path.is_file())
        self.reopen()
        self.assertEqual(len(self.store.pending_actions()), 1)

    def test_frame_checksum_corruption_blocks_startup(self):
        path = Path(self.store.save_frame(ScreenFrame(b"original", 1, 1)))
        self.store.close()
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(MemoryIntegrityError, "pixels"):
            MemoryStore(self.directory)

    def test_interrupted_frame_write_cannot_leave_unbounded_orphan_images(self):
        self.store._db.execute("CREATE TRIGGER reject_frame BEFORE INSERT ON frames BEGIN SELECT RAISE(ABORT,'simulated full disk'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_frame(ScreenFrame(b"image", 1, 1))
        self.assertEqual(list(self.store.frames_dir.iterdir()), [])
        orphan = self.store.frames_dir / ("a" * 64 + ".png")
        orphan.write_bytes(b"interrupted before journal commit")
        unrelated = self.store.frames_dir / "unrelated.txt"
        unrelated.write_text("not an app-generated frame", encoding="utf-8")
        self.reopen()
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.exists())

    def test_demonstration_queue_survives_crash_before_checkpoint(self):
        trace = {"id": "lesson-1", "events": [{"kind": "click"}], "frame_paths": []}
        self.store.add_memory("episodic", {"demonstration": trace}, {"recording": "lesson-1"})
        self.reopen()
        self.assertEqual(self.store.pending_demonstrations(), [trace])
        self.store.append_event("skill_acquired", {"name": "Open visible menu", "demonstration": trace["id"]})
        self.reopen()
        self.assertEqual(self.store.pending_demonstrations(), [])
        self.assertEqual(len(self.store.recall("lesson")), 1)

    def test_interrupted_restore_marker_blocks_accidental_rebirth(self):
        self.store.close()
        marker = MemoryStore._restore_marker(self.directory)
        marker.write_text("{}", encoding="utf-8")
        try:
            with self.assertRaisesRegex(MemoryIntegrityError, "interrupted"):
                MemoryStore(self.directory)
        finally:
            marker.unlink()

    def test_private_only_demonstration_is_not_reloaded_after_being_marked_unusable(self):
        trace = {"id": "private-only", "events": [], "frame_paths": []}
        self.store.add_memory("episodic", {"demonstration": trace}, {"recording": trace["id"]})
        self.store.append_event("demonstration_unusable", {"id": trace["id"], "reason": "no retained visual evidence"})
        self.reopen()
        self.assertEqual(self.store.pending_demonstrations(), [])

    def test_interrupted_demonstration_journal_merges_without_duplicate_completed_trace(self):
        demonstration_id = "crash-during-teaching"
        self.store.append_event("demonstration_started", {"id": demonstration_id, "started_at": "2026-10-30T12:00:00Z"})
        self.store.append_event("demonstration_frame", {"id": demonstration_id, "index": 0,
            "frame": {"frame_id": "before", "captured_at": 1, "available_at": 1.1},
            "paired_steps": [], "omitted_inputs_no_frame": 0})
        self.store.append_event("demonstration_input", {"id": demonstration_id, "index": 0,
            "step": {"before_frame_id": "before", "after_frame_id": None,
                     "input": {"timestamp": 2, "kind": "key_down", "args": {"key": "a"}}}, "accepted_inputs": 1})
        self.reopen()
        pending = self.store.pending_demonstrations()
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0]["interrupted"])
        self.assertIsNone(pending[0]["steps"][0]["after_frame_id"])
        completed = {**pending[0], "ended_at": "2026-10-30T12:01:00Z", "interrupted": False}
        self.store.add_memory("episodic", {"demonstration": completed}, {"demonstration_id": demonstration_id})
        self.reopen()
        self.assertEqual(self.store.pending_demonstrations(), [completed])


if __name__ == "__main__":
    unittest.main()
