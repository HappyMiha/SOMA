"""Developer-only two-run integration smoke with deterministic wait cognition.

This is not an AI/VLM autonomy test. The loopback stub discards request bytes
without parsing JSON, decoding images, or retaining screenshot content.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from soma.config import ModelConfig
from soma.core import utc_now


WAIT_DECISION = {
    "scene": "DETERMINISTIC TEST STUB: no screenshot interpretation is performed",
    "intention": "Wait during the bounded synthetic runtime smoke test",
    "goal": {"origin": "self", "motive": "deterministic integration test",
             "description": "Wait without emitting mouse or keyboard input",
             "priority": 0.5, "expected_outcome": "Bounded shutdown and durable continuity"},
    "uncertainty": 0.1, "reconsider_after": 1,
    "action": {"kind": "wait", "args": {"seconds": 1}, "expected": "No native input"},
    "goal_updates": [], "memory_updates": [],
}


class CognitionStub(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        remaining = int(self.headers.get("Content-Length", "0"))
        received = 0
        while remaining:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            received += len(chunk)
            remaining -= len(chunk)
        # Never parse/decode/log the input body, which contains monitor pixels.
        self.server.request_evidence.append({"path": self.path, "bytes_discarded": received,
                                             "received_at": utc_now()})
        payload = json.dumps({"choices": [{"message": {"role": "assistant",
            "content": json.dumps(WAIT_DECISION)}}], "usage": {"prompt_tokens": 0,
            "completion_tokens": 0}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def inspect_memory(directory):
    # SOMA is the world; the memory lives in its active inhabitant's home (soma.world).
    registry = directory / "world.json"
    if not registry.is_file():
        raise RuntimeError("The target settled no world; check startup logs or an existing singleton instance")
    world = json.loads(registry.read_text(encoding="utf-8"))
    home = next(i["home"] for i in world["inhabitants"] if i["id"] == world["active"])
    database = directory / home / "memory.sqlite3"
    if not database.is_file():
        raise RuntimeError("The target created no runtime database; check startup logs or an existing singleton instance")
    with closing(sqlite3.connect(database)) as connection:
        identity = json.loads(connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
        counts = dict(Counter(row[0] for row in connection.execute("SELECT kind FROM events")))
        checkpoint = json.loads(connection.execute("SELECT state FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()[0])
        return {"persona_id": identity["persona_id"], "event_counts": counts,
                "checkpoint_count": connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0],
                "captured_frames": connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0],
                "action_rows": connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                "last_state": checkpoint["state"], "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0]}


def run_target(command, data_dir, output, run_number):
    # Long enough for the first decision: on a CPU the machine-vision model
    # loads and reads a full screen before cognition is asked, and a freshly
    # installed copy's first launch loads its model files cold (observed >30 s).
    arguments = [*command, "--smoke-seconds", "60", "--smoke-life", "--data-dir", str(data_dir)]
    started = time.monotonic()
    evidence = {"run": run_number, "started_at": utc_now(), "command": arguments,
                "stdout_log": f"run-{run_number}.stdout.log", "stderr_log": f"run-{run_number}.stderr.log"}
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    with (output / evidence["stdout_log"]).open("wb") as stdout, (output / evidence["stderr_log"]).open("wb") as stderr:
        process = subprocess.Popen(arguments, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            evidence["exit_code"] = process.wait(timeout=110)
        except subprocess.TimeoutExpired:
            evidence["timed_out"] = True
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            evidence["exit_code"] = process.returncode
    evidence["ended_at"] = utc_now()
    evidence["duration_seconds"] = round(time.monotonic() - started, 3)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--python", type=Path, help="Explicit Python executable for source -m soma")
    target.add_argument("--executable", type=Path, help="Explicit packaged SOMA binary to launch")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/windows-package")
    args = parser.parse_args()
    executable = (args.python or args.executable).resolve()
    if not executable.is_file():
        parser.error("The explicitly supplied executable does not exist")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [str(executable), "-m", "soma"] if args.python else [str(executable)]
    report = {"started_at": utc_now(), "passed": False, "mode": "source" if args.python else "packaged",
        "cognition": "deterministic loopback wait stub; no AI/VLM screenshot interpretation",
        "scope": "two-run native UI/body capture/provider/storage/shutdown integration",
        "screenshots": "App-owned temporary frames only; harness never reads or decodes image files or HTTP image content",
        "limitations": ["No VLM autonomy, workflow competence or correspondence established",
                        "No native input or demonstration hooks requested", "Current host/session only"], "runs": []}
    server = HTTPServer(("127.0.0.1", 0), CognitionStub)
    server.request_evidence = []
    server_thread = threading.Thread(target=server.serve_forever, name="deterministic-cognition-stub", daemon=True)
    server_thread.start()
    try:
        # This directory is created by this harness and removed after both runs.
        # Only the app opens its screen image files; inspection reads own SQLite.
        with tempfile.TemporaryDirectory(prefix="soma-runtime-smoke-") as temporary:
            data_dir = Path(temporary)
            ModelConfig(mode="local", local_endpoint=f"http://127.0.0.1:{server.server_port}/v1",
                local_model="test-stub", requests_per_minute=12, timeout_seconds=5).save(data_dir)
            previous_frames = 0
            for number in (1, 2):
                before_requests = len(server.request_evidence)
                run = run_target(command, data_dir, output, number)
                report["runs"].append(run)
                if run.get("timed_out") or run["exit_code"] != 0:
                    raise RuntimeError(f"Target run {number} did not shut down cleanly")
                run["storage"] = inspect_memory(data_dir)
                run["loopback_requests"] = len(server.request_evidence) - before_requests
                storage = run["storage"]
                counts = storage["event_counts"]
                if run["loopback_requests"] < 1 or storage["captured_frames"] <= previous_frames:
                    raise RuntimeError(f"Run {number} did not exercise body capture and loopback cognition")
                if counts.get("wake", 0) < number or counts.get("sleep", 0) < number or storage["checkpoint_count"] < 2 * number:
                    raise RuntimeError(f"Run {number} lacks durable wake/sleep/checkpoints")
                if counts.get("rest", 0) < number or counts.get("recoverable_error", 0):
                    raise RuntimeError(f"Run {number} did not accept the valid deterministic wait decision cleanly")
                if counts.get("action.intent", 0) or counts.get("demonstration_started", 0) or storage["action_rows"]:
                    raise RuntimeError("The wait-only smoke unexpectedly journaled input or started hooks")
                if storage["last_state"] != "ASLEEP" or storage["integrity_check"] != "ok":
                    raise RuntimeError(f"Run {number} left an invalid final state or database")
                previous_frames = storage["captured_frames"]
            ids = [run["storage"]["persona_id"] for run in report["runs"]]
            if ids[0] != ids[1] or report["runs"][-1]["storage"]["event_counts"].get("identity.created") != 1:
                raise RuntimeError("The two runs did not retain one continuous persona")
            report["checks"] = {"same_persona_across_two_runs": True, "native_capture_frames": True,
                "loopback_cognition_requests": True, "durable_wake_sleep_checkpoints": True,
                "no_action_intent_or_hooks": True, "clean_shutdowns": True}
            report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        report["requests"] = server.request_evidence
        report["ended_at"] = utc_now()
        (output / "runtime-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "mode": report["mode"], "requests": len(report["requests"]),
                      "error": report.get("error"), "report": str(output / "runtime-smoke.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
