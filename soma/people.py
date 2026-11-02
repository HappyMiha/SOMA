"""The people an inhabitant knows: who they are to the inhabitant, their accounts, and the
inhabitant's own notes about them (kept in the inhabitant's memory).


A registry she always thinks with, like her own accounts. Everyone she has met
(p1, p2 …): who they are to her ("my owner, Miha", "Miha's son"), their
accounts by service and handle, whether who they say they are is confirmed
(on evidence from a channel she already trusts) or only claimed, and her own
notes about each one (n1, n2 …): what she will want to know next time, what
they like, asked, told her, agreed with her. Her owner asked for it: she had
the facts in her memories, but they came to mind only when her intention
happened to name the person.

Everything stays in her append-only history; a note she no longer holds true
leaves her working context, not her memory. Her owner reads and corrects the
list in the "Люди SOMA…" window; what the owner says there counts as confirmed.
"""

from __future__ import annotations

import re

TRUST = ("confirmed", "claimed", "unknown")
TEXTS = {"name": 80, "relation": 160, "evidence": 300, "service": 60, "handle": 120, "note": 400}
PEOPLE_SHOWN, NOTES_SHOWN = 24, 8
COMPACT_PEOPLE, COMPACT_NOTES = 10, 3


def clean_update(update) -> dict:
    """A validated change to the people she knows (from a decision, a dream or her owner)."""
    if not isinstance(update, dict):
        raise ValueError("A person update is an object")
    clean = {}
    for name, limit in TEXTS.items():
        value = update.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{name} is text")
            value = " ".join(value.split())[:limit]
            if value:
                clean[name] = value
    for name, prefix in (("person", "p"), ("forget_note", "n")):
        value = update.get(name)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(prefix + r"\d{1,6}", value.strip()):
                raise ValueError(f"{name} is an id like {prefix}1")
            clean[name] = value.strip()
    trust = update.get("trust")
    if trust is not None:
        if trust not in TRUST:
            raise ValueError("Trust is confirmed, claimed or unknown")
        clean["trust"] = trust
    if ("service" in clean) != ("handle" in clean):
        raise ValueError("An account of theirs is a service and a handle")
    if clean.get("trust") == "confirmed" and "evidence" not in clean:
        raise ValueError("Confirmed on what evidence?")
    if "name" not in clean and "person" not in clean:
        raise ValueError("Who is it: a name or a person id")
    return clean


def latest_news(person: dict) -> str:
    """When she last learned something about them: a change to who they are, or a note."""
    return max([person.get("recorded_at", "")] + [note.get("at", "") for note in person.get("notes", [])])


class People:
    def __init__(self, store):
        self.store = store

    def list(self) -> list[dict]:
        return self.store.people()

    def find(self, person=None, service=None, handle=None, name=None) -> dict | None:
        """Someone by id, by one of their accounts, or by name when only one person has it."""
        people = self.list()
        if person:
            return next((p for p in people if p["id"] == person), None)
        if service and handle:
            for candidate in people:
                for account in candidate.get("accounts", []):
                    if (account.get("service", "").lower() == service.lower()
                            and account.get("handle", "").lower() == handle.lower()):
                        return candidate
        if name:
            named = [p for p in people if p.get("name", "").lower() == name.lower()]
            return named[0] if len(named) == 1 else None
        return None

    def record(self, update: dict, by: str = "soma") -> str:
        """Add someone or what she learned about them; returns their id."""
        update = clean_update(update)
        person = None
        if "person" in update:
            person = self.find(person=update["person"])
            if person is None:
                raise ValueError("Unknown person")
        if person is None and "service" in update:
            person = self.find(service=update["service"], handle=update["handle"])
        if person is None and "name" in update:
            person = self.find(name=update["name"])
        entry = {key: update[key] for key in ("name", "relation", "trust") if key in update}
        if "evidence" in update:
            entry["trust_evidence"] = update["evidence"]
        if "service" in update:
            account = {"service": update["service"], "handle": update["handle"]}
            same = {(a.get("service", "").lower(), a.get("handle", "").lower()) for a in (person or {}).get("accounts", [])}
            if (account["service"].lower(), account["handle"].lower()) not in same:
                entry["account"] = account
        if person is not None:
            entry = {key: value for key, value in entry.items() if person.get(key) != value}
        person_id = person["id"] if person else None
        if person is None or entry:
            person_id = self.store.record_person({"id": person_id, **entry, "by": by})
        if "note" in update:
            notes = (person or {}).get("notes", [])
            if all(note["note"] != update["note"] for note in notes):
                self.store.note_person(person_id, update["note"], by)
        if "forget_note" in update:
            self.store.retire_note(update["forget_note"], by)
        return person_id

    def set_accounts(self, person_id: str, accounts: list[dict], by: str = "owner"):
        """Their accounts as a whole, as her owner sets them right."""
        clean = []
        for account in accounts:
            update = clean_update({"name": "-", "service": account.get("service"), "handle": account.get("handle")})
            clean.append({"service": update["service"], "handle": update["handle"]})
        self.store.record_person({"id": person_id, "accounts": clean, "by": by})

    def for_context(self, compact: bool = False) -> list[dict]:
        """Everyone she knows, the latest first: who they are, their accounts, her notes."""
        people_shown, notes_shown = (COMPACT_PEOPLE, COMPACT_NOTES) if compact else (PEOPLE_SHOWN, NOTES_SHOWN)
        people = sorted(self.list(), key=latest_news, reverse=True)
        shown = []
        for person in people[:people_shown]:
            item = {"person": person["id"], "name": person.get("name", "")}
            if person.get("relation"):
                item["relation"] = person["relation"]
            trust = person.get("trust", "unknown")
            item["trust"] = trust + (": " + person["trust_evidence"] if person.get("trust_evidence") else "")
            if person.get("accounts"):
                item["accounts"] = [f"{a['service']}: {a['handle']}" for a in person["accounts"]]
            notes = person.get("notes", [])
            if notes:
                item["notes"] = [{"note": n["id"], "text": n["note"] + (" (from my owner)" if n.get("by") == "owner" else ""),
                                  "when": n.get("at", "")[:10]} for n in notes[-notes_shown:]]
                if len(notes) > notes_shown:
                    item["older_notes"] = len(notes) - notes_shown
            shown.append(item)
        return shown
