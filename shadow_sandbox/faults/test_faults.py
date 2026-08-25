#!/usr/bin/env python3
"""
shadow_sandbox/faults/test_faults.py

Verification script for Layer 2 (faults/):
1. Verifies safety assertion on non-shadow targets (must raise RuntimeError).
2. Verifies fault selection agent inference on sample incident files.
"""

import os
import unittest

from shadow_sandbox.faults.fault_injector import assert_shadow_target
from shadow_sandbox.faults.fault_agent import FaultSelectionAgent


class TestShadowFaults(unittest.TestCase):

    def test_safety_rule_enforcement(self):
        """Verify that any non-shadow container target raises a RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            assert_shadow_target("postgres-db")
        self.assertIn("SAFETY VIOLATION", str(ctx.exception))

        with self.assertRaises(RuntimeError) as ctx:
            assert_shadow_target("production-api-gateway")
        self.assertIn("SAFETY VIOLATION", str(ctx.exception))

        # Valid shadow target must pass without exception
        self.assertEqual(assert_shadow_target("shadow-postgres-db"), "shadow-postgres-db")

    def test_agent_target_extraction(self):
        """Verify agent extracts and normalizes target container name to shadow- prefix."""
        agent = FaultSelectionAgent()

        target1 = agent.extract_target_service("Target Service: `postgres-db` - Connection exhausted")
        self.assertEqual(target1, "shadow-postgres-db")

        target2 = agent.extract_target_service("Target Service: `redis` - Memory limit")
        self.assertEqual(target2, "shadow-redis")

    def test_agent_primitive_inference(self):
        """Verify agent infers correct fault primitive without a static lookup table."""
        agent = FaultSelectionAgent()

        # Case 11: Connection exhaustion
        prim1, params1 = agent.infer_fault_primitive(
            "Target Service: `postgres-db` - PostgreSQL max connection limit reached",
            "PostgreSQL max connection limit reached causing query timeouts",
            "shadow-postgres-db"
        )
        self.assertEqual(prim1, "apply_resource_exhaustion")
        self.assertEqual(params1.get("resource_type"), "postgres_connections")

        # Case 12: Memory limit
        prim2, params2 = agent.infer_fault_primitive(
            "Target Service: `redis` - Memory limit reached under noeviction policy",
            "Redis cache memory full",
            "shadow-redis"
        )
        self.assertEqual(prim2, "apply_resource_exhaustion")
        self.assertEqual(params2.get("resource_type"), "memory_limit")

        # Case 16: Queue backlog
        prim3, params3 = agent.infer_fault_primitive(
            "Target Service: `rabbitmq` - High message queue backlog accumulating",
            "RabbitMQ queue congestion due to consumer bottleneck",
            "shadow-rabbitmq"
        )
        self.assertEqual(prim3, "apply_queue_pressure")


if __name__ == "__main__":
    unittest.main()
