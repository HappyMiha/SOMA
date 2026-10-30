"""SOMA-owned durable memory; never reads application files or desktop state.

Recall is a Unicode lexical index, not a neural embedding model. New knowledge
and reflections are immutable records with explicit provenance and confidence.
"""

from contextlib import closing, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import uuid
import weakref
import zipfile

from soma.core import ScreenFrame, utc_now


SCHEMA_VERSION = 1
MEMORY_KINDS = frozenset({"episodic", "semantic", "procedural", "social", "intentions", "reflective"})
TABLES = {"metadata", "events", "goals", "memories", "memory_terms", "actions", "checkpoints", "frames"}


class MemoryIntegrityError(RuntimeError):
    """Preserve the existing identity/data and require recovery instead of rebirth."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(seq, timestamp, kind, data, previous_hash):
    return hashlib.sha256(_json([seq, timestamp, kind, data, previous_hash]).encode("utf-8")).hexdigest()


def _terms(value):
    return set(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


class MemoryStore:
    _lifecycle_lock = threading.RLock()
    _active_stores = weakref.WeakSet()

    def __init__(self, data_dir: Path, *, max_frame_bytes=256 * 1024 * 1024):
        with self._lifecycle_lock:
            self._initialize(data_dir, max_frame_bytes)
            self._active_stores.add(self)

    def _initialize(self, data_dir, max_frame_bytes):
        self.data_dir = Path(data_dir).resolve()
        if self._restore_marker(self.data_dir).exists():
            raise MemoryIntegrityError("An interrupted backup restore needs recovery; previous identity is preserved")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.data_dir / "frames"
        self.frames_dir.mkdir(exist_ok=True)
        if self.frames_dir.is_symlink():
            raise MemoryIntegrityError("Frame storage must be inside SOMA's data directory")
        self.db_path = self.data_dir / "memory.sqlite3"
        if self.db_path.is_symlink():
            raise MemoryIntegrityError("Memory database must be inside SOMA's data directory")
        self.max_frame_bytes = max_frame_bytes
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None, timeout=10)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA foreign_keys=ON")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise MemoryIntegrityError(f"Unsupported memory schema {version}; preserve this data directory")
            tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version == SCHEMA_VERSION and not TABLES <= tables:
                raise MemoryIntegrityError("Memory tables are missing; preserve data and restore a backup")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, kind TEXT NOT NULL,
                    data TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
                    source TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL,
                    event_id INTEGER NOT NULL REFERENCES events(id));
                CREATE TABLE IF NOT EXISTS memory_terms(
                    term TEXT NOT NULL, memory_id TEXT NOT NULL REFERENCES memories(id),
                    PRIMARY KEY(term, memory_id));
                CREATE TABLE IF NOT EXISTS actions(
                    id TEXT PRIMARY KEY, action TEXT NOT NULL, before_frame_id TEXT NOT NULL,
                    status TEXT NOT NULL, outcome TEXT, after_frame_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoints(
                    id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL,
                    state TEXT NOT NULL, event_id INTEGER NOT NULL REFERENCES events(id));
                CREATE TABLE IF NOT EXISTS frames(
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
                    geometry TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
                    retained INTEGER NOT NULL DEFAULT 1);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'Event history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'Event history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS memory_no_update BEFORE UPDATE ON memories
                    BEGIN SELECT RAISE(ABORT, 'Memory revisions must be new records'); END;
                CREATE TRIGGER IF NOT EXISTS memory_no_delete BEFORE DELETE ON memories
                    BEGIN SELECT RAISE(ABORT, 'Memory revisions must be new records'); END;
                CREATE TRIGGER IF NOT EXISTS checkpoint_no_update BEFORE UPDATE ON checkpoints
                    BEGIN SELECT RAISE(ABORT, 'Checkpoints are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS checkpoint_no_delete BEFORE DELETE ON checkpoints
                    BEGIN SELECT RAISE(ABORT, 'Checkpoints are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS identity_no_update BEFORE UPDATE ON metadata
                    WHEN OLD.key = 'identity'
                    BEGIN SELECT RAISE(ABORT, 'Identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS identity_no_delete BEFORE DELETE ON metadata
                    WHEN OLD.key = 'identity'
                    BEGIN SELECT RAISE(ABORT, 'Identity is immutable'); END;
            """)
            self._verify_integrity()
            with self._transaction():
                identity = self._db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if identity is None:
                    if self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]:
                        raise MemoryIntegrityError("Identity is missing from an existing history; restore a backup")
                    value = {"schema_version": SCHEMA_VERSION, "persona_id": str(uuid.uuid4()),
                             "name": "SOMA", "aliases": ["SOMA", "SOMIK"], "created_at": utc_now(),
                             "traits": {"curiosity": 0.8, "persistence": 0.7, "sociability": 0.6},
                             "motives": ["understand the visible world", "learn skills", "maintain relationships"]}
                    self._db.execute("INSERT INTO metadata VALUES('identity',?)", (_json(value),))
                    self._append_event("identity.created", value)
                else:
                    value = json.loads(identity["value"])
                    if not value.get("persona_id") or value.get("aliases") != ["SOMA", "SOMIK"]:
                        raise MemoryIntegrityError("Invalid persisted identity; restore a backup")
                    birth = self._db.execute("SELECT data FROM events WHERE kind='identity.created' ORDER BY id LIMIT 1").fetchone()
                    if birth is None or json.loads(birth[0]) != value:
                        raise MemoryIntegrityError("Identity disagrees with its original history; restore a backup")
                self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._remove_orphan_frames()
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            self._db.close()
            raise MemoryIntegrityError("Memory could not be verified; preserve data and restore a backup") from exc
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _verify_integrity(self):
        if any(row[0] != "ok" for row in self._db.execute("PRAGMA integrity_check")):
            raise MemoryIntegrityError("SQLite integrity check failed; restore a backup")
        if self._db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MemoryIntegrityError("Memory provenance links are damaged; restore a backup")
        previous, expected = "", 1
        for row in self._db.execute("SELECT * FROM events ORDER BY id"):
            digest = _hash(row["id"], row["timestamp"], row["kind"], row["data"], previous)
            if row["id"] != expected or row["previous_hash"] != previous or row["hash"] != digest:
                raise MemoryIntegrityError("Event hash chain failed; preserve data and restore a backup")
            previous, expected = digest, expected + 1
        for row in self._db.execute("SELECT c.state,c.schema_version,e.data FROM checkpoints c JOIN events e ON e.id=c.event_id"):
            event = json.loads(row["data"])
            if row["schema_version"] != SCHEMA_VERSION or event.get("state") != json.loads(row["state"]):
                raise MemoryIntegrityError("Checkpoint evidence mismatch; restore a backup")
        for row in self._db.execute("SELECT filename,sha256 FROM frames WHERE retained=1"):
            path = self._frame_path(row["filename"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise MemoryIntegrityError("Stored frame pixels failed verification; restore a backup")

    def _frame_path(self, filename):
        if not re.fullmatch(r"[0-9a-f]{64}\.png", filename):
            raise MemoryIntegrityError("Invalid app-owned frame filename")
        path = self.frames_dir / filename
        if path.is_symlink() or path.resolve().parent != self.frames_dir:
            raise MemoryIntegrityError("Frame path escapes SOMA's image storage")
        return path

    def _remove_orphan_frames(self):
        retained = {row[0] for row in self._db.execute("SELECT filename FROM frames WHERE retained=1")}
        for path in self.frames_dir.iterdir():
            owned_name = re.fullmatch(r"[0-9a-f]{64}(?:\.[0-9a-f-]{36}\.tmp|\.png)", path.name)
            if owned_name and path.name not in retained and not path.is_symlink() and path.is_file():
                path.unlink()

    def _append_event(self, kind, data):
        serialized, timestamp = _json(data), utc_now()
        previous = self._db.execute("SELECT id,hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        seq, previous_hash = (previous["id"] + 1, previous["hash"]) if previous else (1, "")
        self._db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                         (seq, timestamp, kind, serialized, previous_hash,
                          _hash(seq, timestamp, kind, serialized, previous_hash)))
        return seq

    def identity(self) -> dict:
        with self._lock:
            return json.loads(self._db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])

    def append_event(self, kind, data) -> int:
        if not isinstance(kind, str) or not kind:
            raise ValueError("Event kind is required")
        with self._transaction():
            return self._append_event(kind, data)

    def events(self, limit=30) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(0, limit),)).fetchall()
            return [{**dict(row), "data": json.loads(row["data"])} for row in reversed(rows)]

    def put_goal(self, goal: dict) -> str:
        goal = dict(goal)
        goal_id = str(goal.get("id") or uuid.uuid4())
        goal.update(id=goal_id, updated_at=utc_now())
        goal.setdefault("status", "active")
        with self._transaction():
            self._append_event("goal.updated", goal)
            self._db.execute("INSERT INTO goals VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                             (goal_id, _json(goal), goal["updated_at"]))
        return goal_id

    def goals(self) -> list[dict]:
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute("SELECT data FROM goals ORDER BY updated_at DESC,id")]

    def add_memory(self, kind, content, source, confidence=0.5) -> str:
        if kind not in MEMORY_KINDS or not content or not source:
            raise ValueError("Memory requires one of six kinds, content and provenance")
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Memory confidence must be in [0,1]")
        memory_id, created = str(uuid.uuid4()), utc_now()
        content_json, source_json = _json(content), _json(source)
        with self._transaction():
            event_id = self._append_event("memory.added", {"id": memory_id, "kind": kind,
                "content": content, "source": source, "confidence": confidence})
            self._db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?)",
                             (memory_id, kind, content_json, source_json, confidence, created, event_id))
            self._db.executemany("INSERT INTO memory_terms VALUES(?,?)",
                                 [(term, memory_id) for term in _terms(content_json)])
        return memory_id

    def recall(self, query="", limit=12) -> list[dict]:
        terms = sorted(_terms(query))[:64]
        with self._lock:
            if terms:
                placeholders = ",".join("?" for _ in terms)
                rows = self._db.execute(
                    "SELECT m.*,COUNT(t.term) AS relevance FROM memories m JOIN memory_terms t ON m.id=t.memory_id "
                    f"WHERE t.term IN ({placeholders}) GROUP BY m.id ORDER BY relevance DESC,m.created_at DESC,m.id LIMIT ?",
                    (*terms, max(0, limit))).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM memories ORDER BY created_at DESC,id LIMIT ?", (max(0, limit),)).fetchall()
            return [{**dict(row), "content": json.loads(row["content"]), "source": json.loads(row["source"])} for row in rows]

    def begin_action(self, action: dict, before_frame_id: str) -> str:
        action_id, timestamp = str(uuid.uuid4()), utc_now()
        with self._transaction():
            self._append_event("action.intent", {"id": action_id, "action": action, "before_frame_id": before_frame_id})
            self._db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)",
                             (action_id, _json(action), before_frame_id, "pending", None, None, timestamp, timestamp))
        return action_id

    def finish_action(self, action_id, outcome: dict, after_frame_id: str):
        if outcome.get("status") not in {"success", "failure", "uncertain"}:
            raise ValueError("Action outcome must distinguish success, failure and uncertainty")
        status = "uncertain" if outcome["status"] == "uncertain" else "finished"
        with self._transaction():
            changed = self._db.execute("UPDATE actions SET status=?,outcome=?,after_frame_id=?,updated_at=? WHERE id=? AND status IN ('pending','uncertain')",
                                       (status, _json(outcome), after_frame_id, utc_now(), action_id)).rowcount
            if changed != 1:
                raise ValueError("Action is not pending")
            self._append_event("action.outcome", {"id": action_id, "outcome": outcome, "after_frame_id": after_frame_id})

    def pending_actions(self) -> list[dict]:
        with self._lock:
            return [{**dict(row), "action": json.loads(row["action"]),
                     "outcome": json.loads(row["outcome"]) if row["outcome"] else None} for row in
                    self._db.execute("SELECT * FROM actions WHERE status IN ('pending','uncertain') ORDER BY created_at,id")]

    def pending_demonstrations(self) -> list[dict]:
        from soma.demonstration import reconstruct_interrupted_demonstrations
        with self._lock:
            acquired = {row[0] for row in self._db.execute(
                "SELECT json_extract(data,'$.demonstration') FROM events WHERE kind='skill_acquired' "
                "UNION SELECT json_extract(data,'$.id') FROM events WHERE kind='demonstration_unusable'")}
            relevant = ({**dict(row), "data": json.loads(row["data"])} for row in self._db.execute(
                "SELECT id,timestamp,kind,data FROM events WHERE kind LIKE 'demonstration_%' "
                "OR kind='skill_acquired' ORDER BY id"))
            traces = {trace["id"]: trace for trace in reconstruct_interrupted_demonstrations(relevant)}
            for row in self._db.execute("SELECT json_extract(content,'$.demonstration') AS trace, "
                    "json_extract(content,'$.demonstration.id') AS demonstration_id FROM memories "
                    "WHERE kind='episodic' AND json_type(content,'$.demonstration')='object' ORDER BY created_at,id"):
                if row["demonstration_id"] and row["demonstration_id"] not in acquired:
                    trace = json.loads(row["trace"])
                    traces[trace["id"]] = trace
            return list(traces.values())

    def checkpoint(self, state: dict) -> int:
        with self._transaction():
            event_id = self._append_event("checkpoint", {"schema_version": SCHEMA_VERSION, "state": state})
            cursor = self._db.execute("INSERT INTO checkpoints(schema_version,state,event_id) VALUES(?,?,?)",
                                      (SCHEMA_VERSION, _json(state), event_id))
            return cursor.lastrowid

    def latest_checkpoint(self) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT state FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None

    def save_frame(self, frame: ScreenFrame) -> str:
        if not frame.png or len(frame.png) > self.max_frame_bytes:
            raise ValueError("Frame exceeds the app-owned image storage budget")
        filename = hashlib.sha256(frame.frame_id.encode("utf-8")).hexdigest() + ".png"
        path = self._frame_path(filename)
        digest = hashlib.sha256(frame.png).hexdigest()
        with self._lock:
            existing = self._db.execute("SELECT sha256,retained FROM frames WHERE id=?", (frame.frame_id,)).fetchone()
            if existing:
                if existing["sha256"] != digest:
                    raise ValueError("An immutable frame ID cannot contain different pixels")
                if existing["retained"] and path.is_file():
                    return str(path)
            temporary = path.with_suffix("." + str(uuid.uuid4()) + ".tmp")
            committed = False
            try:
                with temporary.open("xb") as handle:
                    handle.write(frame.png)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                with self._transaction():
                    self._db.execute("INSERT INTO frames VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET retained=1",
                        (frame.frame_id, filename, digest, _json(frame.geometry()), len(frame.png), frame.timestamp))
                    self._append_event("frame.captured", {**frame.geometry(), "sha256": digest})
                committed = True
                self._prune_frames(frame.frame_id)
            finally:
                temporary.unlink(missing_ok=True)
                if not committed:
                    path.unlink(missing_ok=True)
        return str(path)

    def frame_path(self, frame_id: str) -> Path | None:
        """Resolve app-owned evidence by identity, including after portable restore."""
        with self._lock:
            row = self._db.execute("SELECT filename FROM frames WHERE id=? AND retained=1", (frame_id,)).fetchone()
            return self._frame_path(row[0]) if row else None

    def _prune_frames(self, newest_id):
        total = self._db.execute("SELECT COALESCE(SUM(size),0) FROM frames WHERE retained=1").fetchone()[0]
        candidates = self._db.execute("SELECT id,filename,size FROM frames WHERE retained=1 AND id<>? "
            "AND id NOT IN (SELECT before_frame_id FROM actions WHERE status IN ('pending','uncertain')) "
            "AND id NOT IN (SELECT after_frame_id FROM actions WHERE status IN ('pending','uncertain') AND after_frame_id IS NOT NULL) "
            "ORDER BY created_at,id", (newest_id,)).fetchall()
        for row in candidates:
            if total <= self.max_frame_bytes:
                break
            with self._transaction():
                self._db.execute("UPDATE frames SET retained=0 WHERE id=?", (row["id"],))
                self._append_event("frame.pruned", {"frame_id": row["id"], "reason": "storage budget"})
            self._frame_path(row["filename"]).unlink(missing_ok=True)
            total -= row["size"]

    def backup(self, destination: Path):
        destination = Path(destination).resolve()
        if destination == self.db_path or destination.parent == self.frames_dir:
            raise ValueError("Backup destination would overwrite live memory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + str(uuid.uuid4()) + ".tmp")
        with self._lock, tempfile.TemporaryDirectory(dir=self.data_dir) as staging:
            snapshot = Path(staging) / "memory.sqlite3"
            try:
                with closing(sqlite3.connect(snapshot)) as connection:
                    self._db.backup(connection)
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "memory.sqlite3")
                    for row in self._db.execute("SELECT filename FROM frames WHERE retained=1"):
                        archive.write(self._frame_path(row["filename"]), "frames/" + row["filename"])
                    archive.writestr("backup.json", _json({"schema_version": SCHEMA_VERSION,
                        "persona_id": self.identity()["persona_id"], "created_at": utc_now()}))
                with temporary.open("r+b") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _restore_marker(data_dir):
        return data_dir.parent / ("." + data_dir.name + ".restore-pending.json")

    @classmethod
    def restore_backup(cls, archive: Path, data_dir: Path) -> Path | None:
        """Validate off to the side, then replace closed app storage, retaining old data.

        A durable sibling marker prevents accidental rebirth if power fails between
        the two portable directory renames. No existing history is deleted.
        Returns the preserved previous directory, or None for a fresh destination.
        """
        data_dir = Path(data_dir).resolve()
        marker = cls._restore_marker(data_dir)
        with cls._lifecycle_lock:
            if any(store.data_dir == data_dir and not store._closed for store in cls._active_stores):
                raise ValueError("Close the running memory store before restoring a backup")
            if marker.exists():
                raise MemoryIntegrityError("Resolve the interrupted restore before starting another")
            data_dir.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="." + data_dir.name + "-restore-", dir=data_dir.parent))
            previous = data_dir.with_name(data_dir.name + ".before-restore-" + str(uuid.uuid4()))
            moved = False
            try:
                with zipfile.ZipFile(archive) as source:
                    seen = set()
                    for entry in source.infolist():
                        name = entry.filename
                        allowed = name in {"memory.sqlite3", "backup.json"} or re.fullmatch(r"frames/[0-9a-f]{64}\.png", name)
                        if (not allowed or name in seen or stat.S_ISLNK(entry.external_attr >> 16)
                                or "\\" in name or entry.is_dir()):
                            raise MemoryIntegrityError("Backup contains invalid, duplicate or non-app-owned paths")
                        seen.add(name)
                        target = staging.joinpath(*name.split("/"))
                        target.parent.mkdir(exist_ok=True)
                        with source.open(entry) as original, target.open("xb") as output:
                            shutil.copyfileobj(original, output)
                            output.flush()
                            os.fsync(output.fileno())
                if not {"memory.sqlite3", "backup.json"} <= seen:
                    raise MemoryIntegrityError("Backup is missing its database or manifest")
                manifest = json.loads((staging / "backup.json").read_text("utf-8"))
                if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
                    raise MemoryIntegrityError("Unsupported backup version")
                candidate = cls(staging)
                try:
                    if candidate.identity()["persona_id"] != manifest.get("persona_id"):
                        raise MemoryIntegrityError("Backup manifest and identity disagree")
                finally:
                    candidate.close()
                with marker.open("x", encoding="utf-8") as handle:
                    handle.write(_json({"previous": str(previous), "staging": str(staging),
                                        "target": str(data_dir), "persona_id": manifest["persona_id"]}))
                    handle.flush()
                    os.fsync(handle.fileno())
                if data_dir.exists():
                    os.replace(data_dir, previous)
                    moved = True
                try:
                    os.replace(staging, data_dir)
                except BaseException:
                    if moved:
                        os.replace(previous, data_dir)
                        moved = False
                    raise
                marker.unlink()
                return previous if moved else None
            except (zipfile.BadZipFile, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
                raise MemoryIntegrityError("Backup failed verification; existing identity was preserved") from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
                if marker.exists() and not moved:
                    marker.unlink()

    def close(self):
        with self._lifecycle_lock, self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
