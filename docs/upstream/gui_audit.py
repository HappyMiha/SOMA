"""Reproduce the GUI upstream audit without installing or controlling a desktop.

Run from the SOMA root: python docs/upstream/gui_audit.py
This reads pinned clones, parses source, and executes three isolated pure/mock
probes. It never imports an upstream package or executes generated action code.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / ".upstream" / "gui-audit"
PINS = {
    "self-operating-computer": "eb8165a2efb1b34d66a28ecebf8ca97ae67cbb79",
    "Agent-S": "0fff0e634869dab72027435b4586e62300185d41",
    "UI-TARS-desktop": "3ac2cb8d946d78d5ff92ad17b318eaafa18c178c",
    "computer_use_ootb": "21b05ae06de89700b998dc85d8ef64454f0d0291",
}
SOURCES = {
    "self-operating-computer": {
        "operate/utils/operating_system.py": ["pyautogui.write", "pyautogui.keyDown", "pyautogui.click"],
        "operate/utils/screenshot.py": ["pyautogui.screenshot", "Xlib.display.Display", "ImageGrab.grab"],
        "operate/operate.py": ["loop_count > 10", "time.sleep(1)"],
    },
    "Agent-S": {
        "gui_agents/s3/agents/grounding.py": ["wmctrl", "import uno", "pyperclip.copy", "self.code_agent.execute"],
        "gui_agents/s3/cli_app.py": ["pyautogui.screenshot", "exec(code[0])"],
        "gui_agents/s3/utils/common_utils.py": ["eval(code)"],
        "gui_agents/s3/utils/local_env.py": ["subprocess.run"],
        "agent_s4/README.md": ["shadow interface", "AWS"],
    },
    "UI-TARS-desktop": {
        "packages/ui-tars/operators/nut-js/src/index.ts": ["screen.grab", "clipboard.setContent", "mouse.drag"],
        "apps/ui-tars/src/main/agent/operator.ts": ["types: ['screen']", "clipboard.readText", "clipboard.writeText"],
        "multimodal/gui-agent/operator-nutjs/src/NutJSOperator.ts": ["screen.grab", "clipboard.setContent"],
        "apps/ui-tars/electron-builder.yml": ["AppImage", "deb"],
    },
    "computer_use_ootb": {
        "computer_use_demo/tools/screen_capture.py": ["ImageGrab.grab(bbox=bbox)", "xrandr"],
        "computer_use_demo/tools/computer.py": ["pyautogui.typewrite", "async def shell", "def scale_coordinates"],
        "computer_use_demo/executor/anthropic_executor.py": ["BashTool()", "EditTool()"],
        "computer_use_demo/executor/showui_executor.py": ["ComputerTool(selected_screen=selected_screen, is_scaling=False)"],
    },
}


def source(repo: str, relative: str) -> str:
    return (UPSTREAM / repo / relative).read_text(encoding="utf-8-sig")


def method(repo: str, relative: str, cls_name: str, name: str):
    tree = ast.parse(source(repo, relative))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    return node


def compile_method(node, namespace):
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(tree)
    exec(compile(tree, "<isolated upstream method>", "exec"), namespace)
    return namespace[node.name]


def probes():
    events = []
    fake_input = SimpleNamespace(**{
        name: (lambda *args, _name=name: events.append([_name, list(args)]))
        for name in ("write", "keyDown", "keyUp")
    })
    path = "operate/utils/operating_system.py"
    namespace = {"pyautogui": fake_input, "time": SimpleNamespace(sleep=lambda _: None)}
    write = compile_method(method("self-operating-computer", path, "OperatingSystem", "write"), namespace)
    press = compile_method(method("self-operating-computer", path, "OperatingSystem", "press"), namespace)
    write(None, "ab")
    press(None, ["ctrl", "a"])
    assert events == [["write", ["a"]], ["write", ["b"]], ["keyDown", ["ctrl"]], ["keyDown", ["a"]], ["keyUp", ["ctrl"]], ["keyUp", ["a"]]]

    path = "gui_agents/s3/agents/grounding.py"
    type_action = compile_method(method("Agent-S", path, "OSWorldACI", "type"), {})
    generated = type_action(SimpleNamespace(platform="windows"), text="Привіт")
    assert "pyperclip.copy('Привіт')" in generated and "subprocess.run" in generated

    path = "computer_use_demo/tools/computer.py"
    scale = compile_method(method("computer_use_ootb", path, "ComputerTool", "scale_coordinates"), {
        "ScalingSource": SimpleNamespace(API="api"), "ToolError": ValueError,
        "MAX_SCALING_TARGETS": {"XGA": {"width": 1024, "height": 768}, "WXGA": {"width": 1280, "height": 800}, "FWXGA": {"width": 1366, "height": 768}},
    })
    display = SimpleNamespace(width=1920, height=1080, _scaling_enabled=True)
    midpoint = scale(display, "api", 683, 384)
    escaped = scale(display, "api", 1500, 300)
    assert midpoint == (960, 540) and escaped[0] > display.width

    ts = source("UI-TARS-desktop", "multimodal/gui-agent/operator-nutjs/src/NutJSOperator.ts")
    actions_match = re.search(r"supportedActions\(\)[^{]+\{\s*return\s*\[([\s\S]*?)\]", ts)
    assert actions_match is not None
    actions = re.findall(r"'([^']+)'", actions_match.group(1))
    assert all(action in actions for action in ["click", "drag", "type", "hotkey"])
    assert "clipboard.setContent(stripContent)" in ts and "screen.grab()" in ts

    return {
        "self-operating-computer": {"level": "isolated mocked Python method execution", "passed": True, "events": events},
        "Agent-S": {"level": "isolated Python code generation; returned code was NEVER executed", "passed": True, "unicode_requires_clipboard": True, "generated_installer_route": True},
        "UI-TARS-desktop": {"level": "static TypeScript structural probe only; no JS runtime or desktop run", "passed": True, "actions": actions, "windows_clipboard_route_present": True},
        "computer_use_ootb": {"level": "isolated pure Python coordinate method execution", "passed": True, "midpoint": midpoint, "out_of_target_range_maps_outside_screen": escaped},
    }


def main():
    results = {"scope": "source audit + isolated probes, NOT installed end-to-end or live GUI evidence", "host": "Windows", "repositories": {}, "probes": probes()}
    for repo, pin in PINS.items():
        directory = UPSTREAM / repo
        sha = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
        assert sha == pin, f"{repo}: expected {pin}, found {sha}"
        tracked = subprocess.check_output(["git", "-C", str(directory), "ls-files"], text=True).splitlines()
        licenses = [p for p in tracked if Path(p).name.upper().startswith("LICENSE")]
        notices = [p for p in tracked if Path(p).name.upper().startswith("NOTICE")]
        evidence = []
        parsed = []
        for relative, markers in SOURCES[repo].items():
            contents = source(repo, relative)
            if relative.endswith(".py"):
                ast.parse(contents)
                parsed.append(relative)
            for marker in markers:
                matches = [i for i, line in enumerate(contents.splitlines(), 1) if marker in line]
                assert matches, f"missing audit marker {repo}/{relative}: {marker}"
                evidence.append({"file": relative, "marker": marker, "lines": matches})
        results["repositories"][repo] = {
            "sha": sha, "clone_command": f"git clone --depth 1 --filter=blob:none https://github.com/{'OthersideAI' if repo == 'self-operating-computer' else 'simular-ai' if repo == 'Agent-S' else 'bytedance' if repo == 'UI-TARS-desktop' else 'showlab'}/{repo}.git .upstream/gui-audit/{repo}",
            "clone_observation": "first clone succeeded, exit 0, on 2026-10-30; no retry/failure observed",
            "licenses": [{"path": p, "sha256": hashlib.sha256((directory / p).read_bytes()).hexdigest()} for p in licenses],
            "notice_files": notices, "python_modules_parsed": parsed, "evidence": evidence,
        }
    output = ROOT / "docs" / "upstream" / "gui_audit_results.json"
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PASS: four pinned repositories; three isolated Python probes and one static TypeScript probe. Evidence: {output}")


if __name__ == "__main__":
    main()
