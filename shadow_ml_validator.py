#!/usr/bin/env python3
import os
import json
import sys
from datetime import datetime, timezone, timedelta
from utils import get_logger, project_path, atomic_write_json, read_json_file
from phase1_processor import process_telemetry_batch
from phase2_vector_memory import query_similar_incident

logger = get_logger("shadow_ml_validator")

SHADOW_RUN_ID = os.environ.get("SHADOW_RUN_ID", "default")
SHADOW_TELEMETRY_PATH = project_path("frontend_data", f"shadow_{SHADOW_RUN_ID}_raw_telemetry.json")
SHADOW_CHAOS_HISTORY_PATH = project_path("frontend_data", "shadow_chaos_history.json")
VALIDATION_REPORT_PATH = project_path("frontend_data", "shadow_ml_validation_report.json")
HISTORY_SCORES_PATH = project_path("frontend_data", "shadow_validation_history.json")

SEVERITY_THRESHOLDS = {
    "CRITICAL": 1.00,
    "HIGH":     0.95,
    "MEDIUM":   0.85,
    "LOW":      0.70,
}

def load_shadow_ground_truth(scenario_id: str) -> dict:
    history = read_json_file(SHADOW_CHAOS_HISTORY_PATH, [])
    for ev in history:
        if ev.get("scenario_id") == scenario_id:
            return {
                "service_restarted": False,
                "cascade_failures": 0,
                "slo_violated": ev.get("duration_s", 0) > 5.0,
                "recovery_time_ms": float(ev.get("duration_s", 0)) * 1000,
                "status": "ok"
            }
    return {"status": "no_ground_truth"}

def derive_ground_truth_severity(gt: dict) -> str:
    if gt.get("slo_violated") or gt.get("service_restarted"):
        return "CRITICAL"
    if gt.get("cascade_failures", 0) > 0:
        return "HIGH"
    return "LOW"

def validate_prediction(incident: dict, ground_truth: dict) -> dict:
    if ground_truth.get("status") == "no_ground_truth":
        return {"status": "no_ground_truth", "safe": False, "drift": 1.0}

    predicted = incident.get("severity")
    if not predicted and isinstance(incident.get("incident_event"), dict):
        predicted = incident["incident_event"].get("severity")
    if not predicted:
        predicted = "LOW"

    gt_sev = derive_ground_truth_severity(ground_truth)
    recovery_ms = ground_truth.get("recovery_time_ms", 999999)
    self_healed = not ground_truth.get("slo_violated") and recovery_ms < 5000

    severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    pred_idx = severity_order.get(predicted, 0)
    gt_idx = severity_order.get(gt_sev, 0)
    diff = abs(pred_idx - gt_idx)

    if diff == 0:
        return {"status": "validated", "safe": True, "drift": 0.1}
    elif diff == 1 and self_healed:
        return {"status": "validated_partial", "safe": True, "drift": 0.3}
    elif predicted == "CRITICAL" and gt_sev in ("LOW", "MEDIUM"):
        return {"status": "over_prediction", "safe": False, "drift": 0.8}
    elif predicted == "LOW" and gt_sev in ("HIGH", "CRITICAL"):
        return {"status": "under_prediction", "safe": False, "drift": 0.9}
    else:
        return {"status": "mismatch", "safe": False, "drift": 0.5}

def run_shadow_validation() -> bool:
    if not os.path.exists(SHADOW_TELEMETRY_PATH) or os.path.getsize(SHADOW_TELEMETRY_PATH) == 0:
        logger.error(f"Shadow telemetry not found: {SHADOW_TELEMETRY_PATH}")
        return False

    incidents = process_telemetry_batch(SHADOW_TELEMETRY_PATH, sandbox_mode=True)
    if not incidents:
        logger.warning("No incidents generated from shadow telemetry.")
        return False

    results = []
    severity_counts = {
        "CRITICAL": {"safe": 0, "total": 0},
        "HIGH":     {"safe": 0, "total": 0},
        "MEDIUM":   {"safe": 0, "total": 0},
        "LOW":      {"safe": 0, "total": 0}
    }

    for inc in incidents:
        scenario_id = inc.get("scenario_id") or inc.get("injected_chaos_context", {}).get("scenario_id", "")
        gt = load_shadow_ground_truth(scenario_id)
        v = validate_prediction(inc, gt)
        
        pred_sev = inc.get("severity") or (inc.get("incident_event", {}).get("severity") if isinstance(inc.get("incident_event"), dict) else "LOW")
        inc_id = inc.get("incident_id") or (inc.get("incident_event", {}).get("incident_id") if isinstance(inc.get("incident_event"), dict) else "unknown")

        results.append({
            "incident_id": inc_id,
            "predicted": pred_sev,
            "ground_truth": derive_ground_truth_severity(gt),
            "validation": v
        })
        sev = pred_sev if pred_sev in severity_counts else "LOW"
        severity_counts[sev]["total"] += 1
        if v["safe"]:
            severity_counts[sev]["safe"] += 1

    per_severity = {}
    gate_passed = True
    for sev, counts in severity_counts.items():
        if counts["total"] > 0:
            ratio = counts["safe"] / counts["total"]
            threshold = SEVERITY_THRESHOLDS[sev]
            passed = ratio >= threshold
            per_severity[sev] = {"ratio": ratio, "threshold": threshold, "passed": passed}
            if not passed:
                gate_passed = False

    overall_safe = (sum(1 for r in results if r["validation"]["safe"]) / len(results)) if results else 0.0

    history = read_json_file(HISTORY_SCORES_PATH, [])
    delta = None
    if history:
        last = history[-1]
        delta = overall_safe - last.get("overall_safe", 0)
        if delta < -0.05:
            logger.warning(f"Regression detected: score dropped by {abs(delta):.1%} from last run.")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_safe": overall_safe,
        "per_severity": per_severity,
        "promotion_gate": gate_passed,
        "total_incidents": len(results),
        "delta_from_last": delta,
        "details": results
    }

    atomic_write_json(VALIDATION_REPORT_PATH, report)

    history.append({"timestamp": report["timestamp"], "overall_safe": overall_safe, "gate_passed": gate_passed})
    if len(history) > 30:
        history = history[-30:]
    atomic_write_json(HISTORY_SCORES_PATH, history)

    logger.info(f"Shadow validation: overall={overall_safe:.2%}, gate={gate_passed}")
    for sev, stats in per_severity.items():
        logger.info(f"  {sev}: {stats['ratio']:.2%} (threshold: {stats['threshold']:.0%}, passed={stats['passed']})")

    return gate_passed

def run_remediation_validation(outcomes_path: str = None) -> bool:
    """
    Reads frontend_data/dynamic_execution_outcomes.json and computes what fraction
    of EXECUTED (non-blocked) incidents had fault_cleared == true.
    Applies the same SEVERITY_THRESHOLDS gate logic, keyed by incident severity
    (pulled from the original incident's problem/severity field), not by prediction accuracy.
    This is remediation-success rate, a distinct metric from the existing severity-prediction accuracy.
    """
    if outcomes_path is None:
        outcomes_path = project_path("frontend_data", "dynamic_execution_outcomes.json")

    outcomes = read_json_file(outcomes_path, [])
    if not outcomes:
        logger.warning(f"No execution outcomes found at '{outcomes_path}'")
        return False

    executed_outcomes = [o for o in outcomes if o.get("gate_decision") == "EXECUTED"]
    if not executed_outcomes:
        logger.warning("No EXECUTED outcomes to validate.")
        return False

    severity_counts = {
        "CRITICAL": {"cleared": 0, "total": 0},
        "HIGH":     {"cleared": 0, "total": 0},
        "MEDIUM":   {"cleared": 0, "total": 0},
        "LOW":      {"cleared": 0, "total": 0}
    }

    for o in executed_outcomes:
        sev = o.get("severity", "LOW")
        if sev not in severity_counts:
            sev = "LOW"
        severity_counts[sev]["total"] += 1
        if o.get("fault_cleared"):
            severity_counts[sev]["cleared"] += 1

    per_severity = {}
    gate_passed = True
    for sev, counts in severity_counts.items():
        if counts["total"] > 0:
            ratio = counts["cleared"] / counts["total"]
            threshold = SEVERITY_THRESHOLDS[sev]
            passed = ratio >= threshold
            per_severity[sev] = {"ratio": ratio, "threshold": threshold, "passed": passed}
            if not passed:
                gate_passed = False

    logger.info(f"Remediation validation: gate={gate_passed}")
    for sev, stats in per_severity.items():
        logger.info(f"  {sev}: {stats['ratio']:.2%} (threshold: {stats['threshold']:.0%}, passed={stats['passed']})")

    return gate_passed

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Shadow ML Validator")
    parser.add_argument("--remediation", action="store_true", help="Run remediation success validation gate")
    args = parser.parse_args()

    if args.remediation:
        gate_passed = run_remediation_validation()
    else:
        gate_passed = run_shadow_validation()
    sys.exit(0 if gate_passed else 1)

