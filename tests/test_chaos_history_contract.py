import sys
import os
import json
from datetime import datetime
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaos_orchestrator import log_chaos_event

def parse_iso(ts_str):
    return datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))

def test_chaos_history_entry_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "frontend_data", exist_ok=True)
    
    # Trigger log_chaos_event
    start_ts = "2026-08-15T12:00:00+00:00"
    end_ts = "2026-08-15T12:00:15+00:00"
    log_chaos_event("pause_container", "payment-service", start_ts, end_ts, {"duration": 15}, 15.0)

    target_file = tmp_path / "frontend_data" / "chaos_history.json"
    assert target_file.exists()

    with open(target_file, "r", encoding="utf-8") as f:
        entries = json.load(f)

    assert isinstance(entries, list)
    assert len(entries) == 1

    entry = entries[0]
    required_keys = {"fault_name", "target", "start_ts", "end_ts"}
    assert required_keys.issubset(entry.keys())
    assert entry["fault_name"] == "pause_container"
    assert entry["target"] == "payment-service"

    t_start = parse_iso(entry["start_ts"])
    t_end = parse_iso(entry["end_ts"])
    assert t_end > t_start, f"Expected end_ts ({t_end}) > start_ts ({t_start})"
