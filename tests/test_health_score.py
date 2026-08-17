from frontend_data_sync import compute_container_health_score, get_dependency_status, get_topology

def test_dead_container_yields_zero_health_score():
    exited_container = {
        "name": "payment-service",
        "status": "exited",
        "health": None,
        "anomaly_score": 0.0,
        "memory_percent": 10.0,
        "cpu_percent": 0.0
    }
    score = compute_container_health_score(exited_container)
    assert score == 0.0
    assert get_dependency_status(score) == "unhealthy"

def test_dead_container_status_dead():
    dead_container = {
        "name": "order-service",
        "status": "dead",
        "health": "unhealthy",
        "anomaly_score": 5.0,
        "memory_percent": 0.0,
        "cpu_percent": 0.0
    }
    score = compute_container_health_score(dead_container)
    assert score == 0.0
    assert get_dependency_status(score) == "unhealthy"

def test_healthy_running_container():
    healthy_container = {
        "name": "auth-service",
        "status": "running",
        "health": "healthy",
        "anomaly_score": 0.0,
        "memory_percent": 45.0,
        "cpu_percent": 12.0
    }
    score = compute_container_health_score(healthy_container)
    assert score == 100.0
    assert get_dependency_status(score) == "healthy"

def test_unhealthy_healthcheck_penalty():
    unhealthy_container = {
        "name": "api-gateway",
        "status": "running",
        "health": "unhealthy",
        "anomaly_score": 0.0,
        "memory_percent": 50.0,
        "cpu_percent": 20.0
    }
    score = compute_container_health_score(unhealthy_container)
    assert score == 50.0
    assert get_dependency_status(score) == "degraded"

def test_dynamic_topology_single_source():
    topo = get_topology()
    assert isinstance(topo, dict)
    assert "api-gateway" in topo
    assert "auth-service" in topo.get("api-gateway", {}).get("downstream_dependencies", [])
