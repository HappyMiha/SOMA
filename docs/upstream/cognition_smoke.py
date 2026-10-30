"""Offline upstream audit probes, not a full model/desktop benchmark.

Run from the SOMA repository. AST isolation avoids loading neural dependencies;
the selected upstream definitions execute unchanged, only in this audit process.
"""
import ast
import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / ".upstream"


def definitions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


qwen = definitions(
    UPSTREAM / "Qwen3-VL/qwen-vl-utils/src/qwen_vl_utils/vision_process.py",
    {"round_by_factor", "ceil_by_factor", "floor_by_factor", "smart_resize"},
    {"math": math, "Optional": Optional, "Tuple": Tuple, "MAX_RATIO": 200,
     "IMAGE_MAX_TOKEN_NUM": 16384, "IMAGE_MIN_TOKEN_NUM": 4},
)
resized = qwen["smart_resize"](1080, 1920, factor=32, min_pixels=4096, max_pixels=1280 * 32 * 32)
assert all(value % 32 == 0 for value in resized)
assert resized[0] * resized[1] <= 1280 * 32 * 32
print("Qwen isolated smart_resize:", resized)

memory = definitions(
    UPSTREAM / "generative_agents/reverie/backend_server/persona/memory_structures/associative_memory.py",
    {"ConceptNode", "AssociativeMemory"}, {"json": json, "datetime": datetime},
)
with tempfile.TemporaryDirectory() as directory:
    location = Path(directory)
    for filename, data in {"embeddings.json": {}, "nodes.json": {}, "kw_strength.json": {"kw_strength_event": {}, "kw_strength_thought": {}}}.items():
        (location / filename).write_text(json.dumps(data), encoding="utf-8")
    store = memory["AssociativeMemory"](location.as_posix())
    store.add_event(datetime.datetime(2026, 10, 30, 12), None, "SOMA", "observes", "screen", "SOMA observes screen", {"screen"}, 5, ("screen", [1.0, 0.0]), None)
    store.save(location.as_posix())
    restored = memory["AssociativeMemory"](location.as_posix())
    assert len(restored.id_to_node) == 1
    assert restored.id_to_node["node_1"].description == "SOMA observes screen"
    print("Generative Agents isolated memory roundtrip:", len(restored.id_to_node), "event")

osworld = UPSTREAM / "OSWorld-V2"
spec = importlib.util.spec_from_file_location("audit_osworld_task", osworld / "desktop_env/task_base.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
task = module.BaseTask(id="audit", instruction="observe screen")
assert task.to_dict()["platform"] == "linux"
manifest = json.loads((osworld / "benchmark_releases/osworld-v2.1.json").read_text())
entry = manifest["task_hash_manifest"]
contents = subprocess.check_output(["git", "-C", str(osworld), "show", "HEAD:" + entry["path"]])
assert "sha256:" + hashlib.sha256(contents).hexdigest() == entry["sha256"]
assert len(json.loads(contents)["files"]) == entry["task_count"] == 108
print("OSWorld BaseTask + v2.1 task hash manifest: PASS, 108 entries")
