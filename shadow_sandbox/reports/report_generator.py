#!/usr/bin/env python3
"""
shadow_sandbox/reports/report_generator.py

Layer 4: Write-only outcome record generator for shadow sandboxing runs.
Assembles and writes outcome records to shadow_sandbox/reports/<incident_id>_<timestamp>.json.
No aggregation, no dashboarding, no auto-reading back.
"""

import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

REPORTS_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_report(outcome: Dict[str, Any], reports_dir: Optional[str] = None) -> str:
    """
    Takes an outcome record dictionary produced by execution_harness.py (Layer 3),
    formats it according to Section 5 specifications, and writes it to a timestamped JSON file.
    
    Returns the absolute path of the generated report file.
    """
    target_dir = reports_dir or REPORTS_DIR
    os.makedirs(target_dir, exist_ok=True)

    incident_id = outcome.get("incident_id", "unknown_incident")
    
    # Generate timestamp string for filename: YYYYMMDD_HHMMSS
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
    
    # Use run_timestamp if present in outcome, else format ISO timestamp
    run_timestamp = outcome.get("run_timestamp") or now_utc.isoformat()
    
    gate_decision = outcome.get("gate_decision", "UNKNOWN")
    is_blocked = gate_decision.startswith("BLOCKED_")
    
    # Determine human_intervention_required and message
    if is_blocked:
        human_intervention_required = outcome.get("human_intervention_required", True)
        message = outcome.get("message")
        if not message:
            if gate_decision == "BLOCKED_SAFETY_VIOLATION":
                message = "This incident's proposed fix was flagged as a safety violation and was not executed. Human review required before any further action."
            elif gate_decision == "BLOCKED_GUARDRAIL":
                message = "This incident's proposed fix violated guardrail parameters/bounds and was not executed. Human review required."
            elif gate_decision == "BLOCKED_UNMAPPED":
                message = "This incident's action commands could not be mapped to a valid tool proposal. Human review required."
            else:
                message = f"This incident was blocked ({gate_decision}). Human review required."
    else:
        human_intervention_required = False
        message = None

    # Performance per-stage timing block
    perf_raw = outcome.get("performance", {})
    if is_blocked:
        performance = {
            "safety_check_time_s": perf_raw.get("safety_check_time_s", 0.0),
            "agent_proposal_time_s": perf_raw.get("agent_proposal_time_s"),
            "guardrail_check_time_s": perf_raw.get("guardrail_check_time_s"),
            "execution_time_s": perf_raw.get("execution_time_s"),
            "settle_wait_time_s": perf_raw.get("settle_wait_time_s"),
            "state_recheck_time_s": perf_raw.get("state_recheck_time_s"),
            "total_pipeline_time_s": perf_raw.get("total_pipeline_time_s", 0.0)
        }
    else:
        performance = {
            "safety_check_time_s": perf_raw.get("safety_check_time_s", 0.0),
            "agent_proposal_time_s": perf_raw.get("agent_proposal_time_s", 0.0),
            "guardrail_check_time_s": perf_raw.get("guardrail_check_time_s", 0.0),
            "execution_time_s": perf_raw.get("execution_time_s", 0.0),
            "settle_wait_time_s": perf_raw.get("settle_wait_time_s", 0.0),
            "state_recheck_time_s": perf_raw.get("state_recheck_time_s", 0.0),
            "total_pipeline_time_s": perf_raw.get("total_pipeline_time_s", 0.0)
        }

    # Format record matching exact Section 5 spec
    record = {
        "incident_id": incident_id,
        "run_timestamp": run_timestamp,
        "gate_decision": gate_decision,
        "human_intervention_required": human_intervention_required,
        "message": message,
        "before_state": outcome.get("before_state") if (not is_blocked or outcome.get("before_state")) else None,
        "agent_proposal": outcome.get("agent_proposal") if not is_blocked else None,
        "guardrail_result": outcome.get("guardrail_result") if not is_blocked else None,
        "execution_result": outcome.get("execution_result") if not is_blocked else None,
        "after_state": outcome.get("after_state") if not is_blocked else None,
        "fault_cleared": outcome.get("fault_cleared") if not is_blocked else None,
        "performance": performance
    }

    # Unique file naming: shadow_sandbox/reports/<incident_id>_<timestamp>.json
    filename = f"{incident_id}_{timestamp_str}.json"
    filepath = os.path.join(target_dir, filename)
    
    counter = 1
    while os.path.exists(filepath):
        filename = f"{incident_id}_{timestamp_str}_{counter}.json"
        filepath = os.path.join(target_dir, filename)
        counter += 1

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    return filepath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m shadow_sandbox.reports.report_generator <fix_json_path>")
        sys.exit(1)

    fix_path = sys.argv[1]
    
    # Import Layer 3 ExecutionHarness to obtain real outcome record
    from shadow_sandbox.remediation.execution_harness import ExecutionHarness
    
    harness = ExecutionHarness(settle_wait_s=1.0)
    outcome = harness.run(fix_path)
    
    report_file = generate_report(outcome)
    
    print(f"Generated Report: {report_file}")
    with open(report_file, "r", encoding="utf-8") as f:
        print(f.read())
