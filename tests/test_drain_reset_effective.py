import os
from unittest.mock import MagicMock
import phase1_processor

def test_drain_reset_deletes_old_state_and_rewrites_version(tmp_path, monkeypatch):
    state_file = str(tmp_path / "drain3_state.bin")
    version_file = str(tmp_path / "drain3_version.meta")

    with open(state_file, "wb") as f:
        f.write(b"fake_old_drain3_state_data")
    with open(version_file, "w") as f:
        f.write("1")  # old version (PROCESSOR_VERSION is 2)

    monkeypatch.setattr(phase1_processor, "DRAIN3_STATE_FILE", state_file)
    monkeypatch.setattr(phase1_processor, "VERSION_HEADER_FILE", version_file)

    phase1_processor.check_drain_version_and_reset_if_needed(force_reset=False)

    assert not os.path.exists(state_file), "Old Drain3 state file must be removed"
    assert os.path.exists(version_file), "Version header file must exist"
    with open(version_file, "r") as f:
        assert int(f.read().strip()) == phase1_processor.PROCESSOR_VERSION

def test_process_phase1_incidents_creates_miner_after_reset_check(tmp_path, monkeypatch):
    call_order = []

    def mock_reset_check(reset_drain=False):
        call_order.append("reset_check")

    def mock_template_miner(*args, **kwargs):
        call_order.append("create_miner")
        mock_instance = MagicMock()
        mock_instance.drain.clusters = []
        return mock_instance

    monkeypatch.setattr(phase1_processor, "check_drain_version_and_reset_if_needed", mock_reset_check)
    monkeypatch.setattr(phase1_processor, "TemplateMiner", mock_template_miner)

    # Point events file to an empty file in tmp_path
    events_file = str(tmp_path / "events_and_incidents.json")
    with open(events_file, "w") as f:
        f.write("[]")

    monkeypatch.setattr("utils.project_path", lambda *parts: str(tmp_path / os.path.join(*parts)))

    phase1_processor.process_phase1_incidents(reset_drain=True)

    assert "reset_check" in call_order
    assert "create_miner" in call_order
    assert call_order.index("reset_check") < call_order.index("create_miner"), \
        f"Expected reset_check before create_miner, got: {call_order}"
