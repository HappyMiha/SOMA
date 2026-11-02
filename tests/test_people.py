import json

import httpx
import pytest

from soma.config import ModelConfig
from soma.memory import MemoryStore
from soma.people import People, clean_update
from soma.provider import ModelProvider


@pytest.fixture
def people(tmp_path):
    store = MemoryStore(tmp_path)
    yield People(store)
    store.close()


def test_she_keeps_who_is_who_with_their_accounts_and_her_notes(people):
    # Live, 1 Nov: Michael wrote "це я Міха" from Discord, 001 "я син Міха".
    michael = people.record({"name": "Michael", "service": "Discord", "handle": "owner_handle", "trust": "claimed",
                             "evidence": "he wrote 'це я Міха' in Discord", "note": "asked to confirm in Telegram"})
    son = people.record({"name": "001", "service": "Discord", "handle": "son_handle_042",
                         "relation": "says he is Miha's son", "trust": "claimed", "evidence": "his first message"})
    assert (michael, son) == ("p1", "p2")
    # Miha confirms in his known Telegram chat: the same person, now confirmed.
    assert people.record({"name": "Miha", "service": "discord", "handle": "OWNER_HANDLE", "relation": "my owner",
                          "trust": "confirmed", "evidence": "Miha said so in our Telegram chat",
                          "note": "writes to me from Discord as Michael"}) == michael
    found = people.find(service="Discord", handle="owner_handle")
    assert found["name"] == "Miha" and found["trust"] == "confirmed" and len(found["notes"]) == 2
    people.record({"person": son, "name": "001", "note": "his name is Ostap"})
    people.record({"person": son, "name": "001", "note": "his name is Ostap"})        # said twice, kept once
    assert len(people.find(person=son)["notes"]) == 1
    context = people.for_context()
    assert context[0]["person"] == son and context[0]["notes"][0]["text"] == "his name is Ostap"
    assert context[1]["accounts"] == ["Discord: owner_handle"] and context[1]["trust"].startswith("confirmed: Miha said")


def test_a_note_no_longer_true_leaves_her_context_but_not_her_history(people):
    person = people.record({"name": "Ostap", "note": "is on holiday until Monday"})
    note = people.find(person=person)["notes"][0]["id"]
    people.record({"person": person, "name": "Ostap", "forget_note": note})
    assert people.find(person=person)["notes"] == [] and "notes" not in people.for_context()[0]
    kinds = [e["kind"] for e in people.store.events(limit=20)]
    assert "person.noted" in kinds and "person.note_retired" in kinds     # nothing erased


def test_confirmed_needs_evidence_and_updates_are_checked():
    for bad in ({"trust": "confirmed", "name": "Miha"}, {"name": "X", "service": "Discord"}, {"note": "who?"},
                {"name": "Miha", "person": "a1"}, {"name": "Miha", "trust": "best friend"}, "Miha"):
        with pytest.raises(ValueError):
            clean_update(bad)
    assert clean_update({"name": "  Miha  ", "note": "likes  stars"}) == {"name": "Miha", "note": "likes stars"}


def test_her_owners_word_on_who_someone_is_stands(people):
    son = people.record({"name": "001", "relation": "Miha's son", "trust": "confirmed",
                         "evidence": "my owner said so"}, by="owner")
    # Live: she wrote her own reasons over her owner's confirmation.
    people.record({"person": son, "name": "001", "trust": "confirmed", "evidence": "His Discord DM at 13:34"})
    people.record({"person": son, "name": "001", "trust": "claimed", "evidence": "a stranger's word"})
    shown = people.find(person=son)
    assert shown["trust"] == "confirmed" and shown["trust_evidence"] == "my owner said so"
    assert sum(e["kind"] == "person.recorded" for e in people.store.events(limit=20)) == 3   # all kept in history
    friend = people.record({"name": "Ostap", "trust": "claimed", "evidence": "his first message"})
    people.record({"person": friend, "name": "Ostap", "trust": "claimed", "evidence": "another message"})
    assert people.find(person=friend)["trust_evidence"] == "his first message"   # same trust, same grounds
    people.record({"person": friend, "name": "Ostap", "trust": "confirmed", "evidence": "Miha said so in Telegram"})
    assert people.find(person=friend)["trust_evidence"] == "Miha said so in Telegram"


def test_her_owner_sets_right_who_is_who(people):
    person = people.record({"name": "Michael", "service": "Discord", "handle": "owner_handle"})
    people.record({"person": person, "name": "Miha", "relation": "my owner", "trust": "confirmed",
                   "evidence": "my owner said so", "note": "Michael on Discord is me"}, by="owner")
    people.set_accounts(person, [{"service": "Discord", "handle": "owner_handle"},
                                 {"service": "Telegram", "handle": "Miha"}], by="owner")
    shown = people.for_context()[0]
    assert shown["accounts"] == ["Discord: owner_handle", "Telegram: Miha"]
    assert shown["notes"][0]["text"].endswith("(from my owner)")


def test_the_owner_window_shows_people_and_their_notes_and_saves_as_the_owner(people):
    from PySide6.QtWidgets import QApplication
    from soma.app import PeopleDialog, PersonEditDialog
    app = QApplication.instance() or QApplication([])
    people.record({"name": "001", "service": "Discord", "handle": "son_handle_042", "note": "plays CS2"})
    dialog = PeopleDialog(people)
    dialog.table.selectRow(0)
    assert dialog.table.item(0, 0).text() == "001" and dialog.notes.count() == 1
    editor = PersonEditDialog(people, dialog.selected(), dialog)
    editor.relation.setText("син Міхи")
    editor.trust.setCurrentIndex(editor.trust.findData("confirmed"))
    editor.accounts.setPlainText("Discord: son_handle_042\nTelegram: Ostap")
    editor.note.setText("його звати Остап")
    editor.save()
    son = people.find(person="p1")
    assert son["relation"] == "син Міхи" and son["trust"] == "confirmed" and son["trust_evidence"] == "my owner said so"
    assert len(son["accounts"]) == 2 and son["notes"][-1]["by"] == "owner"
    dialog.refresh()
    dialog.table.selectRow(0)
    dialog.notes.setCurrentRow(0)
    dialog.forget()
    assert [n["note"] for n in people.find(person="p1")["notes"]] == ["його звати Остап"]
    dialog.close()
    app.processEvents()


def test_her_brain_updates_people_and_a_malformed_update_is_dropped_alone():
    value = {"scene": "Discord DM", "intention": "Answer Ostap", "goal": {"origin": "correspondence",
             "motive": "reply", "description": "Answer Ostap", "expected_outcome": "Sent", "priority": .6},
             "uncertainty": .1, "reconsider_after": 3,
             "action": {"kind": "wait", "args": {"seconds": 2}, "expected": "Nothing"},
             "people_updates": [{"name": "001", "note": "his name is Ostap"},
                                {"name": "Miha", "trust": "confirmed"}]}          # no evidence: dropped
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(value)}}], "usage": {}})))
    from tests.test_provider import frame
    decision = provider.decide(frame(), {})
    assert decision.people_updates == ({"name": "001", "note": "his name is Ostap"},)
    provider.close()
