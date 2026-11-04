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
    # "auto" probes a localhost server for the native Ollama API, which takes a
    # context size and a JSON schema; otherwise OpenAI-compatible chat is used.
    local_api: str = "auto"
    local_context_tokens: int = 8192
    coordinate_space: str = "normalized"
    # Paid remote thinking per local calendar day; 0 means unlimited. A local
    # model is never limited by it (in hybrid mode it takes over instead).
    daily_request_budget: int = 2000
    # "openai": an OpenAI-compatible HTTPS endpoint with a key in the OS vault.
    # "codex" / "claude": the owner's logged-in Codex or Claude Code CLI as a
    # tool-less brain (no key, no endpoint; empty model means the CLI default).
    remote_api: str = "openai"
    # Each brain its own job. "deep_api" names a second subscription brain
    # ("claude" / "codex", empty for none) for what needs the most judgment:
    # conversations with people, something new on the screen, reflection and
    # learning from a demonstration. With "routine_on_local" the local brain
    # (fast on a GPU) takes the routine — reading, verifying, recovering — and
    # the remote brains are only its fallback, so their quota lasts.
    deep_api: str = ""
    routine_on_local: bool = False
    # Unload the local model every N local requests to free the server's host
    # prompt cache (0 = never). A CPU model with a large KV cache needs ~4; a
    # small-KV model on a GPU loses only its cache by unloading.
    local_unload_every: int = 4
    # The hands' reflex (soma.reflex): a small decision model in the same local
    # Ollama. Empty = whichever "laya" model has been pulled there, if any.
    reflex_model: str = ""

    def validate(self):
        if self.mode not in {"remote", "local", "hybrid"}:
            raise ValueError("Unknown inference mode")
        if self.local_api not in {"auto", "openai", "ollama"}:
            raise ValueError("Unknown local inference API")
        if self.remote_api not in {"openai", "codex", "claude"}:
            raise ValueError("Unknown remote inference API")
        if self.deep_api not in {"", "codex", "claude"} or type(self.routine_on_local) is not bool:
            raise ValueError("Unknown brain for deep work")
        if self.routine_on_local and self.mode != "hybrid":
            raise ValueError("Routine on the local brain needs hybrid mode")
        if type(self.local_unload_every) is not int or not 0 <= self.local_unload_every <= 1000:
            raise ValueError("Invalid local unload interval")
        if not isinstance(self.reflex_model, str) or len(self.reflex_model) > 200:
            raise ValueError("Invalid reflex model name")
        if self.coordinate_space not in {"normalized", "per_mille"}:
            raise ValueError("Unknown coordinate space")
        if not 2048 <= self.local_context_tokens <= 32768:
            raise ValueError("Invalid local context budget")
        if type(self.daily_request_budget) is not int or not 0 <= self.daily_request_budget <= 1_000_000:
            raise ValueError("Invalid daily request budget")
        http_remote = self.mode in {"remote", "hybrid"} and self.remote_api == "openai"
        for endpoint in ([self.endpoint] if http_remote else []) + (
                [self.local_endpoint] if self.mode in {"local", "hybrid"} else []):
            url = urlsplit(endpoint)
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Endpoint must be a base URL without credentials or query")
            if url.scheme != "https" and not (local and url.scheme == "http"):
                raise ValueError("Remote inference requires HTTPS")
            if endpoint == self.local_endpoint and self.mode in {"local", "hybrid"} and not local:
                raise ValueError("Local inference must use a localhost endpoint")
        if http_remote and not self.model.strip():
            raise ValueError("Remote model name is required")
        if self.mode in {"local", "hybrid"} and not self.local_model.strip():
            raise ValueError("Local model name is required")
        # A CPU-only local VLM needs minutes per screenshot; an HTTP remote stays
        # bounded; an agent CLI starts a process and reasons before answering.
        longest = 120 if self.mode == "remote" and self.remote_api == "openai" else 900
        if not 5 <= self.timeout_seconds <= longest or not 1 <= self.requests_per_minute <= 60:
            raise ValueError("Invalid inference budget")
        if not 256 <= self.max_output_tokens <= 4096 or not 512 <= self.image_long_edge <= 2048:
            raise ValueError("Invalid token/image budget")

    @classmethod
    def load(cls, data_dir: Path) -> "ModelConfig":
        path = data_dir / "model.json"
        if not path.exists():
            return cls()
        known = set(cls.__dataclass_fields__)
        # Settings written by a newer version must not prevent waking up.
        return cls(**{k: v for k, v in json.loads(path.read_text("utf-8")).items() if k in known})

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


VISION_MARKERS = ("-vl", "vl:", "vision", "llava", "ui-tars", "minicpm-v")


def detect_local_brain(transport=None) -> "ModelConfig | None":
    """First run without a wizard: use a vision model already pulled into a local Ollama."""
    import httpx
    try:
        with httpx.Client(timeout=3, transport=transport, trust_env=False) as client:
            names = [m["name"] for m in client.get("http://127.0.0.1:11434/api/tags").json()["models"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    vision = sorted(n for n in names if any(marker in n.lower() for marker in VISION_MARKERS))
    if not vision:
        return None
    return ModelConfig(mode="local", local_endpoint="http://127.0.0.1:11434/v1", local_model=vision[0],
                       timeout_seconds=600, requests_per_minute=6, max_output_tokens=1024,
                       image_long_edge=768, coordinate_space=grounding_space(vision[0]))


def grounding_space(model: str) -> str:
    """Qwen-VL and UI-TARS families are trained to point on a 0..1000 grid."""
    name = model.lower()
    return "per_mille" if "qwen" in name or "ui-tars" in name or "uitars" in name else "normalized"


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
