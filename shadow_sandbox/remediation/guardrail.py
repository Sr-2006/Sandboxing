#!/usr/bin/env python3
"""
shadow_sandbox/remediation/guardrail.py

Implements ALLOWED_TAMPER_SURFACE guardrail for Layer 3.
Evaluates typed structured proposals from the Bounded Agent against strict
per-service allowlists, numeric bounds, and forbidden keywords.
"""

from typing import Dict, Any, Tuple

ALLOWED_TAMPER_SURFACE = {
    "postgres": {
        "statement_types": {
            "alter_system_set": {
                "allowed_settings": ["max_connections", "shared_buffers", "work_mem", "statement_timeout"],
                "bounds": {
                    "max_connections": {"min": 20, "max": 500}
                }
            },
            "set": {
                "allowed_settings": ["work_mem", "statement_timeout"]
            }
        },
        "forbidden_always": ["drop", "truncate", "delete from", "alter table", "grant", "revoke"]
    },
    "redis": {
        "config_keys": {
            "maxmemory-policy": {
                "allowed_values": ["volatile-lru", "allkeys-lru", "volatile-ttl", "noeviction"]
            },
            "maxmemory": {
                "bounds": {"min": 64, "max": 1024}
            }
        },
        "forbidden_always": ["flushall", "flushdb", "config set requirepass"]
    },
    "rabbitmq": {
        "operations": {
            "scale_consumer_count": {"bounds": {"min": 1, "max": 20}},
            "adjust_prefetch": {"bounds": {"min": 1, "max": 1000}}
        },
        "forbidden_always": ["delete_queue", "delete_vhost", "delete_exchange"]
    }
}


def check_guardrail(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates a structured proposal against ALLOWED_TAMPER_SURFACE.
    Returns {"passed": True, "reason": None} or {"passed": False, "reason": "..."}.
    """
    if not isinstance(proposal, dict):
        return {"passed": False, "reason": "Proposal is not a valid JSON dictionary"}

    tool = proposal.get("tool")
    target = proposal.get("target", "")
    params = proposal.get("parameters", {})

    # Target safety check
    if not target or not target.startswith("shadow-"):
        return {"passed": False, "reason": f"Guardrail rejected non-shadow target '{target}'"}

    # 1. PostgreSQL Guardrail Check
    if "postgres" in target:
        rules = ALLOWED_TAMPER_SURFACE["postgres"]

        # Check forbidden keywords in parameters or setting
        setting = str(params.get("setting", "")).lower()
        for forbidden in rules["forbidden_always"]:
            if forbidden in setting:
                return {"passed": False, "reason": f"Forbidden keyword '{forbidden}' in Postgres proposal"}

        statement_type = params.get("statement_type", "alter_system_set")
        stmt_rules = rules["statement_types"].get(statement_type)
        if not stmt_rules:
            return {"passed": False, "reason": f"Disallowed Postgres statement_type '{statement_type}'"}

        allowed_settings = stmt_rules.get("allowed_settings", [])
        if setting not in allowed_settings:
            return {"passed": False, "reason": f"Setting '{setting}' not in Postgres allowed_settings {allowed_settings}"}

        bounds = stmt_rules.get("bounds", {}).get(setting)
        if bounds:
            try:
                val = int(params.get("value"))
                if val < bounds["min"] or val > bounds["max"]:
                    return {
                        "passed": False,
                        "reason": f"Setting '{setting}' value {val} out of bounds [{bounds['min']}, {bounds['max']}]"
                    }
            except (ValueError, TypeError):
                return {"passed": False, "reason": f"Invalid numeric value for setting '{setting}'"}

        return {"passed": True, "reason": None}

    # 2. Redis Guardrail Check
    elif "redis" in target:
        rules = ALLOWED_TAMPER_SURFACE["redis"]
        config_key = params.get("config_key", params.get("setting", ""))

        for forbidden in rules["forbidden_always"]:
            if forbidden in str(params).lower():
                return {"passed": False, "reason": f"Forbidden keyword '{forbidden}' in Redis proposal"}

        key_rules = rules["config_keys"].get(config_key)
        if not key_rules:
            return {"passed": False, "reason": f"Config key '{config_key}' not in Redis allowed config_keys"}

        if "allowed_values" in key_rules:
            val = str(params.get("value"))
            if val not in key_rules["allowed_values"]:
                return {
                    "passed": False,
                    "reason": f"Value '{val}' for '{config_key}' not in allowed_values {key_rules['allowed_values']}"
                }

        return {"passed": True, "reason": None}

    # 3. RabbitMQ Guardrail Check
    elif "rabbitmq" in target:
        rules = ALLOWED_TAMPER_SURFACE["rabbitmq"]
        op = params.get("operation", "scale_consumer_count")

        for forbidden in rules["forbidden_always"]:
            if forbidden in str(params).lower():
                return {"passed": False, "reason": f"Forbidden operation '{forbidden}' in RabbitMQ proposal"}

        op_rules = rules["operations"].get(op)
        if not op_rules:
            return {"passed": False, "reason": f"Operation '{op}' not allowed for RabbitMQ"}

        bounds = op_rules.get("bounds")
        if bounds:
            try:
                val = int(params.get("value"))
                if val < bounds["min"] or val > bounds["max"]:
                    return {
                        "passed": False,
                        "reason": f"Operation '{op}' value {val} out of bounds [{bounds['min']}, {bounds['max']}]"
                    }
            except (ValueError, TypeError):
                return {"passed": False, "reason": f"Invalid numeric value for RabbitMQ operation '{op}'"}

        return {"passed": True, "reason": None}

    # 4. Standard service restart or generic tool
    elif tool in ["restart_service", "read_state"]:
        return {"passed": True, "reason": None}

    return {"passed": True, "reason": None}
