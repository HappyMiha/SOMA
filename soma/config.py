"""Own-product configuration. Credentials live in the OS credential store."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def app_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "SOMA"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "soma"


@dataclass
class ModelConfig:
    mode: str = "remote"
    endpoint: str = ""
    model: str = ""
    local_endpoint: str = "http://127.0.0.1:1234/v1"
    local_model: str = ""
    timeout_seconds: int = 60
    requests_per_minute: int = 12
    max_output_tokens: int = 2000
    image_long_edge: int = 1600

    def validate(self):
        if self.mode not in {"remote", "local", "hybrid"}:
            raise ValueError("Unknown inference mode")
        for endpoint in ([self.endpoint] if self.mode == "remote" else
                         [self.local_endpoint] if self.mode == "local" else
                         [self.endpoint, self.local_endpoint]):
            url = urlsplit(endpoint)
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Endpoint must be a base URL without credentials or query")
            if url.scheme != "https" and not (local and url.scheme == "http"):
                raise ValueError("Remote inference requires HTTPS")
            if endpoint == self.local_endpoint and self.mode in {"local", "hybrid"} and not local:
                raise ValueError("Local inference must use a localhost endpoint")
        if self.mode in {"remote", "hybrid"} and not self.model.strip():
            raise ValueError("Remote model name is required")
        if self.mode in {"local", "hybrid"} and not self.local_model.strip():
            raise ValueError("Local model name is required")
        if not 5 <= self.timeout_seconds <= 120 or not 1 <= self.requests_per_minute <= 60:
            raise ValueError("Invalid inference budget")
        if not 256 <= self.max_output_tokens <= 4096 or not 512 <= self.image_long_edge <= 2048:
            raise ValueError("Invalid token/image budget")

    @classmethod
    def load(cls, data_dir: Path) -> "ModelConfig":
        path = data_dir / "model.json"
        return cls(**json.loads(path.read_text("utf-8"))) if path.exists() else cls()

    def save(self, data_dir: Path):
        self.validate()
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "model.json"
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)


def get_api_key(endpoint: str) -> str:
    import keyring
    try:
        return keyring.get_password("SOMA inference", endpoint.rstrip("/")) or ""
    except keyring.errors.NoKeyringError:
        # Keyless inference is valid. Writing a requested key still fails visibly.
        return ""


def set_api_key(endpoint: str, key: str):
    import keyring
    keyring.set_password("SOMA inference", endpoint.rstrip("/"), key)
