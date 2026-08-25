#!/usr/bin/env python3
"""
shadow_sandbox/test_pipeline.py

Unit tests for shadow_sandbox/run_pipeline.py pipeline orchestrator.
"""

import os
import shutil
import tempfile
import unittest
from shadow_sandbox.run_pipeline import process_incident, run_batch_mode


class TestPipelineOrchestrator(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_process_incident_blocked(self):
        case_path = os.path.join(
            os.path.dirname(__file__), "sample_inputs", "case_22_storage_corruption_nuclear.json"
        )
        report_file = process_incident(case_path, settle_wait_s=0.1)
        self.assertIsNotNone(report_file)
        self.assertTrue(os.path.exists(report_file))

    def test_run_batch_mode(self):
        # Create dummy incident copy in temp directory
        case_22 = os.path.join(
            os.path.dirname(__file__), "sample_inputs", "case_22_storage_corruption_nuclear.json"
        )
        shutil.copy(case_22, os.path.join(self.test_dir, "case_22.json"))

        run_batch_mode(self.test_dir, settle_wait_s=0.1)


if __name__ == "__main__":
    unittest.main()
