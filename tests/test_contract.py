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
    for path in (Path(__file__).parents[1] / "soma").glob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & forbidden, path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden, path
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile", "__import__"}, path
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"system", "popen", "GetWindowText", "FindWindow",
                        "get_active_window", "GetForegroundWindow", "paste", "copy_to_clipboard"}, path
