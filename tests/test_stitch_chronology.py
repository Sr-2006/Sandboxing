from phase1_processor import stitch_log_events

def test_stitching_preserves_original_chronological_position():
    events = [
        {"container": "order-service", "timestamp": "2026-08-15T12:00:01Z", "content": "java.lang.NullPointerException: user not found"},
        {"container": "order-service", "timestamp": "2026-08-15T12:00:02Z", "content": "    at com.autosre.OrderService.process(OrderService.java:42)"},
        {"container": "order-service", "timestamp": "2026-08-15T12:00:03Z", "content": "    at com.autosre.OrderService.run(OrderService.java:10)"},
        {"container": "order-service", "timestamp": "2026-08-15T12:00:04Z", "content": "Payment verification starting for txn_123"},
        {"container": "order-service", "timestamp": "2026-08-15T12:00:05Z", "content": "Order finalized successfully."}
    ]

    stitched = stitch_log_events(events)

    assert len(stitched) == 3
    # Index 0 must be the multi-line exception block
    assert "NullPointerException" in stitched[0]["content"]
    assert "OrderService.java:42" in stitched[0]["content"]
    assert stitched[0]["timestamp"] == "2026-08-15T12:00:01Z"

    # Index 1 must be the normal log following the exception
    assert stitched[1]["content"] == "Payment verification starting for txn_123"
    assert stitched[1]["timestamp"] == "2026-08-15T12:00:04Z"

    # Index 2 must be the final normal log
    assert stitched[2]["content"] == "Order finalized successfully."
    assert stitched[2]["timestamp"] == "2026-08-15T12:00:05Z"
