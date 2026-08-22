import os
import json
import re
from utils import project_path, read_json_file

# Load controlled action vocabulary at module import time
VOCABULARY_PATH = project_path("frontend_data", "action_vocabulary.json")

def load_vocabulary() -> dict:
    if os.path.exists(VOCABULARY_PATH):
        return read_json_file(VOCABULARY_PATH, {})
    return {
        "restart_service": {"docker_op": "restart", "keywords": ["restart", "reboot service", "cycle the"]},
        "reset_config_param": {"docker_op": "exec_config_patch", "keywords": ["set max_connections", "adjust", "reduce", "reset connection pool", "reset limit", "reset max_connections"]},
        "clear_cache": {"docker_op": "exec_flush", "keywords": ["clear cache", "flush", "evict"]},
        "network_isolate": {"docker_op": "network_partition", "keywords": ["drain", "cordon", "isolate", "quarantine"]},
        "scale_resource": {"docker_op": "update_resources", "keywords": ["scale", "increase memory", "increase cpu"]},
        "rotate_cert": {"docker_op": "exec_cert_rotate", "keywords": ["renew cert", "rotate tls", "reissue certificate"]},
        "noop_monitor": {"docker_op": "noop", "keywords": ["monitor", "review logs", "verify", "check"]}
    }

VOCABULARY = load_vocabulary()

def extract_target_service(problem_text: str) -> str:
    if not problem_text:
        return "unknown"
    match = re.search(r"Target Service:\s*[`'\"]?([a-zA-Z0-9_\-]+)[`'\"]?", problem_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown"

# TODO: Upgrade to embedding similarity using phase2_vector_memory.embedding_model

def adapt_action_command(command_str: str, target_service: str) -> dict:
    """
    Translates a single free-text action command string into a structured action tuple.
    Uses deterministic keyword containment matching in order of vocabulary keys.
    """
    if not command_str:
        return {
            "raw_command": "",
            "intent": "UNMAPPED_ACTION",
            "docker_op": "none",
            "target": target_service,
            "mapped": False,
            "params": {}
        }

    cmd_lower = command_str.lower()

    for intent, spec in VOCABULARY.items():
        keywords = spec.get("keywords", [])
        for kw in keywords:
            if kw.lower() in cmd_lower:
                return {
                    "raw_command": command_str,
                    "intent": intent,
                    "docker_op": spec.get("docker_op", "noop"),
                    "target": target_service,
                    "mapped": True,
                    "params": {"matched_keyword": kw}
                }

    return {
        "raw_command": command_str,
        "intent": "UNMAPPED_ACTION",
        "docker_op": "none",
        "target": target_service,
        "mapped": False,
        "params": {}
    }

def adapt_action_commands(incident: dict) -> list:
    """
    Translates all action_commands in a Tri-Debate incident dictionary.
    """
    problem = incident.get("problem", "")
    target_service = extract_target_service(problem)
    commands = incident.get("action_commands", [])

    results = []
    for cmd in commands:
        mapped = adapt_action_command(cmd, target_service)
        results.append(mapped)
    return results
