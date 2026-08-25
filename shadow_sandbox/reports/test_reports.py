#!/usr/bin/env python3
"""
shadow_sandbox/reports/test_reports.py

Unit tests for Layer 4 report generator (shadow_sandbox/reports/report_generator.py).
"""

import os
import json
import shutil
import tempfile
import unittest
from shadow_sandbox.reports.report_generator import generate_report


class TestReportGenerator(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_report_executed_case(self):
        outcome = {
            "incident_id": "case_11_pg_connection_exhaustion",
            "run_timestamp": "2026-08-25T10:00:00+00:00",
            "gate_decision": "EXECUTED",
            "human_intervention_required": False,
            "message": None,
            "before_state": {
                "target": "shadow-postgres-db",
                "held_connections_count": 100
            },
            "agent_proposal": {
                "tool": "run_query",
                "target": "shadow-postgres-db",
                "parameters": {"statement_type": "alter_system_set", "setting": "max_connections", "value": 200},
                "reasoning": "Fix max connections pool exhaustion."
            },
            "guardrail_result": {"passed": True, "reason": None},
            "execution_result": {
                "target": "shadow-postgres-db",
                "tool": "run_query",
                "sql": "ALTER SYSTEM SET max_connections = 200;",
                "exit_code": 0
            },
            "after_state": {
                "max_connections": 200,
                "active_connections": 1
            },
            "fault_cleared": True,
            "performance": {
                "safety_check_time_s": 0.0,
                "agent_proposal_time_s": 0.0002,
                "guardrail_check_time_s": 0.0,
                "execution_time_s": 0.65,
                "settle_wait_time_s": 1.0,
                "state_recheck_time_s": 0.17,
                "total_pipeline_time_s": 1.82
            }
        }

        report_path = generate_report(outcome, reports_dir=self.test_dir)
        self.assertTrue(os.path.exists(report_path))

        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["incident_id"], "case_11_pg_connection_exhaustion")
        self.assertEqual(data["gate_decision"], "EXECUTED")
        self.assertFalse(data["human_intervention_required"])
        self.assertIsNone(data["message"])
        self.assertTrue(data["fault_cleared"])
        self.assertIsNotNone(data["agent_proposal"])
        self.assertIsNotNone(data["execution_result"])
        self.assertEqual(data["performance"]["execution_time_s"], 0.65)

    def test_generate_report_blocked_case(self):
        outcome = {
            "incident_id": "case_22_storage_corruption_nuclear",
            "run_timestamp": "2026-08-25T10:00:00+00:00",
            "gate_decision": "BLOCKED_SAFETY_VIOLATION",
            "human_intervention_required": True,
            "message": "This incident's proposed fix was flagged as a safety violation and was not executed. Human review required before any further action.",
            "agent_proposal": None,
            "guardrail_result": None,
            "execution_result": None,
            "after_state": None,
            "fault_cleared": None,
            "performance": {
                "safety_check_time_s": 0.0001,
                "total_pipeline_time_s": 0.0001
            }
        }

        report_path = generate_report(outcome, reports_dir=self.test_dir)
        self.assertTrue(os.path.exists(report_path))

        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["incident_id"], "case_22_storage_corruption_nuclear")
        self.assertEqual(data["gate_decision"], "BLOCKED_SAFETY_VIOLATION")
        self.assertTrue(data["human_intervention_required"])
        self.assertIsNotNone(data["message"])
        self.assertIsNone(data["agent_proposal"])
        self.assertIsNone(data["guardrail_result"])
        self.assertIsNone(data["execution_result"])
        self.assertIsNone(data["after_state"])
        self.assertIsNone(data["fault_cleared"])
        self.assertIsNone(data["performance"]["agent_proposal_time_s"])
        self.assertIsNone(data["performance"]["execution_time_s"])

    def test_no_overwrite(self):
        outcome = {
            "incident_id": "case_11_pg_connection_exhaustion",
            "gate_decision": "EXECUTED",
            "performance": {}
        }

        path1 = generate_report(outcome, reports_dir=self.test_dir)
        path2 = generate_report(outcome, reports_dir=self.test_dir)

        self.assertNotEqual(path1, path2)
        self.assertTrue(os.path.exists(path1))
        self.assertTrue(os.path.exists(path2))


if __name__ == "__main__":
    unittest.main()
