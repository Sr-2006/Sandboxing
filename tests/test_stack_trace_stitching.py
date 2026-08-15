import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import stitch_log_events, preprocess_log_header
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
