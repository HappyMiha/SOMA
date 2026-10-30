from io import BytesIO

from PIL import Image

from soma.core import ScreenFrame
from soma.memory import MemoryStore


def test_frame_ids_resolve_in_restored_persona_without_following_old_paths(tmp_path):
    output = BytesIO()
    Image.new("RGB", (10, 10), "white").save(output, "PNG")
    frame = ScreenFrame(output.getvalue(), 10, 10)
    original = MemoryStore(tmp_path / "original")
    old_path = original.save_frame(frame)
    original.add_memory("episodic", {"demonstration": {"id": "d", "frames": [{"frame_id": frame.frame_id, "path": old_path}]}}, {"test": True})
    archive = tmp_path / "backup.zip"
    original.backup(archive)
    original.close()
    MemoryStore.restore_backup(archive, tmp_path / "restored")
    restored = MemoryStore(tmp_path / "restored")
    try:
        path = restored.frame_path(frame.frame_id)
        assert path and path.is_relative_to(restored.data_dir)
        assert str(path) != old_path
        assert path.read_bytes() == frame.png
        assert restored.frame_path("unknown") is None
    finally:
        restored.close()
