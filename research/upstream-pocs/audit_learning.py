"""Offline upstream probes. Never starts recording, input injection, or inference.

Run from the SOMA root: python research/upstream-pocs/audit_learning.py
Only imports audited, side-effect-free upstream files by absolute file path.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / ".upstream"


def module_from_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def geometry_probe(path: Path, name: str) -> dict:
    module = module_from_file(name, path)
    scope = module.DesktopCaptureScope.from_monitors([
        {"left": -1920, "top": 0, "width": 4480, "height": 1440},
        {"left": -1920, "top": 0, "width": 1920, "height": 1080},
        {"left": 0, "top": 0, "width": 2560, "height": 1440},
    ])
    assert scope.translate(-1920, 0) == (0, 0)
    assert scope.translate(2559, 1439) == (4479, 1439)
    try:
        module.DesktopCaptureScope.from_monitors([
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": True, "top": 0, "width": 1920, "height": 1080},
        ])
    except module.DesktopCaptureError:
        malformed_rejected = True
    else:
        raise AssertionError("Boolean geometry accepted")
    return {"status": "PASS", "kind": "offline geometry", "snapshot": scope.snapshot(),
            "negative_origin_translation": True, "malformed_rejected": malformed_rejected}


def aloha_probe() -> dict:
    module = module_from_file("aloha_log_processor_audit",
        UPSTREAM / "ShowUI-Aloha/Aloha_Learn/log_processor.py")
    fixture = UPSTREAM / "ShowUI-Aloha/Aloha_Learn/Examples/air_tickets/input_log_20250912_085417.txt"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        raw = module.LogProcessor().process_input_log(str(fixture))
        processed = module.LogProcessor().process_log_file(str(fixture))
    assert len(processed) > 0
    assert all(isinstance(event["timestamp"], (int, float)) for event in processed)
    # Synthetic fixture checks whether the parser handles a left-hand monitor.
    with tempfile.TemporaryDirectory(prefix="soma-aloha-audit-") as directory:
        path = Path(directory) / "negative-origin.jsonl"
        path.write_text(json.dumps({"timestamp": "00:00:01.000",
            "message": "LClick at (-100, 50)", "window": None}) + "\n", encoding="utf-8")
        negative = module.LogProcessor().process_input_log(str(path))[0]
    return {"status": "PASS", "kind": "offline public demonstration log parsing",
            "raw_events": len(raw), "processed_actions": len(processed),
            "nonpixel_window_metadata_retained": any(event.get("current_software") for event in processed),
            "negative_coordinate_extracted": bool(negative["coords"]),
            "pipeline_stdout": output.getvalue().splitlines(),
            "inference": "NOT RUN", "live_recording": "NOT RUN"}


def openadapt_probe() -> dict:
    module = module_from_file("openadapt_desktop_recorder_audit",
        UPSTREAM / "OpenAdapt/packages/flow/openadapt_flow/adapters/desktop_recorder.py")
    workflow = SimpleNamespace(steps=[
        SimpleNamespace(action="click", anchor=SimpleNamespace(structural=None)),
        SimpleNamespace(action="click", anchor=SimpleNamespace(structural={"role": "button"})),
        SimpleNamespace(action="type", anchor=None),
    ])
    coverage = module.structural_armed_coverage(workflow)
    assert coverage == {"click_steps": 2, "armed_clicks": 1, "armed_coverage": 0.5}
    return {"status": "PASS", "kind": "offline structural route detection",
            "coverage": coverage,
            "capture_geometry": geometry_probe(UPSTREAM / "OpenAdapt/packages/capture/openadapt_capture/desktop_capture.py",
                "openadapt_monorepo_geometry_audit"), "live_capture_or_replay": "NOT RUN"}


def showui_probe() -> dict:
    from PIL import Image

    # Execute only the existing pure postprocessor, with no Gradio client startup.
    tree = ast.parse((UPSTREAM / "ShowUI/api.py").read_text(encoding="utf-8"))
    provider = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ShowUIProvider")
    method = next(node for node in provider.body if isinstance(node, ast.FunctionDef) and node.name == "extract_norm_point")
    isolated = ast.Module(body=[method], type_ignores=[])
    namespace = {"ast": ast, "Image": Image}
    exec(compile(isolated, "upstream:ShowUI/api.py::extract_norm_point", "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="soma-showui-audit-") as directory:
        image = Path(directory) / "synthetic-screen.png"
        Image.new("RGB", (1920, 1080)).save(image)
        point = namespace["extract_norm_point"](None, "[0.5, 0.25]", str(image))
        assert point == (960.0, 270.0)
        out_of_range = namespace["extract_norm_point"](None, "[1.5, -0.25]", str(image))
    assert out_of_range == (2880.0, -270.0)
    return {"status": "PASS", "kind": "isolated upstream output postprocessor",
            "point": point, "out_of_range_not_rejected": out_of_range,
            "requires_added_validation": True, "model_inference": "NOT RUN"}


def main() -> None:
    pins = {}
    for name in ["ShowUI-Aloha", "OpenAdapt", "openadapt-capture", "ShowUI"]:
        repository = UPSTREAM / name
        pins[name] = {"sha": subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(),
                      "license_sha256": hashlib.sha256((repository / "LICENSE").read_bytes()).hexdigest()}
    result = {"host": platform.platform(), "python": sys.version, "pins": pins,
              "ShowUI-Aloha": aloha_probe(), "OpenAdapt": openadapt_probe(),
              "openadapt-capture": geometry_probe(UPSTREAM / "openadapt-capture/openadapt_capture/desktop_capture.py",
                  "openadapt_capture_geometry_audit"), "ShowUI": showui_probe(),
              "limitations": ["No live recording or input injection", "No model weights downloaded",
                  "No inference calls", "No Windows, X11, or Wayland GUI acceptance gate executed"]}
    evidence = ROOT / "docs/upstream/learning-evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
