"""The world restarts its own local brain server when it lost the graphics card.

Live, after a reboot Ollama started before the eGPU was ready, found only the
processor and kept SOMIK's model there: one thought took 1-6 minutes instead of
about 10 s, until the server was started again. Ollama looks for graphics cards
only when it starts.

A reviewed exception to the no-process rule (tests/test_contract.py), like the
CLI brains: on Windows it runs only taskkill on Ollama's own two programs (and the
runners they started) and then Ollama's tray app again, with fixed arguments and
no shell. It lists, reads or touches no other process; soma.health decides when.
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def ollama_app() -> Path | None:
    """Ollama's tray app where its Windows installer puts it, if it is there."""
    if sys.platform != "win32":
        return None
    path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "Ollama" / "ollama app.exe"
    return path if path.is_file() else None


def stop_command() -> list[str]:
    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
    return [str(taskkill), "/F", "/T", "/IM", "ollama app.exe", "/IM", "ollama.exe"]


class OllamaHost:
    @property
    def available(self) -> bool:
        return ollama_app() is not None

    def restart(self, settle=3.0):
        app = ollama_app()
        if app is None:
            raise RuntimeError("Ollama's app is not where its installer puts it")
        quiet = subprocess.CREATE_NO_WINDOW
        subprocess.run(stop_command(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=quiet, timeout=30, check=False)
        time.sleep(settle)
        # Ollama outlives SOMA, as when it starts at login; SOMA's own bundle variables stay behind.
        environment = {key: value for key, value in os.environ.items() if not key.startswith(("_PYI", "_MEI"))}
        subprocess.Popen([str(app)], cwd=str(app.parent), env=environment, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
