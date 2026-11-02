"""Subscription CLIs (Codex, Claude Code) as tool-less brains, via the owner's own logins.

This is the only production module allowed to start a process, and it starts
only these inference CLIs. Both are agents, so every tool is disabled, they run
in an empty temporary directory without the user's settings, rules, MCP
servers or persisted sessions, and any tool activity in their event stream
rejects the answer: the brain proposes, only HumanInterfacePort acts. Screens
go in as images; the answer comes back as one schema-shaped JSON object.
SOMA never reads or copies the CLIs' credentials; each CLI uses its own login.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


class BrainUnavailable(RuntimeError):
    pass


def strict_schema(schema):
    """OpenAI strict structured outputs: every property required, optional ones nullable."""
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    converted = {key: strict_schema(value) for key, value in schema.items()}
    if converted.get("type") == "object" and "properties" in converted:
        required = set(schema.get("required", []))
        converted["properties"] = {name: (value if name in required else {"anyOf": [value, {"type": "null"}]})
                                   for name, value in converted["properties"].items()}
        converted["required"] = list(converted["properties"])
        converted["additionalProperties"] = False
    return converted


CONSTRAINT_KEYWORDS = {"minimum", "maximum", "minItems", "maxItems"}


def relaxed_schema(schema):
    """Structure only: SOMA validates ranges itself after parsing every answer."""
    if isinstance(schema, list):
        return [relaxed_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {key: relaxed_schema(value) for key, value in schema.items() if key not in CONSTRAINT_KEYWORDS}


def _newest(paths) -> Path | None:
    found = sorted((p for p in paths if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _run(argv, stdin_text, workdir, deadline, cancel, env=None) -> tuple[int, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               cwd=workdir, env=env, creationflags=flags, text=True, encoding="utf-8")
    try:
        pending = stdin_text
        while True:
            try:
                stdout, _ = process.communicate(pending, timeout=0.5)
                return process.returncode, stdout
            except subprocess.TimeoutExpired:
                pending = None
                if cancel.is_set():
                    raise InterruptedError("Inference cancelled")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Brain deadline exceeded")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


# ---------------------------------------------------------------- Codex (ChatGPT login)

CODEX_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "shell_snapshot", "computer_use", "browser_use",
    "browser_use_external", "browser_use_full_cdp_access", "in_app_browser", "apps", "plugins", "hooks",
    "view_image", "image_generation", "sleep_tool", "tool_suggest", "skill_search",
    "skill_mcp_dependency_install", "code_mode_host",
)
# Event items a thinking-only Codex turn may contain. Anything else (commands,
# file changes, MCP/web/browser/computer calls) means it tried to act itself.
CODEX_THINKING_ITEMS = {"agent_message", "reasoning", "error"}


def find_codex() -> Path | None:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OpenAI/Codex/bin"
        found = _newest(root.glob("*/codex.exe"))
        if found:
            return found
    located = shutil.which("codex")
    return Path(located) if located else None


def codex_command(executable, workdir: Path, schema_path: Path, output_path: Path, images, model="") -> list[str]:
    argv = [str(executable), "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--sandbox", "read-only", "-C", str(workdir), "--json",
            "--output-schema", str(schema_path), "-o", str(output_path), "-c", 'web_search="disabled"']
    for feature in CODEX_DISABLED_FEATURES:
        argv += ["--disable", feature]
    if model:
        argv += ["--model", model]
    for image in images:
        argv += ["--image", str(image)]
    return argv + ["-"]  # The prompt arrives on stdin, never on the command line.


class BrainExhausted(BrainUnavailable):
    """The subscription's usage limit is reached; asking again soon is pointless."""


def codex_events(stdout: str) -> dict:
    usage = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # Plain log lines.
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict) and item.get("type") not in CODEX_THINKING_ITEMS:
            raise PermissionError("Codex brain attempted to act through a tool")
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
            message = str(event.get("message") or (event.get("error") or {}).get("message") or "")
            if "usage limit" in message.lower() or "rate limit" in message.lower():
                raise BrainExhausted("Codex usage limit reached")
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
    return {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)}


class CodexBrain:
    name = "Codex"

    def __init__(self, executable=None, model=""):
        self.executable = executable or find_codex()
        self.model = model

    def think(self, system, prompt, images, schema, deadline, cancel) -> tuple[dict, dict]:
        if not self.executable or not Path(self.executable).is_file():
            raise BrainUnavailable("Codex CLI is not installed")
        with tempfile.TemporaryDirectory(prefix="soma-brain-") as temporary:
            root = Path(temporary)
            workdir = root / "empty"
            workdir.mkdir()
            schema_path, output_path = root / "schema.json", root / "answer.json"
            schema_path.write_text(json.dumps(strict_schema(schema)), "utf-8")
            paths = []
            for index, image in enumerate(images):
                paths.append(root / f"screen-{index}.jpg")
                paths[-1].write_bytes(image)
            code, stdout = _run(codex_command(self.executable, workdir, schema_path, output_path, paths, self.model),
                                system + "\n\n" + prompt, workdir, deadline, cancel)
            usage = codex_events(stdout)
            if code != 0 or not output_path.is_file():
                raise BrainUnavailable(f"Codex exited with code {code}")
            return json.loads(output_path.read_text("utf-8")), usage


# ---------------------------------------------------------------- Claude Code (Claude login)

# Variables of a parent Claude Code session must not leak into the brain.
CLAUDE_HOST_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_ENTRYPOINT")


def find_claude() -> Path | None:
    candidates = []
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        candidates += list(local.glob("Claude-Data/*/claude-code/*/*/claude.exe"))
        candidates.append(Path.home() / ".local/bin/claude.exe")
    else:
        candidates.append(Path.home() / ".local/bin/claude")
    found = _newest(candidates)
    if found:
        return found
    located = shutil.which("claude")
    return Path(located) if located else None


def claude_command(executable, system: str, schema: dict, model="") -> list[str]:
    argv = [str(executable), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--tools", "", "--strict-mcp-config", "--setting-sources", "project",
            "--no-session-persistence", "--disable-slash-commands",
            "--system-prompt", system, "--json-schema", json.dumps(relaxed_schema(schema))]
    if model:
        argv += ["--model", model]
    return argv


def claude_message(prompt: str, images) -> str:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(image).decode("ascii")}} for image in images]
    content.append({"type": "text", "text": prompt})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def claude_events(stdout: str) -> tuple[dict, dict]:
    result = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                # --json-schema answers arrive through the CLI's own StructuredOutput
                # carrier (verified live, 2.1.309); every other tool use is refused.
                if (isinstance(block, dict) and block.get("type") not in {"text", "thinking", "redacted_thinking"}
                        and not (block.get("type") == "tool_use" and block.get("name") == "StructuredOutput")):
                    raise PermissionError("Claude brain attempted to act through a tool")
        if event.get("type") == "result":
            result = event
    if result is None:
        raise BrainUnavailable("Claude CLI returned no result")
    if result.get("permission_denials"):
        raise PermissionError("Claude brain attempted to act through a tool")
    if result.get("is_error"):
        message = str(result.get("result") or "").lower()
        if "limit" in message and ("usage" in message or "rate" in message or "reached" in message):
            raise BrainExhausted("Claude usage limit reached")
        raise BrainUnavailable("Claude CLI is not logged in" if "logged in" in message
                               else "Claude CLI reported an error")
    value = result.get("structured_output")
    if value is None:
        value = json.loads(result.get("result") or "")
    usage = result.get("usage") or {}
    return value, {"input_tokens": usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
                   "output_tokens": usage.get("output_tokens", 0)}


class ClaudeBrain:
    name = "Claude"

    def __init__(self, executable=None, model=""):
        self.executable = executable or find_claude()
        self.model = model

    def think(self, system, prompt, images, schema, deadline, cancel) -> tuple[dict, dict]:
        if not self.executable or not Path(self.executable).is_file():
            raise BrainUnavailable("Claude Code CLI is not installed")
        env = {key: value for key, value in os.environ.items() if key not in CLAUDE_HOST_VARIABLES}
        with tempfile.TemporaryDirectory(prefix="soma-brain-") as workdir:
            code, stdout = _run(claude_command(self.executable, system, schema, self.model),
                                claude_message(prompt, images), workdir, deadline, cancel, env)
        value, usage = claude_events(stdout)
        if code != 0:
            raise BrainUnavailable(f"Claude exited with code {code}")
        return value, usage


BRAINS = {"codex": CodexBrain, "claude": ClaudeBrain}
