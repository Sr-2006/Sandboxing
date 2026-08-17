import os
import time
import gc
from datetime import datetime, timezone
from utils import atomic_write_json, read_json_file, get_logger, project_path
from package_ml_dataset import parse_docker_compose_topology

logger = get_logger("frontend_data_sync")

OUTPUT_DIR = project_path("frontend_data")
RAW_TELEMETRY_FILE = project_path("frontend_data", "raw_telemetry.json")
TIME_SERIES_FILE = project_path("frontend_data", "time_series.json")
STATUS_FILE = project_path("frontend_data", "status.json")
ANALYTICS_FILE = project_path("frontend_data", "analytics.json")

MAX_TIME_SERIES_ENTRIES = 5000
MAX_HEALTH_HISTORY_ENTRIES = 100
SYNC_INTERVAL = 5.0

CRITICAL_SERVICES = {"api-gateway", "postgres-db", "otel-collector"}

# Dynamic Topology Cache (Single source of truth from docker-compose.yml)
_TOPOLOGY_CACHE = {"mtime": None, "data": None}

def get_topology():
    compose_file = project_path("docker-compose.yml")
    mtime = os.path.getmtime(compose_file) if os.path.exists(compose_file) else 0
    if _TOPOLOGY_CACHE["mtime"] != mtime or _TOPOLOGY_CACHE["data"] is None:
        _TOPOLOGY_CACHE["data"] = parse_docker_compose_topology()
        _TOPOLOGY_CACHE["mtime"] = mtime
    return _TOPOLOGY_CACHE["data"]

def log_msg(msg: str):
    logger.info(msg)

def compute_container_health_score(container: dict) -> float:
    status = container.get("status", "running").lower()
    if status in ("exited", "dead"):
        return 0.0

    score = 100.0
    health = (container.get("health") or "").lower()
    anomaly_score = float(container.get("anomaly_score", 0.0))
    mem_pct = float(container.get("memory_percent", 0.0))
    cpu_pct = float(container.get("cpu_percent", 0.0))

    if health == "unhealthy":
        score -= 50.0
    if anomaly_score > 0.0:
        score -= min(30.0, anomaly_score * 10.0)
    if mem_pct > 90.0 or cpu_pct > 95.0:
        score -= 15.0

    return max(0.0, min(100.0, score))

def get_dependency_status(score: float) -> str:
    if score >= 80.0:
        return "healthy"
    elif score >= 50.0:
        return "degraded"
    return "unhealthy"

def sync_cycle():
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Read raw_telemetry.json
    raw_data = read_json_file(RAW_TELEMETRY_FILE, {"generated_at": now_iso, "containers": []})
    containers = raw_data.get("containers", [])

    if not containers and not os.path.exists(RAW_TELEMETRY_FILE):
        atomic_write_json(RAW_TELEMETRY_FILE, {"generated_at": now_iso, "containers": []})

    # 2. Maintain time_series.json
    time_series_data = read_json_file(TIME_SERIES_FILE, [])
    new_ts_points = []
    
    for c in containers:
        c_name = c.get("name")
        new_ts_points.append({
            "timestamp": now_iso,
            "container": c_name,
            "cpu_percent": c.get("cpu_percent", 0.0),
            "memory_percent": c.get("memory_percent", 0.0),
            "network_tx": c.get("network_tx_rate", 0.0),
            "network_rx": c.get("network_rx_rate", 0.0)
        })

    combined_ts = time_series_data + new_ts_points
    if len(combined_ts) > MAX_TIME_SERIES_ENTRIES:
        combined_ts = combined_ts[-MAX_TIME_SERIES_ENTRIES:]
    atomic_write_json(TIME_SERIES_FILE, combined_ts)

    # 3. Compute per-container health scores
    container_health_map = {}
    for c in containers:
        c_name = c.get("name")
        c_score = compute_container_health_score(c)
        container_health_map[c_name] = c_score

    # 4. Compute global system health score & active warnings
    total_weight = 0.0
    weighted_score_sum = 0.0
    active_warnings_count = 0

    for c in containers:
        c_name = c.get("name")
        c_status = c.get("status", "running")
        c_warnings = c.get("active_warnings", 0)
        c_score = container_health_map.get(c_name, 100.0)

        weight = 2.0 if c_name in CRITICAL_SERVICES else 1.0
        weighted_score_sum += c_score * weight
        total_weight += weight

        if c_warnings > 0 or c_status != "running":
            active_warnings_count += 1

    system_health_score = round(weighted_score_sum / total_weight, 1) if total_weight > 0 else 100.0

    # 5. Build status.json with single-source-of-truth topology dependencies
    topo = get_topology()
    services_list = []
    for c in containers:
        c_name = c.get("name")
        c_status = c.get("status", "running")
        c_health = (c.get("health") or "healthy") if c_status == "running" else "unhealthy"
        c_score = container_health_map.get(c_name, 100.0)

        # Build dependency states from docker-compose topology
        deps = topo.get(c_name, {}).get("downstream_dependencies", [])
        dependency_states = {}
        for dep in deps:
            dep_score = container_health_map.get(dep, 100.0)
            dependency_states[dep] = get_dependency_status(dep_score)

        services_list.append({
            "name": c_name,
            "docker_status": c_status,
            "health_check": c_health,
            "cpu_percent": c.get("cpu_percent", 0.0),
            "memory_percent": c.get("memory_percent", 0.0),
            "anomaly_score": c.get("anomaly_score", 0.0),
            "health_score": round(c_score, 1),
            "dependency_states": dependency_states
        })

    status_payload = {
        "timestamp": now_iso,
        "system_health_score": system_health_score,
        "active_warnings": active_warnings_count,
        "services": services_list
    }
    atomic_write_json(STATUS_FILE, status_payload)

    # 6. Update analytics.json
    analytics_data = read_json_file(ANALYTICS_FILE, {})
    health_history = analytics_data.get("health_history", [])
    health_history.append({
        "timestamp": now_iso,
        "score": system_health_score
    })
    if len(health_history) > MAX_HEALTH_HISTORY_ENTRIES:
        health_history = health_history[-MAX_HEALTH_HISTORY_ENTRIES:]

    analytics_payload = {
        "generated_at": now_iso,
        "system_health_score": system_health_score,
        "active_warnings": active_warnings_count,
        "health_history": health_history
    }
    atomic_write_json(ANALYTICS_FILE, analytics_payload)
    gc.collect()

    log_msg(f"Sync complete. System Health: {system_health_score}, Active Warnings: {active_warnings_count}, Services: {len(services_list)}")

def run_sync_loop():
    log_msg("Starting Frontend Data Sync Loop...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Initialize supporting schemas if absent
    empty_schemas = {
        "causality.json": {"root_cause": "", "confidence": 0, "evidence": []},
        "cost_and_roi.json": {"estimated_cost": 0.0, "impact": "none"}
    }
    for filename, schema in empty_schemas.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(filepath):
            atomic_write_json(filepath, schema)

    while True:
        try:
            sync_cycle()
        except Exception as e:
            log_msg(f"Error during sync cycle: {e}")
        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    run_sync_loop()