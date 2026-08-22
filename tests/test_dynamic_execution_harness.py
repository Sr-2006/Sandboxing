import os
import json
import pytest
from unittest.mock import MagicMock, patch
from utils import project_path, read_json_file
from dynamic_execution_harness import (
    process_single_incident,
    run_harness,
    OUTCOMES_PATH
)

SAMPLES_DIR = project_path("tests", "fixtures", "tri_debate_samples")

def test_harness_enforces_shadow_target_namespace():
    assert os.environ.get("CHAOS_TARGET_NAMESPACE") == "shadow"

def test_safety_violation_blocks_execution_without_docker_calls():
    case_22_path = os.path.join(SAMPLES_DIR, "case_22_storage_corruption_nuclear.json")
    incident = read_json_file(case_22_path, {})
    assert incident["safety_violation"] is True

    with patch("chaos_orchestrator.get_container") as mock_get_container:
        outcome = process_single_incident(incident)
        assert outcome["gate_decision"] == "BLOCKED_SAFETY_VIOLATION"
        assert outcome["fault_cleared"] is False
        assert mock_get_container.call_count == 0

def test_unmapped_action_blocks_execution_without_docker_calls():
    case_09_path = os.path.join(SAMPLES_DIR, "case_09_unknown_issue.json")
    incident = read_json_file(case_09_path, {})

    with patch("chaos_orchestrator.get_container") as mock_get_container:
        outcome = process_single_incident(incident)
        assert outcome["gate_decision"] == "BLOCKED_UNMAPPED"
        assert outcome["fault_cleared"] is False
        assert mock_get_container.call_count == 0

def test_mapped_action_executes_against_shadow_container(tmp_path, monkeypatch):
    case_11_path = os.path.join(SAMPLES_DIR, "case_11_pg_connection_exhaustion.json")
    incident = read_json_file(case_11_path, {})

    mock_container = MagicMock()
    mock_container.name = "shadow-postgres-db"
    mock_container.labels = {"ara.topology.sandbox": "shadow"}

    with patch("chaos_orchestrator.get_container", return_value=mock_container) as mock_get_c, \
         patch("chaos_orchestrator.validate_namespace_safety") as mock_val_safety, \
         patch("dynamic_execution_harness.record_remediation_outcome") as mock_rec_outcome:

        outcome = process_single_incident(incident)

        assert outcome["gate_decision"] == "EXECUTED"
        assert outcome["fault_cleared"] is True
        assert mock_get_c.call_count == 1
        assert mock_val_safety.call_count == 1
        assert mock_rec_outcome.call_count == 1

def test_batch_execution_fault_tolerance(tmp_path):
    outcomes_file = str(tmp_path / "dynamic_execution_outcomes.json")

    mock_container = MagicMock()
    mock_container.name = "shadow-auth-service"
    mock_container.labels = {"ara.topology.sandbox": "shadow"}

    with patch("chaos_orchestrator.get_container", return_value=mock_container), \
         patch("chaos_orchestrator.validate_namespace_safety"), \
         patch("dynamic_execution_harness.record_remediation_outcome"):

        outcomes = run_harness(input_dir=SAMPLES_DIR, outcomes_file=outcomes_file)

        assert len(outcomes) >= 3
        decisions = [o["gate_decision"] for o in outcomes]
        assert "BLOCKED_SAFETY_VIOLATION" in decisions
        assert "BLOCKED_UNMAPPED" in decisions
        assert "EXECUTED" in decisions

        saved = read_json_file(outcomes_file, [])
        assert len(saved) == len(outcomes)
