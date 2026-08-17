from datetime import datetime, timezone
from utils import correlate_chaos_event

def test_correlate_chaos_event_in_window_match():
    cluster_start = datetime(2026, 8, 15, 12, 5, 0, tzinfo=timezone.utc)
    cluster_end = datetime(2026, 8, 15, 12, 6, 0, tzinfo=timezone.utc)
    history = [
        {
            "fault_name": "cpu_throttle",
            "target": "order-service",
            "start_ts": "2026-08-15T12:04:00+00:00",
            "end_ts": "2026-08-15T12:07:00+00:00",
            "duration_s": 180.0,
            "status": "injected"
        }
    ]
    res = correlate_chaos_event(cluster_start, cluster_end, "order-service", history)
    assert "cpu_throttle on order-service" in res
    assert "injected" in res

def test_correlate_chaos_event_out_of_window_miss():
    cluster_start = datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc)
    cluster_end = datetime(2026, 8, 15, 13, 1, 0, tzinfo=timezone.utc)
    history = [
        {
            "fault_name": "network_latency",
            "target": "payment-service",
            "start_ts": "2026-08-15T12:00:00+00:00",
            "end_ts": "2026-08-15T12:02:00+00:00",
            "duration_s": 120.0,
            "status": "recovered"
        }
    ]
    res = correlate_chaos_event(cluster_start, cluster_end, "payment-service", history)
    assert res == ""

def test_correlate_chaos_event_target_mismatch():
    cluster_start = datetime(2026, 8, 15, 12, 0, 30, tzinfo=timezone.utc)
    cluster_end = datetime(2026, 8, 15, 12, 1, 0, tzinfo=timezone.utc)
    history = [
        {
            "fault_name": "memory_limit",
            "target": "auth-service",
            "start_ts": "2026-08-15T12:00:00+00:00",
            "end_ts": "2026-08-15T12:02:00+00:00",
            "duration_s": 120.0,
            "status": "injected"
        }
    ]
    res = correlate_chaos_event(cluster_start, cluster_end, "order-service", history)
    assert res == ""

def test_correlate_chaos_event_empty_target_wildcard():
    cluster_start = datetime(2026, 8, 15, 12, 0, 30, tzinfo=timezone.utc)
    cluster_end = datetime(2026, 8, 15, 12, 1, 0, tzinfo=timezone.utc)
    history = [
        {
            "fault_name": "dns_failure",
            "target": "",
            "start_ts": "2026-08-15T12:00:00+00:00",
            "end_ts": "2026-08-15T12:02:00+00:00",
            "duration_s": 120.0,
            "status": "injected"
        }
    ]
    res = correlate_chaos_event(cluster_start, cluster_end, "order-service", history)
    assert "dns_failure" in res
