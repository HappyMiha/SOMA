"""SOMA is the world on this PC; SOMIK, and those who come after, are its inhabitants.

The world owns what every inhabitant shares: the one physical body (monitor
pixels in, mouse and keyboard out; one inhabitant holds it at a time), the
brains it lends (model.json, the thinking budget), the painter on the GPU,
the widget and its tray, and the registry of who lives here (world.json).

Each inhabitant owns a home, inhabitants/<persona id>/, with everything that
is theirs alone: memory with an unchanging identity, frames, goals, diary,
accounts, the people they know, their look. A new inhabitant is born in a home
of their own; nothing of theirs is shared with another.

Before SOMA was a world (until 2026-11-01) SOMIK's memory lived in the world's
own folder. settle() moves it into SOMIK's home by renaming files on the same
volume, with a journal written first, so an interrupted move is finished on
the next start and never repeated or undone halfway. The identity, its id and
its whole history move unchanged.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = "world.json"
HOMES = "inhabitants"
MOVE_JOURNAL = ".moving-in.json"
LEGACY_ITEMS = ("frames", "memory.sqlite3-shm", "memory.sqlite3-wal", "memory.sqlite3")
FIRST = {"name": "SOMIK", "born": "1984-10-18"}  # the first inhabitant, as the owner introduced SOMIK


class WorldError(RuntimeError):
    """The world's folder is in a state that must be preserved for a human to look at."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _identity_of(database: Path) -> dict:
    """The identity in a memory file, read without changing it."""
    # closing(): a sqlite3 connection used as a context manager only commits, and an open
    # one keeps its -shm file, which Windows then refuses to move.
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
    if row is None:
        raise WorldError("A memory without an identity was found in SOMA's folder; it is left in place")
    return json.loads(row[0])


class World:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ registry

    def registry(self) -> dict:
        path = self.root / REGISTRY
        if not path.exists():
            return {"schema": 1, "world": "SOMA", "inhabitants": [], "active": None}
        return json.loads(path.read_text(encoding="utf-8"))

    def inhabitants(self) -> list[dict]:
        return list(self.registry()["inhabitants"])

    def inhabitant(self, inhabitant_id: str) -> dict | None:
        return next((i for i in self.inhabitants() if i["id"] == inhabitant_id), None)

    def active(self) -> dict | None:
        registry = self.registry()
        return next((i for i in registry["inhabitants"] if i["id"] == registry.get("active")), None)

    def home(self, inhabitant: dict) -> Path:
        home = (self.root / inhabitant["home"]).resolve()
        if home.parent != (self.root / HOMES).resolve():
            raise WorldError("An inhabitant's home must be inside SOMA's inhabitants folder")
        return home

    def _register(self, entry: dict, active: bool = True):
        registry = self.registry()
        registry["inhabitants"] = [i for i in registry["inhabitants"] if i["id"] != entry["id"]] + [entry]
        if active or not registry.get("active"):
            registry["active"] = entry["id"]
        _write_json(self.root / REGISTRY, registry)

    def update(self, inhabitant_id: str, **fields) -> dict:
        """Change what the world records about an inhabitant (never their memory)."""
        entry = self.inhabitant(inhabitant_id)
        if entry is None:
            raise WorldError("No such inhabitant")
        entry.update(fields)
        registry = self.registry()
        was_active = registry.get("active") == inhabitant_id
        registry["inhabitants"] = [entry if i["id"] == inhabitant_id else i for i in registry["inhabitants"]]
        if was_active and "id" in fields:
            registry["active"] = fields["id"]
        _write_json(self.root / REGISTRY, registry)
        return entry

    # ------------------------------------------------------------------ settling

    def settle(self) -> dict:
        """Bring the world's folder into shape and return the inhabitant who holds the body.

        Finishes an interrupted move, moves a memory from before SOMA was a world
        into its inhabitant's home, and gives a new world its first inhabitant."""
        from soma.memory import MemoryStore
        self._finish_move()
        legacy = self.root / "memory.sqlite3"
        if legacy.exists():
            if MemoryStore._restore_marker(self.root).exists():
                raise WorldError("A backup restore into SOMA's folder is pending; it is recovered before moving in")
            identity = _identity_of(legacy)
            if self.inhabitant(identity["persona_id"]) is not None:
                raise WorldError("This memory already has a home in SOMA; both copies are kept for a human to compare")
            entry = {"id": identity["persona_id"], "name": FIRST["name"], "born": FIRST["born"],
                     "home": f"{HOMES}/{identity['persona_id']}", "created_at": identity.get("created_at"),
                     "moved_in_at": _now(), "vault": "shared"}  # passwords kept before homes keep their old names
            _write_json(self.root / MOVE_JOURNAL, {"inhabitant": entry})
            self._finish_move()
        if not self.inhabitants():
            self.create_inhabitant(FIRST["name"], born=FIRST["born"])
        active = self.active() or self.inhabitants()[0]
        if self.registry().get("active") != active["id"]:
            self._register(active)
        return active

    def _finish_move(self):
        journal = self.root / MOVE_JOURNAL
        if not journal.exists():
            return
        entry = json.loads(journal.read_text(encoding="utf-8"))["inhabitant"]
        home = self.home(entry)
        home.mkdir(parents=True, exist_ok=True)
        for item in LEGACY_ITEMS:
            source, target = self.root / item, home / item
            if source.exists():
                if target.exists():
                    raise WorldError(f"{item} exists both in SOMA's folder and in {entry['name']}'s home")
                os.replace(source, target)  # a rename on the same volume: all or nothing
        self._register(entry)
        self._record_profile(entry)
        journal.unlink()

    def _record_profile(self, entry: dict):
        """Who the inhabitant is to themself in this world, in their own append-only memory."""
        from soma.memory import MemoryStore
        store = MemoryStore(self.home(entry))
        try:
            profile = store.profile()
            if profile.get("name") != entry["name"] or profile.get("world") != "SOMA" or (
                    entry.get("born") and profile.get("born") != entry["born"]):
                store.record_profile(name=entry["name"], born=entry.get("born"), world="SOMA")
        finally:
            store.close()

    def create_inhabitant(self, name: str, born: str | None = None) -> dict:
        """A new inhabitant, born in a home of their own with a new identity."""
        from soma.memory import MemoryStore
        homes = self.root / HOMES
        homes.mkdir(parents=True, exist_ok=True)
        nursery = homes / (".being-born-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
        store = MemoryStore(nursery, name=name)
        try:
            identity = store.identity()
            store.record_profile(name=name, born=born, world="SOMA")
        finally:
            store.close()
        home = homes / identity["persona_id"]
        os.replace(nursery, home)
        entry = {"id": identity["persona_id"], "name": name, "home": f"{HOMES}/{identity['persona_id']}",
                 "created_at": identity["created_at"], "vault": "own"}
        if born:
            entry["born"] = born
        self._register(entry, active=not self.inhabitants())
        return entry
