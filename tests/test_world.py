import json
import sqlite3

import pytest

from soma.accounts import KeyringVault
from soma.memory import MemoryStore
from soma.world import FIRST, HOMES, MOVE_JOURNAL, REGISTRY, World, WorldError


def test_a_new_world_gets_its_first_inhabitant_in_a_home_of_their_own(tmp_path):
    world = World(tmp_path / "SOMA")
    somik = world.settle()
    assert somik["name"] == "SOMIK" and world.home(somik) == (tmp_path / "SOMA" / HOMES / somik["id"]).resolve()
    assert not (tmp_path / "SOMA" / "memory.sqlite3").exists()              # the world keeps no one's memory
    store = MemoryStore(world.home(somik))
    try:
        identity, profile = store.identity(), store.profile()
        assert identity["persona_id"] == somik["id"] and identity["aliases"] == ["SOMIK"]
        assert (profile["name"], profile["born"], profile["world"]) == ("SOMIK", FIRST["born"], "SOMA")
    finally:
        store.close()
    assert world.settle() == somik                                          # settling again changes nothing
    assert json.loads((tmp_path / "SOMA" / REGISTRY).read_text("utf-8"))["active"] == somik["id"]


def legacy_world(root, monkeypatch):
    """SOMIK's memory where it lived before SOMA was a world (identity named SOMA, aliases SOMA+SOMIK)."""
    import soma.memory as memory
    born = memory.new_identity
    def old_shape(name):
        identity = dict(born(name), name="SOMA", aliases=["SOMA", "SOMIK"])
        identity.pop("world")
        return identity
    with monkeypatch.context() as patch:
        patch.setattr(memory, "new_identity", old_shape)   # as builds before 2026-11-01 made it
        store = MemoryStore(root)
    persona = store.identity()["persona_id"]
    store.append_event("rest", {"intention": "Read about Cassiopeia"})
    store.close()
    (root / "model.json").write_text("{}", encoding="utf-8")
    (root / "thinking-budget.json").write_text("{}", encoding="utf-8")
    return persona


def test_somik_moves_from_the_old_folder_into_a_home_with_identity_and_history_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "SOMA"
    persona = legacy_world(root, monkeypatch)
    somik = World(root).settle()
    home = root / HOMES / persona
    assert somik["id"] == persona and somik["vault"] == "shared" and (home / "memory.sqlite3").exists()
    assert not (root / "memory.sqlite3").exists() and (root / "model.json").exists()    # the world keeps its own
    assert (root / "thinking-budget.json").exists() and not (root / MOVE_JOURNAL).exists()
    store = MemoryStore(home)
    try:
        assert store.identity()["persona_id"] == persona and store.identity()["aliases"] == ["SOMA", "SOMIK"]
        assert store.profile()["name"] == "SOMIK" and store.profile()["world"] == "SOMA"
        assert any(e["kind"] == "rest" for e in store.events(limit=20))                     # her history came along
    finally:
        store.close()


def test_an_interrupted_move_is_finished_on_the_next_start(tmp_path, monkeypatch):
    root = tmp_path / "SOMA"
    persona = legacy_world(root, monkeypatch)
    entry = {"id": persona, "name": "SOMIK", "home": f"{HOMES}/{persona}", "vault": "shared"}
    (root / MOVE_JOURNAL).write_text(json.dumps({"inhabitant": entry}), encoding="utf-8")
    (root / HOMES / persona).mkdir(parents=True)
    (root / "frames").rename(root / HOMES / persona / "frames")     # the power failed after the first rename
    World(root).settle()
    assert (root / HOMES / persona / "memory.sqlite3").exists() and not (root / "memory.sqlite3").exists()
    store = MemoryStore(root / HOMES / persona)
    store.close()


def test_two_copies_of_one_identity_are_kept_for_a_human_to_compare(tmp_path, monkeypatch):
    root = tmp_path / "SOMA"
    persona = legacy_world(root, monkeypatch)
    world = World(root)
    world.settle()
    copy = root / HOMES / persona / "memory.sqlite3"
    (root / "memory.sqlite3").write_bytes(copy.read_bytes())     # e.g. an old build started again
    with pytest.raises(WorldError):
        world.settle()
    assert (root / "memory.sqlite3").exists() and copy.exists()  # nothing overwritten, nothing deleted


def test_more_inhabitants_each_have_their_own_identity_and_home(tmp_path):
    world = World(tmp_path / "SOMA")
    somik = world.settle()
    second = world.create_inhabitant("LUNA")
    assert second["id"] != somik["id"] and world.active()["id"] == somik["id"]     # SOMIK keeps the body
    assert {i["name"] for i in world.inhabitants()} == {"SOMIK", "LUNA"}
    store = MemoryStore(world.home(second))
    try:
        assert store.profile()["name"] == "LUNA" and not store.events(limit=50)[0]["kind"].startswith("rest")
    finally:
        store.close()
    with sqlite3.connect(world.home(somik) / "memory.sqlite3") as connection:
        assert "LUNA" not in json.dumps(connection.execute("SELECT data FROM events").fetchall())


def test_the_widget_settles_its_world_and_shows_the_inhabitant_by_name(tmp_path, monkeypatch):
    # Live, the first build named the "МІЙ СВІТ" label self.world too and never settled.
    from PySide6.QtWidgets import QApplication
    from soma import app as app_module
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module.LifeWidget, "bootstrap", lambda self: None)
    widget = app_module.LifeWidget(tmp_path / "SOMA")
    try:
        widget.settle_world()
        assert widget.inhabitant["name"] == "SOMIK" and widget.name.text() == "SOMIK"
        assert widget.home == (tmp_path / "SOMA" / HOMES / widget.inhabitant["id"]).resolve()
        assert widget.teach.toolTip() == "SOMIK, дивись, я тобі покажу"
        assert widget._inhabitant_actions["people"].text() == "Люди SOMIK…"
    finally:
        widget._quitting = True
        widget.tray.hide()
        widget.close()
        application.processEvents()


def test_the_widget_steps_aside_and_comes_back_unless_moved_meanwhile(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from soma import app as app_module
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module.LifeWidget, "bootstrap", lambda self: None)
    widget = app_module.LifeWidget(tmp_path / "SOMA")
    try:
        widget.show()
        area = widget.screen().availableGeometry()
        widget.move(area.right() - widget.frameGeometry().width() - 20, area.bottom() - widget.frameGeometry().height() - 20)
        application.processEvents()
        home = widget.pos()
        widget.step_aside()
        application.processEvents()
        assert widget.pos().x() < area.center().x() and widget.pos().y() == home.y()   # out of her way
        widget.step_back()
        assert widget.pos() == home                                                      # and back again
        widget.step_aside()
        widget.move(widget.pos().x() + 30, widget.pos().y())                             # her owner moved it
        widget.step_back()
        assert widget.pos().x() < area.center().x()                                      # it stays where put
    finally:
        widget._quitting = True
        widget.tray.hide()
        widget.close()
        application.processEvents()


def test_each_inhabitant_keeps_passwords_of_their_own_and_old_ones_are_still_read(monkeypatch):
    stored = {}
    class FakeKeyring:
        class errors:
            NoKeyringError = RuntimeError
        @staticmethod
        def get_password(service, user):
            return stored.get((service, user))
        @staticmethod
        def set_password(service, user, value):
            stored[(service, user)] = value
    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
    stored[("SOMA accounts", "a2")] = "kept-before-homes"
    somik, luna = KeyringVault("p-somik", shared=True), KeyringVault("p-luna")
    assert somik.get("a2") == "kept-before-homes" and luna.get("a2") is None
    luna.set("a2", "lunas-own")
    assert stored[("SOMA accounts", "p-luna/a2")] == "lunas-own" and somik.get("a2") == "kept-before-homes"
