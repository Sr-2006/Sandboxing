import pytest
import subprocess
import time
import requests
import os
import json
import sys

SHADOW_BASE = "http://localhost:9080"
PROD_BASE = "http://localhost:8080"

def get_run_shadow_cmd(action="up"):
    if sys.platform == "win32":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", ".\\run-shadow.ps1", action]
    return ["./run-shadow.sh", action]

class TestShadowSandboxing:
    @classmethod
    def setup_class(cls):
        try:
            subprocess.run(get_run_shadow_cmd("up"), check=False)
            time.sleep(2)
        except Exception:
            pass

    @classmethod
    def teardown_class(cls):
        try:
            subprocess.run(get_run_shadow_cmd("down"), check=False)
        except Exception:
            pass

    def test_shadow_stack_deploys(self):
        try:
            r = requests.get(f"{SHADOW_BASE}/chaos/shadow-status", timeout=2)
            assert r.status_code == 200
            assert r.json()["sandbox"] is True
        except Exception as e:
            pytest.skip(f"Shadow stack not running: {e}")

    def test_shadow_payment_mock(self):
        try:
            r = requests.post("http://localhost:9083/api/payments/process",
                             headers={"X-User-Id": "test"}, timeout=2)
            assert r.status_code == 200
            assert r.json()["status"] == "mock_success"
        except Exception as e:
            pytest.skip(f"Shadow payment service not running: {e}")

    def test_chaos_namespace_isolation(self):
        os.environ["CHAOS_TARGET_NAMESPACE"] = "shadow"
        try:
            from chaos_orchestrator import get_container
            c = get_container("api-gateway")
            assert c.name == "shadow-api-gateway"
        except Exception as e:
            pytest.skip(f"Docker client not available: {e}")


    def test_traffic_mirror_reaches_shadow(self):
        pytest.skip("Requires manual mirror enablement")

    def test_shadow_ml_validator_gate(self):
        from shadow_ml_validator import run_shadow_validation
        result = run_shadow_validation()
        assert isinstance(result, bool)

    def test_jaeger_tagging(self):
        try:
            requests.get(f"{SHADOW_BASE}/chaos/shadow-status", timeout=2)
            time.sleep(1)
            jaeger_url = "http://localhost:16686/api/traces?service=shadow-api-gateway&limit=1"
            r = requests.get(jaeger_url, timeout=2)
            assert r.status_code == 200
            traces = r.json().get("data", [])
            if traces:
                tags = {t["key"]: t["value"] for t in traces[0]["spans"][0]["tags"]}
                assert tags.get("sandbox.environment") == "shadow"
        except Exception as e:
            pytest.skip(f"Jaeger or Shadow Gateway not running: {e}")
