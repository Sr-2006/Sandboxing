import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import stitch_log_events, preprocess_log_header, EXCEPTION_START_RE
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

def test_stack_trace_stitching_and_template():
    events = [
        {
            "container": "order-service",
            "timestamp": "2026-08-15T10:00:00Z",
            "level": "ERROR",
            "content": "java.lang.NullPointerException: Order payment token is null",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7"
        },
        {
            "container": "order-service",
            "timestamp": "2026-08-15T10:00:01Z",
            "level": "ERROR",
            "content": "\tat com.autosre.orderservice.OrderController.processOrder(OrderController.java:50)",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7"
        },
        {
            "container": "order-service",
            "timestamp": "2026-08-15T10:00:02Z",
            "level": "ERROR",
            "content": "\tat com.autosre.orderservice.OrderService.charge(OrderService.java:85)",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7"
        },
        {
            "container": "order-service",
            "timestamp": "2026-08-15T10:00:03Z",
            "level": "ERROR",
            "content": "\tat org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1089)",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7"
        }
    ]

    stitched = stitch_log_events(events)
    assert len(stitched) == 1
    first = stitched[0]
    assert "java.lang.NullPointerException" in first["content"]
    assert "OrderController.processOrder" in first["content"]

    cfg = TemplateMinerConfig()
    miner = TemplateMiner(config=cfg)
    header = preprocess_log_header(first["content"].split("\n")[0])
    res = miner.add_log_message(header)
    assert "NullPointerException" in res["template_mined"]

def test_stitching_preserves_chronological_order_of_first_lines():
    # FIX M2: Interleaved logs from multiple containers must preserve first-line arrival order
    events = [
        {
            "container": "auth-service",
            "timestamp": "2026-08-15T10:00:00Z",
            "level": "ERROR",
            "content": "java.lang.IllegalArgumentException: Invalid token",
        },
        {
            "container": "order-service",
            "timestamp": "2026-08-15T10:00:01Z",
            "level": "INFO",
            "content": "Order checkout initialized for user 123",
        },
        {
            "container": "auth-service",
            "timestamp": "2026-08-15T10:00:02Z",
            "level": "ERROR",
            "content": "\tat com.ecommerce.auth.JwtUtil.validate(JwtUtil.java:42)",
        },
        {
            "container": "payment-service",
            "timestamp": "2026-08-15T10:00:03Z",
            "level": "INFO",
            "content": "Payment gateway ping OK",
        }
    ]

    stitched = stitch_log_events(events)
    assert len(stitched) == 3
    # Index 0: auth-service exception block (started at 10:00:00)
    assert stitched[0]["container"] == "auth-service"
    assert "IllegalArgumentException" in stitched[0]["content"]
    assert "JwtUtil.validate" in stitched[0]["content"]
    assert stitched[0]["timestamp"] == "2026-08-15T10:00:00Z"

    # Index 1: order-service info (arrived at 10:00:01)
    assert stitched[1]["container"] == "order-service"
    assert stitched[1]["timestamp"] == "2026-08-15T10:00:01Z"

    # Index 2: payment-service info (arrived at 10:00:03)
    assert stitched[2]["container"] == "payment-service"
    assert stitched[2]["timestamp"] == "2026-08-15T10:00:03Z"

def test_stitching_under_load_does_not_disable():
    # FIX M1: When more than 50 exception blocks occur, stitching continues
    events = []
    for i in range(60):
        events.append({
            "container": "order-service",
            "timestamp": f"2026-08-15T10:00:{i:02d}Z",
            "level": "ERROR",
            "content": f"java.lang.RuntimeException: Error number {i}"
        })
        events.append({
            "container": "order-service",
            "timestamp": f"2026-08-15T10:00:{i:02d}Z",
            "level": "ERROR",
            "content": f"\tat com.autosre.orderservice.Handler.run(Handler.java:{i})"
        })

    stitched = stitch_log_events(events)
    assert len(stitched) == 60
    # Every single event was properly stitched with its stack trace line
    for i, ev in enumerate(stitched):
        assert f"Error number {i}" in ev["content"]
        assert f"Handler.run(Handler.java:{i})" in ev["content"]

def test_stricter_exception_start_regex():
    # FIX M1: Valid exception starts
    assert EXCEPTION_START_RE.search("java.lang.NullPointerException: foo")
    assert EXCEPTION_START_RE.search("2026-08-15 ERROR [main] App - NullPointerException: boom")
    assert EXCEPTION_START_RE.search("Caused by: java.sql.SQLException: connection reset")
    assert EXCEPTION_START_RE.search("RuntimeError: something broke")
