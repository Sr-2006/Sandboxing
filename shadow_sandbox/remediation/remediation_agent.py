#!/usr/bin/env python3
"""
shadow_sandbox/remediation/remediation_agent.py

Bounded Remediation Agent for Shadow Sandbox.
Parses fix action_commands text and problem description to produce ONLY typed structured JSON proposals.
Never generates free-text, raw SQL, or raw shell commands directly.
"""

import json
import re
from typing import Dict, Any, List
from shadow_sandbox.remediation.tools import assert_shadow_target

class BoundedRemediationAgent:
    """Agent that translates fix instructions into typed structured JSON proposals."""

    KNOWN_SERVICES = [
        "postgres-db", "redis", "rabbitmq", "api-gateway",
        "auth-service", "order-service", "payment-service"
    ]

    def extract_target_service(self, problem_text: str) -> str:
        """Extracts target service name from problem description text via regex."""
        match = re.search(r"Target Service:\s*`([^`]+)`", problem_text, re.IGNORECASE)
        if match:
            raw_target = match.group(1).strip()
        else:
            raw_target = "api-gateway"
            for svc in self.KNOWN_SERVICES:
                if svc in problem_text.lower():
                    raw_target = svc
                    break

        if not raw_target.startswith("shadow-"):
            raw_target = f"shadow-{raw_target}"

        return assert_shadow_target(raw_target)

    def propose_action(self, problem_text: str, action_commands: List[str]) -> Dict[str, Any]:
        """
        Parses problem description and action commands to output typed proposal JSON.
        Format:
        {
          "tool": "<tool_name>",
          "target": "shadow-<target_service>",
          "parameters": { ... },
          "reasoning": "..."
        }
        """
        if not action_commands:
            return {
                "tool": None,
                "unmapped": True,
                "reason": "Empty action commands provided in fix JSON"
            }

        target = self.extract_target_service(problem_text)
        commands_str = " ".join(action_commands).lower()
        combined_text = f"{problem_text} {commands_str}".lower()

        # 1. Postgres Connection / Config tuning
        if "postgres" in target or "postgres" in combined_text or "connection pool" in commands_str:
            val = 200
            num_match = re.search(r"(\d+)", commands_str)
            if num_match:
                extracted_val = int(num_match.group(1))
                if 20 <= extracted_val <= 500:
                    val = extracted_val

            return {
                "tool": "run_query",
                "target": "shadow-postgres-db",
                "parameters": {
                    "statement_type": "alter_system_set",
                    "setting": "max_connections",
                    "value": val
                },
                "reasoning": f"Fix instructs adjusting max_connections to {val}; resolving database connection pool saturation."
            }

        # 2. Redis Eviction Policy tuning
        elif "redis" in target or "redis" in combined_text or "eviction" in commands_str:
            policy = "volatile-lru"
            if "allkeys-lru" in combined_text:
                policy = "allkeys-lru"
            return {
                "tool": "run_config_command",
                "target": "shadow-redis",
                "parameters": {
                    "config_key": "maxmemory-policy",
                    "value": policy
                },
                "reasoning": f"Fix instructs setting maxmemory-policy to {policy} to prevent OOM errors on key insertion."
            }

        # 3. RabbitMQ Consumer Scaling
        elif "rabbitmq" in target or "rabbitmq" in combined_text or "consumer" in commands_str:
            count = 5
            num_match = re.search(r"(\d+)", commands_str)
            if num_match:
                extracted_val = int(num_match.group(1))
                if 1 <= extracted_val <= 20:
                    count = extracted_val

            return {
                "tool": "scale_replicas",
                "target": "shadow-rabbitmq",
                "parameters": {
                    "operation": "scale_consumer_count",
                    "value": count
                },
                "reasoning": f"Fix instructs scaling consumer count to {count} to drain message queue backlog."
            }

        # 4. Restart service fallback
        elif "restart" in commands_str or "rolling restart" in commands_str:
            return {
                "tool": "restart_service",
                "target": target,
                "parameters": {},
                "reasoning": f"Fix instructs restarting service {target} to clear transient state error."
            }

        # 5. Unmapped action
        return {
            "tool": None,
            "unmapped": True,
            "reason": f"No action mapping recognized for commands: {action_commands}"
        }
