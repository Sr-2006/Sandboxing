from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from chaos_watchdog import reconcile_stale_chaos_events
from utils import read_json_file, atomic_write_json

def test_reconcile_recovers_stale_injected_event(tmp_path, monkeypatch):
    history_file = str(tmp_path / "chaos_history.json")
    
    # Event injected 20 minutes ago with 60s duration
    start_dt = datetime.now(timezone.utc) - timedelta(minutes=20)
    initial_events = [
        {
            "event_id": "evt-stale-1",
            "scenario_id": "scen-old",
            "fault_name": "cpu_throttle",
            "target": "order-service",
            "start_ts": start_dt.isoformat(),
            "end_ts": (start_dt + timedelta(seconds=60)).isoformat(),
            "params": {},
            "duration_s": 60.0,
            "status": "injected"
        }
    ]
    atomic_write_json(history_file, initial_events)

    mock_recover = MagicMock()
    monkeypatch.setattr("chaos_orchestrator.recover_fault", mock_recover)

    reconciled = reconcile_stale_chaos_events(history_filepath=history_file, grace_seconds=600.0)

    assert reconciled == 1
    mock_recover.assert_called_once_with("cpu_throttle", "order-service", scenario_id="scen-old")

    updated_history = read_json_file(history_file, [])
    assert len(updated_history) == 2
    rec_event = updated_history[-1]
    assert rec_event["status"] == "recovered"
    assert rec_event["fault_name"] == "cpu_throttle"
    assert rec_event["target"] == "order-service"
    assert rec_event["params"]["recovery"] == "watchdog"
    assert rec_event["params"]["original_event_id"] == "evt-stale-1"

def test_reconcile_ignores_recent_injected_event(tmp_path, monkeypatch):
    history_file = str(tmp_path / "chaos_history.json")
    
    # Event injected only 10 seconds ago
    start_dt = datetime.now(timezone.utc) - timedelta(seconds=10)
    initial_events = [
        {
            "event_id": "evt-recent-1",
            "scenario_id": "scen-active",
            "fault_name": "network_latency",
            "target": "payment-service",
            "start_ts": start_dt.isoformat(),
            "end_ts": (start_dt + timedelta(seconds=60)).isoformat(),
            "params": {"latency_ms": 200},
            "duration_s": 60.0,
            "status": "injected"
        }
    ]
    atomic_write_json(history_file, initial_events)

    mock_recover = MagicMock()
    monkeypatch.setattr("chaos_orchestrator.recover_fault", mock_recover)

    reconciled = reconcile_stale_chaos_events(history_filepath=history_file, grace_seconds=600.0)

    assert reconciled == 0
    mock_recover.assert_not_called()

    updated_history = read_json_file(history_file, [])
    assert len(updated_history) == 1

def test_reconcile_handles_recovery_failure_gracefully(tmp_path, monkeypatch):
    history_file = str(tmp_path / "chaos_history.json")
    
    start_dt = datetime.now(timezone.utc) - timedelta(minutes=30)
    initial_events = [
        {
            "event_id": "evt-fail-1",
            "scenario_id": "scen-broken",
            "fault_name": "memory_limit",
            "target": "auth-service",
            "start_ts": start_dt.isoformat(),
            "end_ts": (start_dt + timedelta(seconds=30)).isoformat(),
            "params": {},
            "duration_s": 30.0,
            "status": "injected"
        }
    ]
    atomic_write_json(history_file, initial_events)

    def mock_broken_recover(fault, target, orig_config=None, scenario_id="adhoc"):
        raise RuntimeError("Docker daemon unreachable")

    monkeypatch.setattr("chaos_orchestrator.recover_fault", mock_broken_recover)

    # Should NOT raise exception
    reconciled = reconcile_stale_chaos_events(history_filepath=history_file, grace_seconds=600.0)

    assert reconciled == 1
    updated_history = read_json_file(history_file, [])
    assert len(updated_history) == 2
    failed_event = updated_history[-1]
    assert failed_event["status"] == "failed"
    assert failed_event["params"]["recovery"] == "failed"
    assert "Docker daemon unreachable" in failed_event["params"]["error"]

def test_reconcile_skips_already_completed_events(tmp_path, monkeypatch):
    history_file = str(tmp_path / "chaos_history.json")
    
    start_dt = datetime.now(timezone.utc) - timedelta(hours=2)
    initial_events = [
        {
            "event_id": "evt-recovered-1",
            "scenario_id": "scen-done",
            "fault_name": "pause_container",
            "target": "api-gateway",
            "start_ts": start_dt.isoformat(),
            "end_ts": (start_dt + timedelta(seconds=10)).isoformat(),
            "params": {},
            "duration_s": 10.0,
            "status": "recovered"
        }
    ]
    atomic_write_json(history_file, initial_events)

    mock_recover = MagicMock()
    monkeypatch.setattr("chaos_orchestrator.recover_fault", mock_recover)

    reconciled = reconcile_stale_chaos_events(history_filepath=history_file, grace_seconds=600.0)

    assert reconciled == 0
    mock_recover.assert_not_called()
