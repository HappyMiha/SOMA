"""Her own accounts: a registry she always knows, passwords only her hand and her owner see.

The registry (service, login, status, where the password is) is part of her
memory and of every context she thinks with. Passwords are kept in the OS
credential vault (Windows Credential Manager, Secret Service on Linux): the
brain never sees, invents or repeats one. Her hand types a password by naming
the account, a new account's password is made strong here, and every known
password is replaced by a placeholder in anything sent to any brain.
"""

from __future__ import annotations

import secrets
import string
import threading

VAULT_SERVICE = "SOMA accounts"
STATUSES = ("signing up", "active", "needs verification", "locked", "abandoned")
PASSWORD_PLACES = {"vault": "in my vault (my hand types it)",
                   "browser": "saved in the browser (use its autofill)",
                   "unknown": "unknown — ask my owner"}
PLACEHOLDER = "‹password›"
SYMBOLS = "-_.!"


def new_password(length: int = 18) -> str:
    """Strong, typeable everywhere: letters, digits and a few widely accepted symbols."""
    alphabet = string.ascii_letters + string.digits + SYMBOLS
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in value) and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value) and any(c in SYMBOLS for c in value)):
            return value


class KeyringVault:
    """Passwords in the OS credential store under "SOMA accounts": each inhabitant's
    as "<inhabitant id>/<account id>". SOMIK's passwords from before SOMA had homes
    ("a1", "a2" …) are still read where they were kept; nothing is moved or erased."""

    def __init__(self, inhabitant: str | None = None, shared: bool = False):
        self.inhabitant, self.shared = inhabitant, shared

    def _user(self, account_id: str) -> str:
        return f"{self.inhabitant}/{account_id}" if self.inhabitant else account_id

    def get(self, account_id: str) -> str | None:
        import keyring
        try:
            value = keyring.get_password(VAULT_SERVICE, self._user(account_id))
            if value is None and self.inhabitant and self.shared:
                value = keyring.get_password(VAULT_SERVICE, account_id)
            return value
        except keyring.errors.NoKeyringError:
            return None

    def set(self, account_id: str, secret: str):
        import keyring
        keyring.set_password(VAULT_SERVICE, self._user(account_id), secret)


class Accounts:
    def __init__(self, store, vault=None):
        self.store = store
        self.vault = vault or KeyringVault()
        self._lock = threading.Lock()
        self._known = None  # Cached secrets for scrubbing; refreshed on every change.

    def list(self) -> list[dict]:
        return self.store.accounts()

    def find(self, reference: str) -> dict | None:
        """An account by its id (a1), its login, or its service name when that is unique."""
        reference = (reference or "").strip().lower()
        accounts = self.list()
        for key in ("id", "login"):
            for account in accounts:
                if str(account.get(key, "")).lower() == reference:
                    return account
        by_service = [a for a in accounts if str(a.get("service", "")).lower() == reference
                      and a.get("status") != "abandoned"]
        return by_service[0] if len(by_service) == 1 else None

    def record(self, service=None, login=None, *, status=None, note=None, password_in=None,
               account_id=None, by="soma") -> str:
        if status is not None and status not in STATUSES:
            raise ValueError("Unknown account status")
        if password_in is not None and password_in not in PASSWORD_PLACES:
            raise ValueError("Unknown password place")
        if account_id is None and service and login:
            existing = self._same(service, login)
            account_id = existing["id"] if existing else None
        if account_id is None:  # A new account: say plainly what is known.
            status, password_in = status or "active", password_in or "unknown"
        return self.store.record_account({"id": account_id, "service": service, "login": login, "status": status,
                                          "note": note, "password_in": password_in, "by": by})

    def _same(self, service: str, login: str) -> dict | None:
        return next((a for a in self.list() if a.get("service", "").lower() == service.lower()
                     and a.get("login", "").lower() == login.lower()), None)

    def secret(self, account_id: str) -> str | None:
        return self.vault.get(account_id)

    def set_secret(self, account_id: str, secret: str, by="soma"):
        if not secret:
            raise ValueError("Empty password")
        with self._lock:
            self.vault.set(account_id, secret)
            self._known = None
        self.store.record_account({"id": account_id, "password_in": "vault", "by": by})

    def create_secret(self, service: str, login: str) -> tuple[str, str]:
        """A strong password for an account she is signing up for (or renewing),
        kept in the vault before her hand types it."""
        existing = self._same(service, login)
        account_id = existing["id"] if existing else self.record(service, login, status="signing up")
        secret = new_password()
        self.set_secret(account_id, secret)
        return account_id, secret

    def known_secrets(self) -> list[str]:
        with self._lock:
            if self._known is None:
                found = []
                for account in self.list():
                    if account.get("password_in") == "vault":
                        try:
                            value = self.vault.get(account["id"])
                        except Exception:
                            value = None
                        if value and len(value) >= 6:
                            found.append(value)
                self._known = sorted(found, key=len, reverse=True)
            return list(self._known)

    def scrub(self, text: str) -> str:
        """Every known password replaced by a placeholder: for anything a brain is sent."""
        for value in self.known_secrets():
            if value in text:
                text = text.replace(value, PLACEHOLDER)
        return text

    def for_context(self) -> list[dict]:
        """What she knows about her accounts, without any password."""
        shown = []
        for account in self.list():
            item = {"account": account["id"], "service": account.get("service"), "login": account.get("login"),
                    "status": account.get("status", "active"),
                    "password": PASSWORD_PLACES.get(account.get("password_in", "unknown"))}
            if account.get("note"):
                item["note"] = account["note"]
            shown.append(item)
        return sorted(shown, key=lambda item: item["status"] == "abandoned")
