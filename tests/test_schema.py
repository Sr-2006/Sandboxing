import sys
import os
import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_schema import IncidentEvent

def test_valid_incident_event():
    ie = IncidentEvent(
        incident_id="auth-service_12",
        target_service="auth-service",
        priority_score=85.5,
        severity="CRITICAL",
        occurrence_count=10
    )
    assert ie.incident_id == "auth-service_12"
    assert ie.severity == "CRITICAL"

def test_invalid_incident_id_regex():
    with pytest.raises(ValidationError):
        IncidentEvent(
            incident_id="invalid-id-without-cluster-number",
            target_service="auth-service",
            priority_score=50.0,
            severity="HIGH",
            occurrence_count=5
        )
