"""Source-level guard, supplemented by manual boundary review; not a sandbox."""

import ast
from dataclasses import fields
from pathlib import Path

from soma.core import ScreenFrame


def test_frame_has_pixels_geometry_and_technical_identity_only():
    assert {f.name for f in fields(ScreenFrame)} == {
        "png", "width", "height", "x", "y", "monitors", "timestamp", "frame_id", "captured_monotonic"}


def test_production_has_no_bypass_imports_or_code_dispatch():
    forbidden = {"subprocess", "playwright", "selenium", "pyautogui", "pywinauto", "uiautomation",
                 "win32gui", "psutil", "requests", "telegram", "imaplib", "smtplib", "webbrowser"}
    # Every production module, including any subpackage.
    for path in (Path(__file__).parents[1] / "soma").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        # The reviewed exceptions: the inference adapters that start the
        # subscription CLIs as tool-less brains (see test_cli_brains_cannot_act)
        # and the local image engine that paints her selfies (see
        # test_image_engine_only_paints).
        allowed = {"subprocess"} if path.name in {"cli_brains.py", "imaging.py"} else set()
        forbidden_here = forbidden - allowed
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & forbidden_here, path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_here, path
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile", "__import__"}, path
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"system", "popen", "GetWindowText", "FindWindow",
                        "get_active_window", "GetForegroundWindow", "paste", "copy_to_clipboard"}, path


def test_codex_brain_cannot_act():
    """The Codex adapter starts only Codex, as a brain with every tool disabled."""
    import json
    import pytest
    from soma.cli_brains import (CODEX_DISABLED_FEATURES as DISABLED_FEATURES, codex_command as command,
                                  codex_events as check_events, strict_schema)
    argv = command(Path("codex.exe"), Path("empty"), Path("s.json"), Path("a.json"), [Path("screen-0.jpg")])
    assert argv[:2] == ["codex.exe", "exec"] and argv[-1] == "-"
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--json", "--output-schema"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("-C") + 1] == "empty"
    disabled = {argv[i + 1] for i, value in enumerate(argv) if value == "--disable"}
    assert disabled == set(DISABLED_FEATURES)
    for tool in ("shell_tool", "unified_exec", "computer_use", "browser_use", "apps", "plugins",
                 "view_image", "code_mode_host", "hooks"):
        assert tool in disabled
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    # A tool item anywhere in the event stream rejects the whole answer.
    thinking = [{"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
                {"type": "turn.completed", "usage": {"input_tokens": 5}}]
    assert check_events("\n".join(map(json.dumps, thinking))) == {"input_tokens": 5, "output_tokens": 0}
    for item in ("command_execution", "file_change", "mcp_tool_call", "web_search", "computer_use"):
        with pytest.raises(PermissionError):
            check_events(json.dumps({"type": "item.started", "item": {"type": item}}))
    # Strict structured outputs: every property present, optional ones nullable.
    converted = strict_schema({"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                               "required": ["a"]})
    assert converted["required"] == ["a", "b"] and converted["additionalProperties"] is False
    assert converted["properties"]["b"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_image_engine_only_paints(tmp_path):
    """The selfie engine gets her prompt as one argument and writes one image; no shell, no files of others."""
    from soma.imaging import Imaging
    (tmp_path / "engine").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "engine" / "sd-cli.exe").write_bytes(b"")
    (tmp_path / "models" / "sdxl_lightning_4step.safetensors").write_bytes(b"")
    imaging = Imaging(tmp_path)
    prompt = "--output C:/Windows/evil.png; rm -rf / && echo"
    argv = imaging.command(prompt, tmp_path / "out.png", 7)
    value = argv[argv.index("-p") + 1]                    # one value, never parsed as flags
    assert value.startswith("pixel art") and value.endswith(prompt) and sum(prompt in a for a in argv) == 1
    assert argv[argv.index("-o") + 1] == str(tmp_path / "out.png")
    assert not any(token in {"cmd", "cmd.exe", "powershell", "/c", "-c"} for token in argv)
    import inspect
    import soma.imaging as module
    source = inspect.getsource(module)
    assert "shell=True" not in source and source.count("subprocess.Popen(") == 1


def test_claude_brain_cannot_act():
    """Claude Code CLI as a brain: no tools, no MCP, no user settings, no saved session."""
    import json
    import pytest
    from soma.cli_brains import BrainUnavailable, claude_command, claude_events, claude_message
    argv = claude_command(Path("claude.exe"), "You are SOMA.", {"type": "object", "properties": {
        "x": {"type": "integer", "minimum": 0, "maximum": 1000}}, "required": ["x"]})
    assert argv[:2] == ["claude.exe", "-p"]
    assert argv[argv.index("--tools") + 1] == ""
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert argv[argv.index("--system-prompt") + 1] == "You are SOMA."
    assert "minimum" not in argv[argv.index("--json-schema") + 1]
    assert not any("dangerously" in value or "bypass" in value for value in argv)
    message = json.loads(claude_message("Look", [b"jpeg"]))
    assert [c["type"] for c in message["message"]["content"]] == ["image", "text"]
    ok = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "{}"}]}},
          {"type": "result", "is_error": False, "structured_output": {"x": 5}, "permission_denials": [],
           "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7}}]
    assert claude_events("\n".join(map(json.dumps, ok))) == ({"x": 5}, {"input_tokens": 100, "output_tokens": 7})
    acting = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}] + ok[1:]
    with pytest.raises(PermissionError):
        claude_events("\n".join(map(json.dumps, acting)))
    # The CLI carries a --json-schema answer through its own StructuredOutput
    # block (observed live); that is an answer, not an action.
    structured = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "StructuredOutput"}]}}] + ok[1:]
    assert claude_events("\n".join(map(json.dumps, structured)))[0] == {"x": 5}
    denied = [{**ok[1], "permission_denials": [{"tool_name": "Read"}]}]
    with pytest.raises(PermissionError):
        claude_events(json.dumps(denied[0]))
    logged_out = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    with pytest.raises(BrainUnavailable, match="not logged in"):
        claude_events(json.dumps(logged_out))
