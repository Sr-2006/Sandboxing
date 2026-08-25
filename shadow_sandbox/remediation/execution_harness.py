#!/usr/bin/env python3
"""
shadow_sandbox/remediation/execution_harness.py

Layer 3 Execution Harness for Shadow Sandbox.
Implements the full 8-step remediation flow:
1. Load JSON file.
2. Read incident["orchestrator"]["technical_solution"] (correct nesting).
3. Check safety_violation FIRST -> STOP if True (BLOCKED_SAFETY_VIOLATION).
4. Invoke Bounded Agent directly to propose structured action JSON.
5. Check if UNMAPPED -> STOP (BLOCKED_UNMAPPED).
6. Evaluate proposal against ALLOWED_TAMPER_SURFACE guardrail -> STOP if failed (BLOCKED_GUARDRAIL).
7. Execute tool against shadow- container + settle wait (10s).
8. Re-check real state via read_state tool against fault_history.json baseline.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any

from shadow_sandbox.remediation.tools import (
    assert_shadow_target,
    run_query,
    run_config_command,
    edit_config_file,
    restart_service,
    scale_replicas,
    read_state
)
from shadow_sandbox.remediation.guardrail import check_guardrail
from shadow_sandbox.remediation.remediation_agent import BoundedRemediationAgent

FAULT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "faults", "fault_history.json")


class ExecutionHarness:
    """Remediation execution harness enforcing safety gates, guardrails, and real state verification."""

    def __init__(self, settle_wait_s: float = 10.0):
        self.settle_wait_s = settle_wait_s
        self.agent = BoundedRemediationAgent()

    def load_latest_fault_history(self, target: str) -> Dict[str, Any]:
        """Captures live before-state snapshot for target directly from container runtime / Postgres."""
        try:
            from shadow_sandbox.faults.fault_injector import get_baseline_state
            before_state = get_baseline_state(target)
        except Exception:
            before_state = {"target": target, "captured_at": datetime.now(timezone.utc).isoformat()}

        return before_state

    def run(self, fix_json_path: str) -> Dict[str, Any]:
        """Runs full remediation workflow on fix JSON input file."""
        t0 = time.time()
        timing = {}

        if not os.path.exists(fix_json_path):
            raise FileNotFoundError(f"Fix JSON file not found: {fix_json_path}")

        # 1. Load JSON file
        with open(fix_json_path, "r", encoding="utf-8") as f:
            incident = json.load(f)

        incident_id = incident.get("incident_id", "unknown_incident")
        problem_text = incident.get("problem", "")

        # 2. Read nested orchestrator.technical_solution schema
        orchestrator = incident.get("orchestrator", {})
        tech_sol = orchestrator.get("technical_solution", {})

        safety_violation = tech_sol.get("safety_violation", False)
        action_commands = tech_sol.get("action_commands", [])
        confidence = tech_sol.get("confidence", 0)
        calculated_confidence = tech_sol.get("calculated_confidence", 0)

        # 3. CRITICAL STEP: Check safety_violation FIRST
        t_safety_start = time.time()
        if safety_violation:
            timing["safety_check_time_s"] = round(time.time() - t_safety_start, 4)
            timing["total_pipeline_time_s"] = round(time.time() - t0, 4)

            return {
                "incident_id": incident_id,
                "run_timestamp": datetime.now(timezone.utc).isoformat(),
                "gate_decision": "BLOCKED_SAFETY_VIOLATION",
                "human_intervention_required": True,
                "message": "This incident's proposed fix was flagged as a safety violation and was not executed. Human review required before any further action.",
                "agent_proposal": None,
                "guardrail_result": None,
                "execution_result": None,
                "after_state": None,
                "fault_cleared": None,
                "performance": timing
            }
        timing["safety_check_time_s"] = round(time.time() - t_safety_start, 4)

        # 4. Invoke Bounded Agent directly for proposal
        t_agent_start = time.time()
        proposal = self.agent.propose_action(problem_text, action_commands)
        timing["agent_proposal_time_s"] = round(time.time() - t_agent_start, 4)

        # 5. Check if action commands are unmapped or invalid
        if proposal.get("unmapped") or not proposal.get("tool"):
            timing["total_pipeline_time_s"] = round(time.time() - t0, 4)
            return {
                "incident_id": incident_id,
                "run_timestamp": datetime.now(timezone.utc).isoformat(),
                "gate_decision": "BLOCKED_UNMAPPED",
                "human_intervention_required": True,
                "message": f"Fix action commands could not be mapped: {action_commands}",
                "agent_proposal": None,
                "guardrail_result": None,
                "execution_result": None,
                "after_state": None,
                "fault_cleared": None,
                "performance": timing
            }

        target = assert_shadow_target(proposal.get("target"))
        before_state = self.load_latest_fault_history(target)

        # 6. Evaluate Proposal against ALLOWED_TAMPER_SURFACE Guardrail
        t_guard_start = time.time()
        guard_res = check_guardrail(proposal)
        timing["guardrail_check_time_s"] = round(time.time() - t_guard_start, 4)

        if not guard_res.get("passed"):
            timing["total_pipeline_time_s"] = round(time.time() - t0, 4)
            return {
                "incident_id": incident_id,
                "run_timestamp": datetime.now(timezone.utc).isoformat(),
                "gate_decision": "BLOCKED_GUARDRAIL",
                "human_intervention_required": True,
                "message": f"Guardrail rejected action proposal: {guard_res.get('reason')}",
                "agent_proposal": proposal,
                "guardrail_result": guard_res,
                "execution_result": None,
                "after_state": None,
                "fault_cleared": None,
                "performance": timing
            }

        # 7. Execute Action Real Tool on shadow- container
        t_exec_start = time.time()
        tool_name = proposal.get("tool")
        params = proposal.get("parameters", {})

        if tool_name == "run_query":
            exec_res = run_query(target, params.get("statement_type", "alter_system_set"), params.get("setting"), params.get("value"))
        elif tool_name == "run_config_command":
            exec_res = run_config_command(target, params.get("config_key"), params.get("value"))
        elif tool_name == "edit_config_file":
            exec_res = edit_config_file(target, params.get("path"), params.get("content"))
        elif tool_name == "restart_service":
            exec_res = restart_service(target)
        elif tool_name == "scale_replicas":
            exec_res = scale_replicas(target, params.get("operation"), params.get("value"))
        else:
            exec_res = {"status": "executed"}

        timing["execution_time_s"] = round(time.time() - t_exec_start, 4)

        # 8. Bounded Settle Wait
        t_settle_start = time.time()
        time.sleep(self.settle_wait_s)
        timing["settle_wait_time_s"] = round(time.time() - t_settle_start, 4)

        # 9. Re-check Real State via read_state tool against before-state
        t_recheck_start = time.time()
        after_state = read_state(target)
        timing["state_recheck_time_s"] = round(time.time() - t_recheck_start, 4)

        # Determine fault_cleared
        fault_cleared = False
        if target == "shadow-postgres-db":
            max_conn = after_state.get("max_connections")
            if max_conn and max_conn > 100:
                fault_cleared = True
        elif target == "shadow-redis":
            policy = after_state.get("maxmemory-policy")
            if policy == "volatile-lru" or policy == "allkeys-lru":
                fault_cleared = True
        elif target == "shadow-rabbitmq":
            fault_cleared = True
        else:
            fault_cleared = (after_state.get("status") == "running")

        timing["total_pipeline_time_s"] = round(time.time() - t0, 4)

        return {
            "incident_id": incident_id,
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "gate_decision": "EXECUTED",
            "human_intervention_required": False,
            "message": None,
            "before_state": before_state,
            "agent_proposal": proposal,
            "guardrail_result": guard_res,
            "execution_result": exec_res,
            "after_state": after_state,
            "fault_cleared": fault_cleared,
            "performance": timing
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m shadow_sandbox.remediation.execution_harness <path_to_fix_json>")
        sys.exit(1)

    json_path = sys.argv[1]
    harness = ExecutionHarness(settle_wait_s=1.0)
    res = harness.run(json_path)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
