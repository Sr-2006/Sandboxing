import pytest
from unittest.mock import MagicMock
import chaos_orchestrator

def test_tc_network_latency_injection_guard_command_injection(monkeypatch):
    mock_container = MagicMock()
    mock_container.name = "mock-order-service"
    monkeypatch.setattr(chaos_orchestrator, "get_container", lambda target: mock_container)

    # Command injection attempt
    with pytest.raises(ValueError):
        chaos_orchestrator.apply_fault(
            "network_latency",
            "order-service",
            params={"latency_ms": "200; rm -rf /"}
        )

def test_tc_network_latency_out_of_bounds_guard(monkeypatch):
    mock_container = MagicMock()
    mock_container.name = "mock-order-service"
    monkeypatch.setattr(chaos_orchestrator, "get_container", lambda target: mock_container)

    # Exceeds max 10000ms
    with pytest.raises(ValueError):
        chaos_orchestrator.apply_fault(
            "network_latency",
            "order-service",
            params={"latency_ms": 50000}
        )

    # Negative / zero latency
    with pytest.raises(ValueError):
        chaos_orchestrator.apply_fault(
            "network_latency",
            "order-service",
            params={"latency_ms": 0}
        )

def test_rabbitmq_backlog_messages_guard(monkeypatch):
    # Exceeds max 100000 messages
    with pytest.raises(ValueError):
        chaos_orchestrator.apply_fault(
            "rabbitmq_backlog",
            "rabbitmq",
            params={"messages": 999999}
        )

    # Invalid non-integer
    with pytest.raises(ValueError):
        chaos_orchestrator.apply_fault(
            "rabbitmq_backlog",
            "rabbitmq",
            params={"messages": "ten_thousand"}
        )
