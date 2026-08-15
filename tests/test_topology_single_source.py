import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_topology_single_source_contract():
    processor_path = os.path.join(os.path.dirname(__file__), "..", "phase1_processor.py")
    with open(processor_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "from package_ml_dataset import parse_docker_compose_topology" in content
    assert "TOPOLOGY_MAP = {" not in content
