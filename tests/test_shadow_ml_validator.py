import os
import json
import pytest
from unittest.mock import patch, MagicMock
from shadow_ml_validator import (
    SEVERITY_THRESHOLDS,
    derive_ground_truth_severity,
    validate_prediction,
    run_shadow_validation,
    load_shadow_ground_truth
)

def test_severity_thresholds_contract():
    assert SEVERITY_THRESHOLDS == {
        "CRITICAL": 1.00,
        "HIGH":     0.95,
        "MEDIUM":   0.85,
        "LOW":      0.70,
    }

def test_derive_ground_truth_severity():
    assert derive_ground_truth_severity({"slo_violated": True}) == "CRITICAL"
    assert derive_ground_truth_severity({"service_restarted": True}) == "CRITICAL"
    assert derive_ground_truth_severity({"cascade_failures": 2}) == "HIGH"
    assert derive_ground_truth_severity({"slo_violated": False, "cascade_failures": 0}) == "LOW"

def test_validate_prediction_exact_match():
    gt = {"slo_violated": True, "status": "ok"}
    inc = {"severity": "CRITICAL"}
    res = validate_prediction(inc, gt)
    assert res["status"] == "validated"
    assert res["safe"] is True

def test_validate_prediction_mismatch():
    gt = {"slo_violated": True, "status": "ok"}
    inc = {"severity": "LOW"}
    res = validate_prediction(inc, gt)
    assert res["status"] == "under_prediction"
    assert res["safe"] is False

def test_shadow_validation_gate_pass_and_history_truncation(tmp_path, monkeypatch):
    telemetry_file = tmp_path / "shadow_default_raw_telemetry.json"
    telemetry_file.write_text(json.dumps({"containers": []}))

    report_file = tmp_path / "shadow_ml_validation_report.json"
    history_file = tmp_path / "shadow_validation_history.json"

    # Seed history with 35 runs to test 30-run truncation
    old_history = [{"timestamp": f"2026-01-01T00:00:{i:02d}Z", "overall_safe": 0.90, "gate_passed": True} for i in range(35)]
    history_file.write_text(json.dumps(old_history))

    monkeypatch.setattr("shadow_ml_validator.SHADOW_TELEMETRY_PATH", str(telemetry_file))
    monkeypatch.setattr("shadow_ml_validator.VALIDATION_REPORT_PATH", str(report_file))
    monkeypatch.setattr("shadow_ml_validator.HISTORY_SCORES_PATH", str(history_file))

    mock_incidents = [
        {"incident_id": "inc-1", "severity": "CRITICAL", "scenario_id": "scen-1"}
    ]
    monkeypatch.setattr("shadow_ml_validator.process_telemetry_batch", lambda path, sandbox_mode: mock_incidents)
    monkeypatch.setattr("shadow_ml_validator.load_shadow_ground_truth", lambda scen_id: {"slo_violated": True, "status": "ok"})

    gate_passed = run_shadow_validation()
    assert gate_passed is True

    report = json.loads(report_file.read_text())
    assert report["overall_safe"] == 1.0
    assert report["promotion_gate"] is True
    assert "CRITICAL" in report["per_severity"]
    assert report["per_severity"]["CRITICAL"]["ratio"] == 1.0
    assert report["per_severity"]["CRITICAL"]["passed"] is True
    assert report["delta_from_last"] == pytest.approx(0.10)

    saved_history = json.loads(history_file.read_text())
    assert len(saved_history) == 30

def test_shadow_validation_gate_fails_when_critical_below_threshold(tmp_path, monkeypatch):
    telemetry_file = tmp_path / "shadow_default_raw_telemetry.json"
    telemetry_file.write_text(json.dumps({"containers": []}))

    report_file = tmp_path / "shadow_ml_validation_report.json"
    history_file = tmp_path / "shadow_validation_history.json"

    monkeypatch.setattr("shadow_ml_validator.SHADOW_TELEMETRY_PATH", str(telemetry_file))
    monkeypatch.setattr("shadow_ml_validator.VALIDATION_REPORT_PATH", str(report_file))
    monkeypatch.setattr("shadow_ml_validator.HISTORY_SCORES_PATH", str(history_file))

    mock_incidents = [
        {"incident_id": "inc-1", "severity": "LOW", "scenario_id": "scen-1"} # under-prediction for CRITICAL ground truth
    ]
    monkeypatch.setattr("shadow_ml_validator.process_telemetry_batch", lambda path, sandbox_mode: mock_incidents)
    monkeypatch.setattr("shadow_ml_validator.load_shadow_ground_truth", lambda scen_id: {"slo_violated": True, "status": "ok"})

    gate_passed = run_shadow_validation()
    assert gate_passed is False

    report = json.loads(report_file.read_text())
    assert report["promotion_gate"] is False
    assert report["per_severity"]["LOW"]["passed"] is False
