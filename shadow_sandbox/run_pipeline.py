#!/usr/bin/env python3
"""
shadow_sandbox/run_pipeline.py

Pipeline Orchestrator for Shadow Sandboxing Subsystem.
Sequences Layer 2 (faults/), Layer 3 (remediation/), and Layer 4 (reports/) for incident processing.
Supports Batch Mode (one pass over a directory) and Watch Mode (continuous directory monitoring).
"""

import os
import sys
import time
import json
import glob
import argparse
from typing import Dict, Any, Optional, Set

from shadow_sandbox.faults.fault_agent import FaultSelectionAgent
from shadow_sandbox.faults.fault_injector import recover_all, log_fault_event
from shadow_sandbox.remediation.execution_harness import ExecutionHarness
from shadow_sandbox.reports.report_generator import generate_report


def process_incident(incident_file: str, settle_wait_s: float = 10.0) -> Optional[str]:
    """
    Processes a single incident JSON file through the 4-layer shadow sandboxing pipeline:
    1. Reads incident JSON.
    2. Calls fault_agent to infer target & fault primitive.
       - If no suitable fault primitive -> writes report SKIPPED_NO_SUITABLE_FAULT and returns.
    3. Recovers baseline -> applies fault -> logs fault history event.
    4. Runs Layer 3 ExecutionHarness (fixes fault, verifies state, captures outcome).
    5. Recovers target baseline state after run.
    6. Writes outcome record to Layer 4 report generator (shadow_sandbox/reports/).
       - A BLOCKED_* outcome never halts the pipeline loop — report is written and processing continues.
    
    Returns the path to the generated report JSON file.
    """
    if not os.path.exists(incident_file):
        print(f"[ORCHESTRATOR] File not found: {incident_file}")
        return None

    with open(incident_file, "r", encoding="utf-8") as f:
        incident = json.load(f)

    incident_id = incident.get("incident_id", os.path.splitext(os.path.basename(incident_file))[0])
    problem_text = incident.get("problem", "")
    rca_text = incident.get("root_cause_analysis", {}).get("summary", "")

    agent = FaultSelectionAgent()
    target = agent.extract_target_service(problem_text)
    primitive, params = agent.infer_fault_primitive(problem_text, rca_text, target)

    # 1. Fail-closed check for non-reproducible / unsuitable fault primitive
    if primitive is None:
        skipped_outcome = {
            "incident_id": incident_id,
            "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gate_decision": "SKIPPED_NO_SUITABLE_FAULT",
            "human_intervention_required": True,
            "message": f"No suitable fault primitive could be inferred for incident '{incident_id}'. Fault injection skipped.",
            "before_state": None,
            "agent_proposal": None,
            "guardrail_result": None,
            "execution_result": None,
            "after_state": None,
            "fault_cleared": None,
            "performance": {
                "safety_check_time_s": 0.0,
                "agent_proposal_time_s": None,
                "guardrail_check_time_s": None,
                "execution_time_s": None,
                "settle_wait_time_s": None,
                "state_recheck_time_s": None,
                "total_pipeline_time_s": 0.0
            }
        }
        report_path = generate_report(skipped_outcome)
        print(f"[ORCHESTRATOR] [{incident_id}] Skipped (no suitable fault primitive). Report written: {report_path}")
        return report_path

    # 2. Recover baseline state first -> Apply Fault -> Log fault event
    try:
        print(f"[ORCHESTRATOR] [{incident_id}] Applying fault primitive '{primitive}' on '{target}'...")
        recover_all(target)
        before_state = agent.execute_fault_primitive(target, primitive, params)
        log_fault_event(
            incident_id=incident_id,
            fault_type=primitive,
            target=target,
            parameters=params,
            before_state=before_state,
            active=True
        )
    except Exception as e:
        print(f"[ORCHESTRATOR] [{incident_id}] Warning/Notice during fault application: {e}")

    # 3. Run Layer 3 Execution Harness
    print(f"[ORCHESTRATOR] [{incident_id}] Running Layer 3 Execution Harness...")
    harness = ExecutionHarness(settle_wait_s=settle_wait_s)
    outcome = harness.run(incident_file)

    # 4. Clean up / Recover baseline after harness run
    try:
        recover_all(target)
    except Exception as e:
        print(f"[ORCHESTRATOR] [{incident_id}] Cleanup recovery notice: {e}")

    # 5. Write outcome record via Layer 4 Report Generator
    report_path = generate_report(outcome)
    decision = outcome.get("gate_decision", "UNKNOWN")
    print(f"[ORCHESTRATOR] [{incident_id}] Processed ({decision}). Report written: {report_path}")

    return report_path


def run_batch_mode(input_dir: str, settle_wait_s: float = 10.0):
    """
    Batch Mode: Loops once over every fix .json file in input_dir and exits when complete.
    """
    pattern = os.path.join(input_dir, "*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"[ORCHESTRATOR] No fix JSON files found matching pattern '{pattern}'.")
        return

    print(f"[ORCHESTRATOR] Starting Batch Mode run over {len(files)} incident file(s)...")
    for idx, filepath in enumerate(files, 1):
        print(f"\n--- Processing Incident {idx}/{len(files)}: {os.path.basename(filepath)} ---")
        process_incident(filepath, settle_wait_s=settle_wait_s)

    print(f"\n[ORCHESTRATOR] Batch Mode run completed successfully.")


def run_watch_mode(input_dir: str, poll_interval_s: float = 2.0, settle_wait_s: float = 10.0):
    """
    Watch Mode: Continuously monitors input_dir for new fix .json files and processes them automatically.
    """
    print(f"[ORCHESTRATOR] Starting Watch Mode monitoring '{input_dir}' (polling every {poll_interval_s}s)...")
    processed_files: Set[str] = set()

    pattern = os.path.join(input_dir, "*.json")
    
    try:
        while True:
            current_files = set(glob.glob(pattern))
            new_files = sorted(list(current_files - processed_files))

            for filepath in new_files:
                print(f"\n[WATCH] New incident detected: {os.path.basename(filepath)}")
                process_incident(filepath, settle_wait_s=settle_wait_s)
                processed_files.add(filepath)

            time.sleep(poll_interval_s)
    except KeyboardInterrupt:
        print("\n[ORCHESTRATOR] Watch Mode stopped by user.")


def main():
    parser = argparse.ArgumentParser(description="Shadow Sandbox Pipeline Orchestrator")
    parser.add_argument("input_path", nargs="?", default=None, help="Path to incident JSON file or input directory")
    parser.add_argument("--mode", choices=["batch", "watch"], default="batch", help="Pipeline execution mode (batch | watch)")
    parser.add_argument("--settle-wait", type=float, default=1.0, help="Settle wait duration in seconds (default: 1.0s for fast testing)")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds for watch mode")

    args = parser.parse_args()

    default_dir = os.path.join(os.path.dirname(__file__), "sample_inputs")
    
    if args.input_path and os.path.isfile(args.input_path):
        process_incident(args.input_path, settle_wait_s=args.settle_wait)
    else:
        target_dir = args.input_path if (args.input_path and os.path.isdir(args.input_path)) else default_dir
        if args.mode == "watch":
            run_watch_mode(target_dir, poll_interval_s=args.poll_interval, settle_wait_s=args.settle_wait)
        else:
            run_batch_mode(target_dir, settle_wait_s=args.settle_wait)


if __name__ == "__main__":
    main()
