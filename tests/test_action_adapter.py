import os
import json
import pytest
from utils import project_path, read_json_file
from action_adapter import adapt_action_commands, adapt_action_command, extract_target_service

SAMPLES_DIR = project_path("tests", "fixtures", "tri_debate_samples")

def test_extract_target_service():
    problem = "Target Service: `postgres-db` - PostgreSQL max connection limit reached"
    assert extract_target_service(problem) == "postgres-db"

    problem_quotes = "Target Service: 'auth-service' - latency issue"
    assert extract_target_service(problem_quotes) == "auth-service"

    problem_no_quotes = "Target Service: payment-service - failed transaction"
    assert extract_target_service(problem_no_quotes) == "payment-service"

def test_case_11_adapter_mapping():
    case_11_path = os.path.join(SAMPLES_DIR, "case_11_pg_connection_exhaustion.json")
    incident = read_json_file(case_11_path, {})
    assert incident.get("incident_id") == "case_11_pg_connection_exhaustion"

    actions = adapt_action_commands(incident)
    assert len(actions) == 1
    action = actions[0]
    assert action["mapped"] is True
    assert action["intent"] == "reset_config_param"
    assert action["docker_op"] == "exec_config_patch"
    assert action["target"] == "postgres-db"

def test_case_05_adapter_mapping():
    case_05_path = os.path.join(SAMPLES_DIR, "case_05_auth_latency.json")
    incident = read_json_file(case_05_path, {})

    actions = adapt_action_commands(incident)
    assert len(actions) == 1
    action = actions[0]
    assert action["mapped"] is True
    assert action["intent"] == "restart_service"
    assert action["docker_op"] == "restart"
    assert action["target"] == "auth-service"

def test_nonsense_command_returns_unmapped():
    case_09_path = os.path.join(SAMPLES_DIR, "case_09_unknown_issue.json")
    incident = read_json_file(case_09_path, {})

    actions = adapt_action_commands(incident)
    assert len(actions) == 1
    action = actions[0]
    assert action["mapped"] is False
    assert action["intent"] == "UNMAPPED_ACTION"
    assert action["docker_op"] == "none"
