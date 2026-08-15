import sys
import os
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_schema import UnifiedMasterDataset, IncidentEvent
from pydantic import ValidationError

def test_frozen_fixture_contract():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "unified_master_dataset_sample.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dataset = UnifiedMasterDataset(**data)
    assert len(dataset.incidents) == 1
    inc = dataset.incidents[0]
    assert inc.incident_event.incident_id == "auth-service_1"
    assert inc.telemetry_evidence.log_samples[0].trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

def test_live_master_dataset_contract_if_exists():
    live_path = os.path.join(os.path.dirname(__file__), "..", "frontend_data", "unified_master_dataset.json")
    if os.path.exists(live_path):
        with open(live_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        dataset = UnifiedMasterDataset(**data)
        assert isinstance(dataset.incidents, list)
