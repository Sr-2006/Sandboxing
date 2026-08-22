import pytest
import os
from unittest.mock import MagicMock

os.environ["CHAOS_TARGET_NAMESPACE"] = "shadow"
import chaos_orchestrator
from chaos_orchestrator import get_container, validate_namespace_safety, AUDIT_LOG_PATH
from utils import read_json_file


class MockContainer:
    def __init__(self, name, labels=None):
        self.name = name
        self.labels = labels or {}


class TestNamespaceIsolation:
    def test_shadow_prefixes_target(self, monkeypatch):
        monkeypatch.setattr(chaos_orchestrator, "TARGET_NAMESPACE", "shadow")
        mock_c = MagicMock()
        mock_c.name = "shadow-api-gateway"
        mock_c.labels = {"ara.topology.sandbox": "shadow"}
        
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = lambda x: mock_c if x == "shadow-api-gateway" else None
        monkeypatch.setattr(chaos_orchestrator, "client", mock_client)

        c = get_container("api-gateway")
        assert c.name == "shadow-api-gateway"

    def test_production_blocks_shadow_target(self, monkeypatch):
        monkeypatch.setattr(chaos_orchestrator, "TARGET_NAMESPACE", "production")
        mock_client = MagicMock()
        monkeypatch.setattr(chaos_orchestrator, "client", mock_client)
        
        with pytest.raises(ValueError, match="Production namespace cannot target shadow"):
            get_container("shadow-api-gateway")

    def test_label_mismatch_blocks_fault(self, monkeypatch):
        monkeypatch.setattr(chaos_orchestrator, "TARGET_NAMESPACE", "shadow")
        bad = MockContainer("shadow-api-gateway", {"ara.topology.sandbox": "production"})
        with pytest.raises(RuntimeError, match="NAMESPACE CONTAMINATION BLOCKED"):
            validate_namespace_safety(bad)

    def test_audit_log_written(self):
        log = read_json_file(AUDIT_LOG_PATH, [])
        assert any(e["action"] == "orchestrator_startup" for e in log)
