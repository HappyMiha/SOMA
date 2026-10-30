from unittest.mock import Mock

import keyring

from soma.config import get_api_key
from soma.session import SleepSignals


def test_power_resume_does_not_resume_a_locked_session():
    signals = SleepSignals.__new__(SleepSignals)
    # Avoid a GUI application; these methods only route lifecycle state.
    signals.widget = Mock()
    signals.sleeping = False
    signals.locked = False
    signals.lock()
    signals.sleep(True)
    signals.sleep(False)
    signals.widget.kernel.resume.assert_not_called()
    assert signals.locked
    signals.unlock()
    signals.widget.kernel.resume.assert_called_once()


def test_keyless_endpoint_works_without_os_credential_backend(monkeypatch):
    def unavailable(*args):
        raise keyring.errors.NoKeyringError("No backend")
    monkeypatch.setattr(keyring, "get_password", unavailable)
    assert get_api_key("https://inference.example/v1") == ""
