import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_chaos_scenarios_uses_file_lock_and_os_replace():
    scenarios_path = os.path.join(os.path.dirname(__file__), "..", "chaos_scenarios.py")
    with open(scenarios_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "file_lock_context" in content
    assert "atomic_write_json" in content
    assert "os.rename" not in content

def test_utils_atomic_write_uses_os_replace():
    utils_path = os.path.join(os.path.dirname(__file__), "..", "utils.py")
    with open(utils_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "os.replace(" in content
