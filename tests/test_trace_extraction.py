import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from continuous_telemetry import parse_trace_span_ids

def test_json_line_extraction():
    line = '{"timestamp":"2026-08-15T10:00:00Z","level":"ERROR","trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7","message":"Fail"}'
    t_id, s_id = parse_trace_span_ids(line)
    assert t_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert s_id == "00f067aa0ba902b7"

def test_w3c_header_extraction():
    line = "2026-08-15 10:00:00.000 ERROR traceparent=00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01 [main] com.example: Error occurred"
    t_id, s_id = parse_trace_span_ids(line)
    assert t_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert s_id == "00f067aa0ba902b7"

def test_logback_default_pattern_extraction():
    line = "2026-08-15 10:00:00.000 ERROR [auth-service,4bf92f3577b34da6a3ce929d0e0e4736,00f067aa0ba902b7] [http-nio-8081-exec-1] com.auth.Service: Failure"
    t_id, s_id = parse_trace_span_ids(line)
    assert t_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert s_id == "00f067aa0ba902b7"

def test_otel_keyvalue_pattern_extraction():
    line = "2026-08-15 10:00:00.000 ERROR [trace_id=4bf92f3577b34da6a3ce929d0e0e4736, span_id=00f067aa0ba902b7] com.auth.Service: Failure"
    t_id, s_id = parse_trace_span_ids(line)
    assert t_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert s_id == "00f067aa0ba902b7"

def test_uninstrumented_line_returns_none():
    line = "2026-08-15 10:00:00.000 INFO Simple log message without trace context"
    t_id, s_id = parse_trace_span_ids(line)
    assert t_id is None
    assert s_id is None
