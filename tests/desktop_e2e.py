"""Opt-in native Windows input/capture evidence, restricted to an owned Qt fixture.

Run: .venv/Scripts/python tests/desktop_e2e.py --run-desktop
No model, browser, third-party application, user keystroke recording or clipboard.
"""

from __future__ import annotations

import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from soma.body import HumanInterfacePort, InputInhibited
from soma.core import Action, Monitor, ScreenFrame, utc_now
from soma.demonstration import DemonstrationRecorder
from soma.memory import MemoryStore


class TestLine(QLineEdit):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.focus_seen = False
        self.setMinimumHeight(55)

    def focusInEvent(self, event):
        self.focus_seen = True
        self.events.append({"kind": "focus_in"})
        super().focusInEvent(event)

    def keyPressEvent(self, event):
        self.events.append({"kind": "key_down", "key": event.key(), "text": event.text()})
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        self.events.append({"kind": "key_up", "key": event.key(), "text": event.text()})
        super().keyReleaseEvent(event)


class Canvas(QWidget):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.marker = QPoint(70, 70)

    def note(self, kind, event):
        self.events.append({"kind": kind, "x": round(event.position().x()), "y": round(event.position().y())})
        self.marker = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event):
        self.note("mouse_down", event)

    def mouseReleaseEvent(self, event):
        self.note("mouse_up", event)

    def mouseDoubleClickEvent(self, event):
        self.note("double_click", event)

    def mouseMoveEvent(self, event):
        self.note("drag_move" if event.buttons() else "mouse_move", event)

    def wheelEvent(self, event):
        self.events.append({"kind": "wheel", "dx": event.angleDelta().x(), "dy": event.angleDelta().y()})
        self.update()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#e7edf8"))
        painter.setPen(QColor("#26344e"))
        painter.drawText(20, 30, "OWNED TEST CANVAS · click / double click / drag / wheel")
        painter.setBrush(QColor("#6d5ce7"))
        painter.drawEllipse(self.marker, 18, 18)
        painter.drawText(20, self.height() - 20, f"Observed fixture events: {len(self.events)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-desktop", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/windows-desktop")
    args = parser.parse_args()
    if not args.run_desktop:
        print("SKIP: native desktop evidence requires explicit --run-desktop")
        return 0
    if sys.platform != "win32":
        parser.error("This evidence fixture currently runs on Windows only")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"started_at": utc_now(), "passed": False, "scope": "real native input into owned Qt fixture; actual monitor pixels cropped to fixture", "checks": {}, "limitations": ["No model inference or external-application task success tested", "Current physical display configuration only; synthetic scaling tests are separate", "Demonstration hooks accept injected events only during the visible synthetic teacher phase", "Screenshots are fixture crops of real port captures; other desktop pixels are not saved"]}
    app = QApplication(sys.argv[:1])
    app.setApplicationName("SOMA owned desktop evidence")
    window = QWidget()
    window.setWindowTitle("SOMA LIVE TEST · OWNED FIXTURE · max 25 seconds")
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    layout = QVBoxLayout(window)
    banner = QLabel("SOMA LIVE DESKTOP TEST — SYNTHETIC INPUT ONLY\nThis owned fixture closes automatically within 25 seconds. No user keystrokes are recorded.")
    banner.setStyleSheet("font-size:22px; color:#ffffff; background:#5243a8; padding:20px")
    layout.addWidget(banner)
    events = []
    line = TestLine(events)
    line.setPlaceholderText("Owned Ukrainian / emoji / hotkey test field")
    layout.addWidget(line)
    canvas = Canvas(events)
    layout.addWidget(canvas, 1)
    status = QLabel("Checking owned focus before any native input…")
    status.setStyleSheet("font-size:18px;padding:12px")
    layout.addWidget(status)
    window.showFullScreen()
    window.raise_()
    window.activateWindow()
    line.setFocus(Qt.FocusReason.OtherFocusReason)
    deadline = time.monotonic() + 25
    port = teacher = recorder = store = None
    synthetic_phase = threading.Event()

    def pump(seconds=0.15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if time.monotonic() > deadline:
                raise TimeoutError("Owned desktop test exceeded 25 seconds")
            app.processEvents()
            time.sleep(0.005)

    def focused():
        app.processEvents()
        if not window.isVisible() or not window.isActiveWindow() or not line.hasFocus() or not line.focus_seen:
            synthetic_phase.clear()
            raise RuntimeError("Owned Qt fixture focus was not confirmed; native input aborted")

    try:
        pump(0.8)
        focused()
        port = HumanInterfacePort()
        frame = port.capture_monitor_pixels()
        screen = window.screen()
        logical = screen.geometry()
        # The fullscreen fixture is explicitly placed on the Qt primary display.
        # Refuse ambiguous monitor layouts rather than guess physical targets.
        if screen != app.primaryScreen() or logical.x() != 0 or logical.y() != 0:
            raise RuntimeError("Fixture requires the primary monitor at Qt origin (0,0)")
        monitor = next((m for m in frame.monitors if m.x == 0 and m.y == 0), None)
        if monitor is None:
            raise RuntimeError("No physical primary monitor at origin; mapping remains unverified")
        sx, sy = monitor.width / logical.width(), monitor.height / logical.height()
        if abs(sx - screen.devicePixelRatio()) > 0.05 or abs(sy - screen.devicePixelRatio()) > 0.05:
            raise RuntimeError("Qt/native DPI mapping differs; native input aborted")
        report["geometry"] = {"capture": frame.geometry(), "fixture_logical": [logical.x(), logical.y(), logical.width(), logical.height()], "fixture_physical": [monitor.x, monitor.y, monitor.width, monitor.height], "scale_x": sx, "scale_y": sy, "qt_dpr": screen.devicePixelRatio()}

        def owned_capture(name=None):
            focused()
            raw = port.capture_monitor_pixels()
            if (raw.width, raw.height, raw.x, raw.y, raw.monitors) != (frame.width, frame.height, frame.x, frame.y, frame.monitors):
                raise RuntimeError("Monitor topology changed during fixture test")
            with Image.open(BytesIO(raw.png)) as image:
                cropped = image.crop((monitor.x - raw.x, monitor.y - raw.y, monitor.x - raw.x + monitor.width, monitor.y - raw.y + monitor.height))
                blob = BytesIO()
                cropped.save(blob, "PNG")
            if name:
                (output / name).write_bytes(blob.getvalue())
            return ScreenFrame(blob.getvalue(), monitor.width, monitor.height, monitor.x, monitor.y, (monitor,), timestamp=raw.timestamp, frame_id=raw.frame_id, captured_monotonic=raw.captured_monotonic)

        def point(widget, x, y):
            pos = widget.mapToGlobal(QPoint(x, y))
            px = monitor.x + round((pos.x() - logical.x()) * sx)
            py = monitor.y + round((pos.y() - logical.y()) * sy)
            if not (monitor.x + 5 < px < monitor.x + monitor.width - 5 and monitor.y + 5 < py < monitor.y + monitor.height - 5):
                raise RuntimeError("Native target falls outside owned fixture interior")
            return {"x": (px - frame.x) / (frame.width - 1), "y": (py - frame.y) / (frame.height - 1)}

        def act(kind, values):
            focused()
            native(lambda: port.execute(Action(kind, values), frame))
            pump()

        def native(function):
            # Match production: input runs on a worker while the target's Qt
            # event loop remains responsive. Sending to our own blocked GUI
            # thread distorts native Unicode packet/WM_CHAR ordering.
            errors = []

            def run():
                try:
                    function()
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run, name="owned-native-test-driver")
            worker.start()
            while worker.is_alive():
                pump(0.01)
                focused()
            worker.join()
            if errors:
                raise errors[0]

        owned_capture("before.png")
        act("click", point(canvas, 70, 70))
        act("double_click", point(canvas, 140, 70))
        start, finish = point(canvas, 210, 80), point(canvas, min(500, canvas.width() - 40), 210)
        act("drag", {**start, "x2": finish["x"], "y2": finish["y"]})
        act("scroll", {"dx": 0, "dy": 2})
        act("click", point(line, 100, line.height() // 2))
        act("type_text", {"text": "Привіт, SOMA 🦆"})
        assert line.text() == "Привіт, SOMA 🦆", repr(line.text())
        report["checks"]["native_ukrainian_and_emoji"] = True
        act("hotkey", {"keys": ["ctrl", "a"]})
        act("type_text", {"text": "Перевірено 🦆"})
        assert line.text() == "Перевірено 🦆", repr(line.text())
        report["checks"]["native_hotkey_selection"] = True
        focused()
        native(lambda: (port.keyboard_key("shift", True), port.release_all()))
        pump()
        counts = Counter(event["kind"] for event in events)
        assert counts["double_click"] >= 1 and counts["drag_move"] >= 1 and counts["wheel"] >= 1
        assert counts["key_down"] == counts["key_up"]
        assert not port._pressed_keys and not port._pressed_buttons
        report["checks"].update(native_click_double_drag_wheel=True, native_key_releases=True)
        owned_capture("after-input.png")

        status.setText("VISIBLE SYNTHETIC TEACHING RECORDING · native hooks accept injected test events only")
        pump()
        focused()
        # Test-only hook filtering. Physical user events never reach the recorder.
        def synthetic_hooks(callback):
            from pynput import keyboard, mouse

            def dispatch(kind, values, injected):
                if injected and synthetic_phase.is_set():
                    callback(kind, values)

            def key_name(key):
                return key.char if getattr(key, "char", None) else str(key)

            return [mouse.Listener(on_click=lambda x, y, button, pressed, injected: dispatch("mouse_down" if pressed else "mouse_up", {"x": x, "y": y, "button": button.name}, injected), on_scroll=lambda x, y, dx, dy, injected: dispatch("scroll", {"x": x, "y": y, "dx": dx, "dy": dy}, injected)), keyboard.Listener(on_press=lambda key, injected: dispatch("key_down", {"key": key_name(key)}, injected), on_release=lambda key, injected: dispatch("key_up", {"key": key_name(key)}, injected))]

        store = MemoryStore(output / "teaching-memory")
        recorder = DemonstrationRecorder(store, port, hook_factory=synthetic_hooks)
        recorder.start()
        recorder.capture(owned_capture())
        try:
            port.type_text("must-not-appear")
            raise AssertionError("SOMA emitted input during teaching")
        except InputInhibited:
            report["checks"]["teaching_inhibits_soma_input"] = True
        teacher = HumanInterfacePort()
        focused()
        synthetic_phase.set()
        # This second port is a test driver simulating a teacher, never runtime SOMA.
        native(lambda: teacher.type_text(" Показ"))
        pump(0.3)
        synthetic_phase.clear()
        recorder.capture(owned_capture("after-teaching.png"))
        trace = recorder.stop()
        report["teaching"] = {"steps": len(trace["steps"]), "frames": len(trace["frames"]), "paired_steps": sum(bool(step["after_frame_id"]) for step in trace["steps"]), "input_kinds": dict(Counter(step["input"]["kind"] for step in trace["steps"]))}
        assert trace["steps"] and all(step["before_frame_id"] and step["after_frame_id"] for step in trace["steps"])
        assert line.text() == "Перевірено 🦆 Показ", repr(line.text())
        (output / "demonstration.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["checks"]["live_synthetic_teaching_hooks_and_persistence"] = True
        report["fixture_events"] = events
        report["fixture_event_counts"] = dict(Counter(event["kind"] for event in events))
        report["final_owned_text"] = line.text()
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["fixture_events"] = events
    finally:
        synthetic_phase.clear()
        if recorder and recorder.active:
            try:
                recorder.stop()
            except Exception as exc:
                report["cleanup_recorder_error"] = type(exc).__name__
        for body in (teacher, port):
            if body:
                body.close()
        if store:
            store.close()
        window.close()
        app.processEvents()
        report["ended_at"] = utc_now()
        report["duration_seconds"] = round(25 - (deadline - time.monotonic()), 3)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("passed", "checks", "error", "duration_seconds")}, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
