import os
from utils import atomic_write_json

def test_atomic_write_invokes_fsync_before_replace(tmp_path, monkeypatch):
    target_file = str(tmp_path / "test_data.json")
    call_log = []

    real_fsync = os.fsync
    real_replace = os.replace

    def mock_fsync(fd):
        call_log.append("fsync")
        return real_fsync(fd)

    def mock_replace(src, dst):
        call_log.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", mock_fsync)
    monkeypatch.setattr(os, "replace", mock_replace)

    atomic_write_json(target_file, {"status": "ok"})

    assert "fsync" in call_log
    assert "replace" in call_log
    fsync_idx = call_log.index("fsync")
    replace_idx = call_log.index("replace")
    assert fsync_idx < replace_idx, f"Expected fsync before replace, got log: {call_log}"
