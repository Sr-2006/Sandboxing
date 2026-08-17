import sys
import os
import re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_chaos_scenarios_uses_file_lock_and_os_replace():
    utils_path = os.path.join(os.path.dirname(__file__), "..", "utils.py")
    with open(utils_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "file_lock_context" in content
    assert "atomic_write_json" in content
    assert "os.rename" not in content

def test_utils_atomic_write_uses_os_replace_and_fsync():
    # FIX C4: fsync and atomic replacement
    utils_path = os.path.join(os.path.dirname(__file__), "..", "utils.py")
    with open(utils_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "os.replace(" in content
    assert "os.fsync(" in content
    assert "f.flush()" in content

def test_file_lock_never_removes_lock_file():
    # FIX C3: No os.remove inside file_lock_context
    utils_path = os.path.join(os.path.dirname(__file__), "..", "utils.py")
    with open(utils_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract file_lock_context definition
    flc_match = re.search(r"def file_lock_context\(.*?\):\n(.*?)(?=\ndef |\Z)", content, re.DOTALL)
    assert flc_match is not None
    flc_body = flc_match.group(1)
    assert "os.remove" not in flc_body

def test_no_module_level_miner_in_phase1_processor():
    # FIX C5: No module-level TemplateMiner instantiation
    processor_path = os.path.join(os.path.dirname(__file__), "..", "phase1_processor.py")
    with open(processor_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        if line.startswith("miner = TemplateMiner"):
            assert False, "Found module-level TemplateMiner instantiation!"

def test_shared_chaos_correlation_in_utils():
    # FIX M3: Shared correlate_chaos_event
    utils_path = os.path.join(os.path.dirname(__file__), "..", "utils.py")
    with open(utils_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "def correlate_chaos_event(" in content
