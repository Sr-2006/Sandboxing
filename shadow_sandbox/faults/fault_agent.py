#!/usr/bin/env python3
"""
shadow_sandbox/faults/fault_agent.py

Fault-Selection Agent for Shadow Sandbox.
Reads diagnostic text from an incident fix JSON, infers target service and fault primitive,
and executes the recover -> apply -> log sequence safely against shadow- containers.
"""

import json
import re
import os
import sys
from typing import Dict, Any, Tuple

from shadow_sandbox.faults.fault_injector import (
    assert_shadow_target,
    get_baseline_state,
    log_fault_event,
    recover_all,
    cpu_throttle,
    memory_limit,
    network_latency,
    restart_container,
    pause_container,
    rabbitmq_backlog,
    exhaust_postgres_connections
)


class FaultSelectionAgent:
    """Agent that infers fault parameters from diagnostic text without static incident-type tables."""

    KNOWN_SERVICES = [
        "postgres-db", "redis", "rabbitmq", "api-gateway",
        "auth-service", "order-service", "payment-service"
    ]

    def extract_target_service(self, problem_text: str) -> str:
        """Extracts target service name from problem description text."""
        # Check explicit markdown code pattern: Target Service: `postgres-db`
        match = re.search(r"Target Service:\s*`([^`]+)`", problem_text, re.IGNORECASE)
        if match:
            raw_target = match.group(1).strip()
        else:
            # Fallback regex search for known service names
            raw_target = "api-gateway"
            for svc in self.KNOWN_SERVICES:
                if svc in problem_text.lower():
                    raw_target = svc
                    break

        # Normalize to shadow- prefix
        if not raw_target.startswith("shadow-"):
            raw_target = f"shadow-{raw_target}"

        return assert_shadow_target(raw_target)

    def infer_fault_primitive(self, problem_text: str, rca_text: str, target: str) -> Tuple[str, Dict[str, Any]]:
        """
        Analyzes diagnostic text to select appropriate generic primitive and parameters.
        Primitives:
        - apply_resource_exhaustion
        - apply_latency
        - apply_process_disruption
        - apply_queue_pressure
        """
        text = f"{problem_text} {rca_text}".lower()

        # 1. Check Connection / DB Exhaustion / Memory Resource Exhaustion
        if "connection" in text and ("exhaust" in text or "limit" in text or "max" in text or "too many" in text):
            return "apply_resource_exhaustion", {"resource_type": "postgres_connections", "connection_count": 100}

        if "memory" in text and ("oom" in text or "eviction" in text or "limit" in text or "noeviction" in text):
            return "apply_resource_exhaustion", {"resource_type": "memory_limit", "limit_mb": 64}

        if "cpu" in text or "throttle" in text or "high cpu" in text:
            return "apply_resource_exhaustion", {"resource_type": "cpu_throttle", "quota_percent": 20}

        # 2. Check Queue Pressure
        if "queue" in text or "backlog" in text or "consumer" in text or "rabbitmq" in text:
            return "apply_queue_pressure", {"backlog_size": 1000}

        # 3. Check Network Latency / Delay / Timeout
        if "latency" in text or "delay" in text or "slow" in text or "network" in text:
            return "apply_latency", {"delay_ms": 500}

        # 4. Process Disruption (Default for lock/crash/corruption)
        if "pause" in text:
            return "apply_process_disruption", {"mode": "pause"}

        return "apply_process_disruption", {"mode": "restart"}

    def execute_fault_primitive(self, target: str, primitive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the concrete fault function behind the generic primitive."""
        target = assert_shadow_target(target)

        if primitive == "apply_resource_exhaustion":
            res_type = params.get("resource_type")
            if res_type == "postgres_connections" or target == "shadow-postgres-db":
                return exhaust_postgres_connections(target, connection_count=params.get("connection_count", 100))
            elif res_type == "memory_limit":
                return memory_limit(target, limit_mb=params.get("limit_mb", 64))
            else:
                return cpu_throttle(target, quota_percent=params.get("quota_percent", 20))

        elif primitive == "apply_queue_pressure":
            return rabbitmq_backlog(target, message_count=params.get("backlog_size", 1000))

        elif primitive == "apply_latency":
            return network_latency(target, latency_ms=params.get("delay_ms", 500))

        elif primitive == "apply_process_disruption":
            mode = params.get("mode", "restart")
            if mode == "pause":
                return pause_container(target)
            return restart_container(target)

        else:
            raise ValueError(f"Unknown fault primitive: {primitive}")

    def run_fault_injection(self, fix_json_path: str) -> Dict[str, Any]:
        """
        Full Layer 2 fault injection pipeline:
        1. Read incident JSON
        2. Infer target service & fault primitive
        3. Recover target to clean baseline
        4. Capture before-state snapshot
        5. Apply fault
        6. Log fault event to fault_history.json
        """
        if not os.path.exists(fix_json_path):
            raise FileNotFoundError(f"Fix input JSON not found: {fix_json_path}")

        with open(fix_json_path, "r", encoding="utf-8") as f:
            incident = json.load(f)

        incident_id = incident.get("incident_id", "unknown_incident")
        problem_text = incident.get("problem", "")
        rca_text = incident.get("root_cause_analysis", {}).get("summary", "")

        # 1. Extract Target Service (Enforces shadow- target safety assertion)
        target = self.extract_target_service(problem_text)

        # 2. Infer Primitive and Parameters
        primitive, params = self.infer_fault_primitive(problem_text, rca_text, target)

        # 3. Recover baseline state first (prevents stacking)
        recovery_info = recover_all(target)

        # 4. Capture Before State
        before_state = get_baseline_state(target)

        # 5. Apply Fault
        fault_result = self.execute_fault_primitive(target, primitive, params)

        # 6. Log to fault_history.json
        log_fault_event(
            incident_id=incident_id,
            fault_type=primitive,
            target=target,
            parameters=params,
            before_state=before_state,
            active=True
        )

        return {
            "incident_id": incident_id,
            "target": target,
            "inferred_primitive": primitive,
            "parameters": params,
            "recovery_before_apply": recovery_info,
            "before_state": before_state,
            "fault_result": fault_result
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m shadow_sandbox.faults.fault_agent <path_to_fix_json>")
        sys.exit(1)

    json_path = sys.argv[1]
    agent = FaultSelectionAgent()
    res = agent.run_fault_injection(json_path)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
