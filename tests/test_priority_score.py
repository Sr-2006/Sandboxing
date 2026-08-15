import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import calculate_priority_score

def test_base_weight_calculation():
    # ERROR with occ=9, log10(10)=1.0, healthy, 0 anomaly, 0 decay -> 40 * 1 = 40.0
    score = calculate_priority_score(
        max_severity="ERROR",
        occurrence_count=9,
        container_status="running",
        container_health="healthy",
        anomaly_score=0.0,
        minutes_since_last_seen=0.0
    )
    assert score == 40.0

def test_exited_state_penalty():
    # ERROR with occ=9 (40.0) + state_penalty=50.0 = 90.0
    score = calculate_priority_score(
        max_severity="ERROR",
        occurrence_count=9,
        container_status="exited",
        container_health="unhealthy",
        anomaly_score=0.0,
        minutes_since_last_seen=0.0
    )
    assert score == 90.0

def test_anomaly_penalty_cap():
    # anomaly_score 3.0 -> min(25.0, 30.0) = 25.0 cap
    score = calculate_priority_score(
        max_severity="WARN",
        occurrence_count=0, # log10(1)=0 -> 0.0
        container_status="running",
        container_health="healthy",
        anomaly_score=3.0,
        minutes_since_last_seen=0.0
    )
    assert score == 25.0

def test_time_decay_cap():
    # 300 minutes decay -> min(20.0, 30.0) = 20.0 cap
    score = calculate_priority_score(
        max_severity="CRITICAL",
        occurrence_count=9, # 50.0
        container_status="running",
        container_health="healthy",
        anomaly_score=0.0,
        minutes_since_last_seen=300.0
    )
    assert score == 30.0 # 50.0 - 20.0
