import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import assign_severity_bucket

def test_severity_bucket_boundaries():
    assert assign_severity_bucket(75.1) == "CRITICAL"
    assert assign_severity_bucket(75.0) == "HIGH"
    assert assign_severity_bucket(55.1) == "HIGH"
    assert assign_severity_bucket(55.0) == "MEDIUM"
    assert assign_severity_bucket(35.1) == "MEDIUM"
    assert assign_severity_bucket(34.9) == "LOW"
    assert assign_severity_bucket(0.0) == "LOW"
