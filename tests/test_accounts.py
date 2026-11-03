import json

import pytest

from soma.accounts import PLACEHOLDER, Accounts, new_password
from soma.core import Action
from soma.memory import MemoryStore


class DictVault:
    def __init__(self):
        self.values = {}
    def get(self, account_id): return self.values.get(account_id)
    def set(self, account_id, secret): self.values[account_id] = secret


@pytest.fixture
def accounts(tmp_path):
    store = MemoryStore(tmp_path)
    yield Accounts(store, DictVault())
    store.close()


def test_new_passwords_are_strong_and_typeable():
    values = {new_password() for _ in range(50)}
    assert len(values) == 50
    for value in values:
        assert len(value) == 18 and value.isascii() and " " not in value
        assert any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value)


def test_her_accounts_are_remembered_with_their_whole_history(accounts):
    proton = accounts.record("Proton Mail", "somik.mail@example.org", status="active", password_in="browser",
                             note="Password generated and saved by Firefox", by="owner")
    assert accounts.record("proton mail", "SOMIK.MAIL@EXAMPLE.ORG", status="locked") == proton  # same account
    assert accounts.find("somik.mail@example.org")["status"] == "locked"
    assert accounts.find(proton)["password_in"] == "browser"
    history = [e for e in accounts.store.events(limit=50) if e["kind"] == "account.recorded"]
    assert [e["data"].get("status") for e in history] == ["active", "locked"]   # nothing erased
    with pytest.raises(ValueError):
        accounts.store.record_account({"service": "X", "login": "y", "password": "never here"})


def test_her_owner_sees_and_sets_right_her_accounts(accounts):
    from PySide6.QtWidgets import QApplication
    from soma.app import AccountEditDialog, AccountsDialog
    app = QApplication.instance() or QApplication([])
    accounts.record("Proton Mail", "somik.mail@example.org", password_in="browser", by="owner")
    discord, secret = accounts.create_secret("Discord", "somik.mail@example.org")
    dialog = AccountsDialog(accounts)
    cells = [[dialog.table.item(r, c).text() for c in range(5)] for r in range(dialog.table.rowCount())]
    assert [row[:2] for row in cells] == [["Proton Mail", "somik.mail@example.org"],
                                          ["Discord", "somik.mail@example.org"]]
    assert cells[1][3] == "••••••••" and secret not in str(cells)
    dialog.table.selectRow(1)
    dialog.reveal()
    assert dialog.table.item(1, 3).text() == secret and dialog._hide.isActive()   # hidden again after 30 s
    dialog.refresh()
    assert dialog.table.item(1, 3).text() == "••••••••"
    # The owner reset the Proton password by hand and keeps it in her vault now.
    edit = AccountEditDialog(accounts, accounts.find("Proton Mail"))
    edit.place.setCurrentIndex(edit.place.findData("vault"))
    edit.password.setText("Owner-Set-2026!")
    edit.save()
    assert accounts.secret(accounts.find("Proton Mail")["id"]) == "Owner-Set-2026!"
    assert accounts.find("Proton Mail")["password_in"] == "vault" and accounts.find("Proton Mail")["by"] == "owner"
    dialog.close()
    app.processEvents()


def test_the_widget_stays_small_beside_her_screen(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from soma import app as app_module
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module.LifeWidget, "bootstrap", lambda self: None)
    widget = app_module.LifeWidget(tmp_path)
    try:
        widget.show()
        application.processEvents()
        compact = widget.frameGeometry()
        assert widget.teach.isVisible() and not widget.detail.isVisible() and not widget.metrics.isVisible()
        assert widget.teach.width() <= 40 and widget.avatar.width() >= 300   # her painting, not a button, fills it
        widget.update_status({"state": "OBSERVE_AND_LEARN", "intention": "Watching", "detail": "", "cycles": 1,
                              "inference": {}})
        assert widget.teach.text() == "Все, продовжуй" and widget.teach.width() > 60   # found at once while she watches
        assert not widget.teach.isEnabled()          # a second click right after starting cannot end it
        widget.update_status({"state": "AWAKE/AUTONOMOUS", "intention": "Reading", "detail": "", "cycles": 2,
                              "inference": {}, "activity": "acting"})
        assert widget.teach.width() <= 40
        widget.show_intention("Keep my hands off Miha's window while he reads")   # live, cut to "…Miha's w…"
        assert widget.intention.text() == "Keep my hands off Miha's window while he reads"
        long = "Continue reading the article about Cassiopeia below the star chart " * 6
        widget.show_intention(long)
        application.processEvents()
        shown = widget.intention.text()
        assert shown.endswith("…") and len(shown) > 120 and "Cassiopeia" in widget.intention.toolTip()
        lines = widget.intention.height() / widget.intention.fontMetrics().lineSpacing()
        assert 3 <= lines < 5 and widget.intention.width() >= 300          # across the card, at most four lines
        widget.set_expanded(True)
        assert widget.intention.text() == long                                # all of it in the details
        application.processEvents()
        assert widget.detail.isVisible() and widget.frameGeometry().height() > compact.height()
        assert widget.frameGeometry().bottomRight() == compact.bottomRight()     # anchored to its corner
        widget.set_expanded(False)
        widget.show_failure("Пам’ять збережена")
        assert widget.detail.isVisible()                                      # a failure is never folded away
    finally:
        widget._quitting = True
        widget.tray.hide()
        widget.close()
        application.processEvents()


def test_a_new_password_lives_only_in_the_vault_and_never_reaches_a_brain(accounts):
    account_id, secret = accounts.create_secret("Discord", "somik.mail@example.org")
    assert accounts.secret(account_id) == secret and accounts.find(account_id)["status"] == "signing up"
    assert accounts.find(account_id)["password_in"] == "vault"
    assert secret not in json.dumps([e["data"] for e in accounts.store.events(limit=50)])
    shown = accounts.for_context()
    assert secret not in json.dumps(shown) and shown[0]["password"].startswith("in my vault")
    assert accounts.scrub(f"memory: password {secret}!") == f"memory: password {PLACEHOLDER}!"
