import json
from continuous_telemetry import (
    parse_docker_log_line,
    compute_log_hash,
    seed_seen_log_hashes_from_file,
    seen_log_hashes
)

def test_parse_docker_log_line_with_timestamp():
    raw_line = "2026-08-17T12:00:00.123456789Z [ERROR] Failed to process order: connection timeout"
    docker_ts, content = parse_docker_log_line(raw_line)
    assert docker_ts == "2026-08-17T12:00:00.123456789Z"
    assert content == "[ERROR] Failed to process order: connection timeout"

def test_parse_docker_log_line_with_offset_timestamp():
    raw_line = "2026-08-17T12:00:00.987654+00:00 [WARN] High memory pressure detected"
    docker_ts, content = parse_docker_log_line(raw_line)
    assert docker_ts == "2026-08-17T12:00:00.987654+00:00"
    assert content == "[WARN] High memory pressure detected"

def test_parse_docker_log_line_without_timestamp():
    raw_line = "[INFO] Starting application server on port 8080"
    docker_ts, content = parse_docker_log_line(raw_line)
    assert docker_ts == ""
    assert content == "[INFO] Starting application server on port 8080"

def test_nanosecond_timestamps_prevent_storm_dedup_suppression():
    msg = "[ERROR] Database deadlock occurred"
    ts1 = "2026-08-17T12:00:00.100000001Z"
    ts2 = "2026-08-17T12:00:00.100000002Z"
    
    hash1 = compute_log_hash("order-service", ts1, msg, "2026-08-17T12:00:00Z")
    hash2 = compute_log_hash("order-service", ts2, msg, "2026-08-17T12:00:00Z")
    
    assert hash1 != hash2, "Distinct nanosecond timestamps for identical messages must produce distinct hashes"

def test_seed_seen_log_hashes_from_file(tmp_path):
    events_file = str(tmp_path / "events.json")
    mock_events = [
        {
            "container": "payment-service",
            "timestamp": "2026-08-17T12:00:00Z",
            "content": "Payment failed: insufficient funds"
        }
    ]
    with open(events_file, "w", encoding="utf-8") as f:
        json.dump(mock_events, f)
    
    initial_count = len(seen_log_hashes)
    seed_seen_log_hashes_from_file(events_file)
    assert len(seen_log_hashes) >= initial_count + 1
