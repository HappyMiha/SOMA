"""Opt-in synthetic input evidence on an isolated Xvfb X11 server only.

This does not operate the physical Linux/Windows desktop or WSLg. A private
Xvfb invocation is required; all pixels and input belong to this owned fixture.
"""

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-x11", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/linux-x11")
    args = parser.parse_args()
    if not args.run_isolated_x11:
        print("SKIP: pass --run-isolated-x11 under a dedicated xvfb-run server")
        return 0
    if not sys.platform.startswith("linux") or not os.environ.get("XVFB_EVIDENCE_SESSION"):
        parser.error("Set XVFB_EVIDENCE_SESSION=1 only inside the dedicated xvfb-run invocation")
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") != "x11":
        parser.error("This probe requires isolated X11 with WAYLAND_DISPLAY unset")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from soma.body import HumanInterfacePort, InputInhibited
    from soma.core import Action, utc_now
    from soma.demonstration import DemonstrationRecorder
    from soma.memory import MemoryStore

    specification = importlib.util.spec_from_file_location("owned_fixture", ROOT / "tests/desktop_e2e.py")
    fixture = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(fixture)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"started_at": utc_now(), "passed": False,
        "scope": "Synthetic native input/capture on a dedicated virtual Xvfb X11 display in WSL Ubuntu",
        "display": os.environ["DISPLAY"], "checks": {},
        "limitations": ["Not a physical Linux monitor, Wayland or WSLg test", "No model inference or external application workflow"]}
    app = QApplication(sys.argv[:1])
    window = QWidget()
    window.setWindowTitle("SOMA isolated X11 owned fixture")
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("SOMA ISOLATED X11: synthetic keyboard/mouse events only"))
    events = []
    line = fixture.TestLine(events)
    canvas = fixture.Canvas(events)
    layout.addWidget(line)
    layout.addWidget(canvas, 1)
    # Xvfb deliberately runs without a window manager; size the owned window
    # explicitly because no WM is available to honor fullscreen requests.
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    window.setGeometry(app.primaryScreen().geometry())
    window.show()
    window.activateWindow()
    line.setFocus(Qt.FocusReason.OtherFocusReason)
    deadline = time.monotonic() + 35
    port = teacher = recorder = store = None

    def pump(seconds=0.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if time.monotonic() > deadline:
                raise TimeoutError("Isolated X11 fixture exceeded its deadline")
            app.processEvents()
            time.sleep(0.005)

    def focused():
        app.processEvents()
        if not window.isActiveWindow() or not line.hasFocus():
            raise RuntimeError("Owned isolated fixture focus was lost; input stopped")

    def native(function):
        focused()
        errors = []
        def work():
            try:
                function()
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=work)
        worker.start()
        while worker.is_alive():
            pump(0.01)
            focused()
        worker.join()
        pump()
        if errors:
            raise errors[0]

    try:
        pump(0.5)
        focused()
        port = HumanInterfacePort()
        frame = port.capture_monitor_pixels()
        report["geometry"] = frame.geometry()
        report["backend"] = port.backend
        report["fixture_geometry"] = {"width": window.width(), "height": window.height(),
                                      "dpr": window.devicePixelRatioF()}
        assert port.backend == "xorg" and frame.width == window.width() and frame.height == window.height(), report["fixture_geometry"]
        (output / "before.png").write_bytes(frame.png)

        def point(widget, x, y):
            value = widget.mapToGlobal(QPoint(x, y))
            return {"x": (value.x() - frame.x) / (frame.width - 1),
                    "y": (value.y() - frame.y) / (frame.height - 1)}

        def act(kind, values, device=None):
            native(lambda: (device or port).execute(Action(kind, values), frame))

        act("click", point(canvas, 70, 70))
        act("double_click", point(canvas, 140, 70))
        start, finish = point(canvas, 210, 80), point(canvas, 500, 210)
        act("drag", {**start, "x2": finish["x"], "y2": finish["y"]})
        act("scroll", {"dx": 0, "dy": 2})
        act("click", point(line, 100, 20))
        act("type_text", {"text": "Привіт SOMA 🦆"})
        report["typed_unicode"] = line.text()
        assert line.text() == "Привіт SOMA 🦆", repr(line.text())
        report["checks"]["native_unicode_keyboard"] = True
        act("hotkey", {"keys": ["ctrl", "a"]})
        act("type_text", {"text": "Verified"})
        assert line.text() == "Verified", repr(line.text())
        report["checks"]["native_hotkey"] = True
        counts = Counter(event["kind"] for event in events)
        assert counts["double_click"] >= 1 and counts["drag_move"] >= 1 and counts["wheel"] >= 1
        report["checks"]["native_mouse_click_double_drag_scroll"] = True
        after = port.capture_monitor_pixels()
        (output / "after.png").write_bytes(after.png)
        assert frame.png != after.png
        report["checks"]["pixel_capture_observes_effect"] = True

        store = MemoryStore(output / "app-data")
        recorder = DemonstrationRecorder(store, port)
        teacher = HumanInterfacePort()
        recorder.start()
        recorder.capture(port.capture_monitor_pixels())
        try:
            act("key", {"key": "a"})
        except InputInhibited:
            report["checks"]["teaching_inhibits_body"] = True
        else:
            raise AssertionError("Teaching did not inhibit the autonomous body")
        act("type_text", {"text": " teacher"}, device=teacher)
        recorder.capture(port.capture_monitor_pixels())
        before_private = len(recorder._trace["steps"])
        recorder.pause_recording(True)
        act("type_text", {"text": " PRIVATE-OMITTED"}, device=teacher)
        assert recorder.capture(port.capture_monitor_pixels()) is None
        assert len(recorder._trace["steps"]) == before_private
        recorder.pause_recording(False)
        recorder.capture(port.capture_monitor_pixels())
        trace = recorder.stop()
        assert trace["steps"] and trace["gaps"] and not recorder.active and not recorder._hooks
        assert any(step["after_frame_id"] for step in trace["steps"])
        report["checks"]["native_demonstration_hooks"] = True
        report["checks"]["private_pixels_and_inputs_omitted"] = True
        report["checks"]["listeners_stop"] = True
        report["demonstration_steps"] = len(trace["steps"])
        report["fixture_event_counts"] = dict(Counter(event["kind"] for event in events))
        report["passed"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if recorder and recorder.active:
            try:
                recorder.stop()
            except Exception as exc:
                report["cleanup_error"] = type(exc).__name__
        for resource in (teacher, port, store):
            if resource:
                resource.close()
        window.close()
        app.processEvents()
        report["finished_at"] = utc_now()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
