import os
import json
import math
import re
import gc
import argparse
from datetime import datetime, timezone
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.masking import MaskingInstruction
from drain3.file_persistence import FilePersistence
from utils import atomic_write_json, read_json_file, parse_iso_dt
from package_ml_dataset import parse_docker_compose_topology

DRAIN3_STATE_FILE = os.path.join("frontend_data", "drain3_state.bin")
VERSION_HEADER_FILE = os.path.join("frontend_data", "drain3_version.meta")
PROCESSOR_VERSION = 2

# ==========================================
# 1. DRAIN3 CONFIGURATION & ADVANCED MASKING
# ==========================================
config = TemplateMinerConfig()
config.drain_max_clusters = 10000
config.drain_max_node_depth = 4
config.drain_max_children = 256

config.masking_instructions = [
    MaskingInstruction(pattern=r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?|\d{2}:\d{2}:\d{2}\.\d{3}", mask_with="TIMESTAMP"),
    MaskingInstruction(pattern=r"\[(?:http-nio-)?[\w\-\s\.]+\]", mask_with="THREAD"),
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})((?=[^A-Za-z0-9])|$)", mask_with="IP"),
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})((?=[^A-Za-z0-9])|$)", mask_with="UUID"),
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)(0x[a-fA-F0-9]+|[a-fA-F0-9]{16,64})((?=[^A-Za-z0-9])|$)", mask_with="HEX"),
    MaskingInstruction(pattern=r"(?:/[a-zA-Z0-9_\.\-]+){2,}", mask_with="PATH"),
    MaskingInstruction(pattern=r"(?<=[=:])\s*['\"]?[a-zA-Z0-9_\-\.]+['\"]?", mask_with="VAR"),
    MaskingInstruction(pattern=r"(?<=\.java:)\d+|(?<=\.kt:)\d+", mask_with="LINE"),
    MaskingInstruction(pattern=r"\b\d+\b", mask_with="NUM"),
    MaskingInstruction(pattern=r"\x1b\[\d+(?:;\d+)*m", mask_with="ANSI"),
    MaskingInstruction(pattern=r"\x1b\[0m", mask_with="ANSI_RESET")
]

persistence_handler = FilePersistence(DRAIN3_STATE_FILE)
miner = TemplateMiner(persistence_handler=persistence_handler, config=config)

REDIS_NOISE_RE = re.compile(
    r'(oO0OoO0OoO0Oo|Running in standalone mode|Port: \d+|'
    r'Ready to accept connections|server is now ready|'
    r'Warning: no config file specified|'
    r'Configured to not listen anywhere|'
    r'Server initialized|'
    r'Background saving|'
    r'DB loaded from disk|'
    r'Reading the remaining RDB|'
    r'RDB memory usage|'
    r'Running mode=|'
    r'Configuration loaded|'
    r'Loading RDB|'
    r'Server started, Redis version|'
    r'\d+:\w+ \d+ \w+ \d{4} \d{2}:\d{2}:\d{2}.*)',
    re.IGNORECASE
)

REDIS_ERROR_ALLOWLIST_RE = re.compile(
    r"#\s*Error|MISCONF|Failed|CantSaveIn|fatal|out of memory|WRONGTYPE|NOREPLICAS|\bLOADING\s+Redis",
    re.IGNORECASE
)

RABBITMQ_NOISE_RE = re.compile(
    r'(Server startup complete|'
    r'Time to start RabbitMQ|'
    r'Starting RabbitMQ|'
    r'SIGTERM received|'
    r'Setting up loggers|'
    r'rabbit on node|'
    r'node           :|'
    r'home dir       :|'
    r'config file\(s\):|'
    r'cookie hash    :|'
    r'log\(s\)       :|'
    r'database dir   :|'
    r'Running boot step .*|'
    r'Deprecated features:.*|'
    r'\[\w+\] .* \d+\.\d+\.\d+.*)',
    re.IGNORECASE
)

RABBITMQ_ERROR_ALLOWLIST_RE = re.compile(
    r"#\s*Error|MISCONF|\b(?:CRITICAL|FATAL|ERROR)\b|Exception|ConnectionClosed|disk_alarm|connection\.retry|out of memory",
    re.IGNORECASE
)

def is_infra_noise(container_name: str, level: str, raw_content: str) -> bool:
    # Try parsing inner JSON to detect startup thread
    thread_name = None
    cleaned = raw_content.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            inner = json.loads(cleaned)
            thread_name = inner.get("thread_name") or inner.get("thread")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    # Filter out main thread logs (startup noise)
    if thread_name == "main":
        return True

    # Filter out Hibernate dialect / open-in-view warnings / Hikari pause warnings
    if "PostgreSQLDialect" in raw_content or "open-in-view" in raw_content or "Thread starvation or clock leap" in raw_content:
        return True

    # Filter out postgres container initialization noise
    if container_name == "postgres-db":
        if "initdb" in raw_content or "trust" in raw_content or "PostgreSQL Database directory" in raw_content:
            return True

    # Filter out Tomcat post-filter unwound error logs (which lack MDC trace context)
    if "org.apache.catalina.core.ContainerBase" in raw_content or "StandardWrapperValve" in raw_content:
        return True

    # Treat non-error redis/rabbitmq logs as noise
    if container_name == "redis":
        if REDIS_ERROR_ALLOWLIST_RE.search(raw_content) or "WARNING" in raw_content:
            return False
        if REDIS_NOISE_RE.search(raw_content):
            return True
        if level.upper() == "INFO":
            return True
        return False
            
    if container_name == "rabbitmq":
        if RABBITMQ_ERROR_ALLOWLIST_RE.search(raw_content):
            return False
        return True

    return False

# Dynamic Topology Cache
_TOPOLOGY_CACHE = {"mtime": None, "data": None}

def get_topology():
    compose_file = "docker-compose.yml"
    mtime = os.path.getmtime(compose_file) if os.path.exists(compose_file) else 0
    if _TOPOLOGY_CACHE["mtime"] != mtime or _TOPOLOGY_CACHE["data"] is None:
        _TOPOLOGY_CACHE["data"] = parse_docker_compose_topology()
        _TOPOLOGY_CACHE["mtime"] = mtime
    return _TOPOLOGY_CACHE["data"]

# Multi-line Stack Trace Stitching Regexes
EXCEPTION_START_RE = re.compile(r'^(?:.*\b)?(?:Exception|Error|Throwable|Caused by:)|^[A-Za-z_$][\w.$]*Exception\b')
CONTINUATION_RE = re.compile(r'^\s*at\s|^\s*\.\.\.|^\s*Caused by:|^\s*\.\.\.\s+\d+\s+more')

def preprocess_log_header(line: str) -> str:
    if not line:
        return ""
    line = re.sub(r"(\.(?:java|kt|scala)):\d+", r"\1:<LINE>", line)
    return line

def stitch_log_events(events_data):
    stitched_events = []
    buffers = {}
    container_block_counts = {}

    for event in events_data:
        container = event.get("container", "unknown")
        raw_content = (event.get("content") or "").strip()
        if not raw_content:
            continue
        raw_content = re.sub(r'\x1b\[[0-9;]*m', '', raw_content)
        event["content"] = raw_content

        first_line = raw_content.split("\n")[0].strip()

        # Check if continuation line
        if container in buffers and (CONTINUATION_RE.match(raw_content) or CONTINUATION_RE.match(first_line)):
            buffers[container]["lines"].extend(raw_content.split("\n"))
            continue

        if container in buffers:
            b = buffers.pop(container)
            merged_content = "\n".join(b["lines"])[:4000]
            evt = dict(b["first_event"])
            evt["content"] = merged_content
            stitched_events.append(evt)

        if EXCEPTION_START_RE.search(first_line) or EXCEPTION_START_RE.search(raw_content):
            current_count = container_block_counts.get(container, 0)
            if current_count < 50: # Bounded block cache per container
                buffers[container] = {
                    "first_event": event,
                    "lines": raw_content.split("\n")
                }
                container_block_counts[container] = current_count + 1
            else:
                stitched_events.append(event)
        else:
            stitched_events.append(event)

    for container, b in buffers.items():
        merged_content = "\n".join(b["lines"])[:4000]
        evt = dict(b["first_event"])
        evt["content"] = merged_content
        stitched_events.append(evt)

    return stitched_events

def calculate_priority_score(
    max_severity: str,
    occurrence_count: int,
    container_status: str,
    container_health: str,
    anomaly_score: float,
    minutes_since_last_seen: float,
    container_name: str = ""
) -> float:
    severity_weights = {
        "CRITICAL": 50,
        "ERROR": 40,
        "WARN": 20,
        "WARNING": 20,
        "INFO": 5 if container_name == "redis" else 10
    }
    base_weight = severity_weights.get(max_severity.upper(), 10)

    if container_status in ("exited", "dead"):
        state_penalty = 50.0
    elif (container_health or "").lower() == "unhealthy":
        state_penalty = 30.0
    else:
        state_penalty = 0.0

    anomaly_penalty = min(25.0, anomaly_score * 10.0)
    time_decay = min(20.0, 0.1 * max(0.0, minutes_since_last_seen))

    score = (base_weight * math.log10(occurrence_count + 1)) + state_penalty + anomaly_penalty - time_decay
    return round(max(0.0, score), 2)

def assign_severity_bucket(priority_score: float) -> str:
    if priority_score > 75.0:
        return "CRITICAL"
    elif priority_score > 55.0:
        return "HIGH"
    elif priority_score > 35.0:
        return "MEDIUM"
    return "LOW"

def check_drain_version_and_reset_if_needed(force_reset: bool = False):
    should_reset = force_reset
    if os.path.exists(VERSION_HEADER_FILE):
        try:
            with open(VERSION_HEADER_FILE, "r") as f:
                v = int(f.read().strip())
                if v != PROCESSOR_VERSION:
                    should_reset = True
        except Exception:
            should_reset = True
    elif os.path.exists(DRAIN3_STATE_FILE):
        should_reset = True

    if should_reset:
        for file_path in [DRAIN3_STATE_FILE, VERSION_HEADER_FILE]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        print(f"[+] Version migration / --reset-drain: Reset Drain3 cluster state for v{PROCESSOR_VERSION}.")
        with open(VERSION_HEADER_FILE, "w") as f:
            f.write(str(PROCESSOR_VERSION))

def process_phase1_incidents(reset_drain: bool = False):
    events_file = os.path.join("frontend_data", "events_and_incidents.json")
    status_file = os.path.join("frontend_data", "status.json")
    raw_telemetry_file = os.path.join("frontend_data", "raw_telemetry.json")
    time_series_file = os.path.join("frontend_data", "time_series.json")
    chaos_history_file = os.path.join("frontend_data", "chaos_history.json")
    output_file = os.path.join("frontend_data", "processed_incidents.json")

    print("=== [Auto-SRE Phase 1] Processing Inbound Telemetry & Log Clusters ===")

    check_drain_version_and_reset_if_needed(reset_drain)

    if os.path.exists(DRAIN3_STATE_FILE):
        try:
            miner.load_state()
            print(f"[+] Loaded Drain3 cluster state from '{DRAIN3_STATE_FILE}'")
        except Exception as e:
            print(f"[-] Warning: Could not load Drain3 state from '{DRAIN3_STATE_FILE}': {e}. Starting fresh.")

    if not os.path.exists(events_file):
        print(f"[-] Error: '{events_file}' not found.")
        return

    events_data = read_json_file(events_file, [], retries=3)
    if not events_data:
        print(f"[-] Warning: '{events_file}' is empty. No incidents to cluster.")
        empty_payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "incidents": []
        }
        atomic_write_json(output_file, empty_payload)
        return

    # Multi-line stack trace stitching
    stitched_events = stitch_log_events(events_data)

    status_data = read_json_file(status_file, {}, retries=3)
    raw_telemetry_data = read_json_file(raw_telemetry_file, {}, retries=3)
    time_series_data = read_json_file(time_series_file, [], retries=3)
    chaos_history_data = read_json_file(chaos_history_file, [], retries=3)

    system_health_score = status_data.get("system_health_score", 100.0)
    active_warnings_count = status_data.get("active_warnings", 0)

    container_telemetry_map = {c.get("name"): c for c in raw_telemetry_data.get("containers", [])}
    status_service_map = {s.get("name"): s for s in status_data.get("services", [])}

    topology_map = get_topology()

    dt_cache = {}
    def cached_parse_dt(ts_str: str) -> datetime:
        if ts_str not in dt_cache:
            dt_cache[ts_str] = parse_iso_dt(ts_str)
        return dt_cache[ts_str]

    clusters = {}
    max_log_dt = datetime.min.replace(tzinfo=timezone.utc)

    for event in stitched_events:
        container_name = event.get("container", "unknown")
        raw_content = event.get("content", "")
        level = event.get("level", "INFO").upper()
        ts_str = event.get("timestamp", "")
        dt = cached_parse_dt(ts_str)

        if is_infra_noise(container_name, level, raw_content):
            continue

        if dt > max_log_dt:
            max_log_dt = dt

        first_line = raw_content.strip().split("\n")[0] if raw_content else ""
        if not first_line:
            continue

        processed_line = preprocess_log_header(first_line)
        result = miner.add_log_message(processed_line)
        drain_cluster_id = result["cluster_id"]
        template = result["template_mined"]

        incident_key = f"{container_name}_{drain_cluster_id}"

        if incident_key not in clusters:
            clusters[incident_key] = {
                "incident_id": incident_key,
                "target_service": container_name,
                "cluster_id": drain_cluster_id,
                "template": template,
                "occurrence_count": 0,
                "severities": set(),
                "earliest_dt": dt,
                "latest_dt": dt,
                "log_samples": []
            }

        c_info = clusters[incident_key]
        c_info["occurrence_count"] += 1
        c_info["severities"].add(level)
        if dt < c_info["earliest_dt"]:
            c_info["earliest_dt"] = dt
        if dt > c_info["latest_dt"]:
            c_info["latest_dt"] = dt

        c_info["log_samples"].append({
            "timestamp": ts_str,
            "level": level,
            "content": raw_content,
            "trace_id": event.get("trace_id"),
            "span_id": event.get("span_id")
        })

    try:
        miner.save_state("periodic_snapshot")
        print(f"[+] Saved Drain3 cluster state to '{DRAIN3_STATE_FILE}'")
        with open(VERSION_HEADER_FILE, "w") as f:
            f.write(str(PROCESSOR_VERSION))
    except Exception as e:
        print(f"[-] Warning: Failed to save Drain3 state: {e}")

    ref_time = max_log_dt if max_log_dt != datetime.min.replace(tzinfo=timezone.utc) else datetime.now(timezone.utc)
    incidents_list = []

    for incident_key, c_info in clusters.items():
        container_name = c_info["target_service"]
        occ_count = c_info["occurrence_count"]

        sevs = c_info["severities"]
        if "CRITICAL" in sevs:
            highest_sev = "CRITICAL"
        elif "ERROR" in sevs:
            highest_sev = "ERROR"
        elif "WARN" in sevs or "WARNING" in sevs:
            highest_sev = "WARN"
        else:
            highest_sev = "INFO"

        c_tel = container_telemetry_map.get(container_name, {})
        c_stat = status_service_map.get(container_name, {})

        c_docker_status = c_tel.get("status") or c_stat.get("docker_status") or "running"
        c_health = c_tel.get("health") or c_stat.get("health_check") or "healthy"
        c_anomaly_score = float(c_tel.get("anomaly_score", 0.0))

        mins_since_seen = max(0.0, (ref_time - c_info["latest_dt"]).total_seconds() / 60.0)

        priority = calculate_priority_score(
            max_severity=highest_sev,
            occurrence_count=occ_count,
            container_status=c_docker_status,
            container_health=c_health,
            anomaly_score=c_anomaly_score,
            minutes_since_last_seen=mins_since_seen,
            container_name=container_name
        )

        severity_label = assign_severity_bucket(priority)

        sorted_samples = sorted(
            c_info["log_samples"],
            key=lambda s: cached_parse_dt(s.get("timestamp")),
            reverse=True
        )[:5]

        container_ts = [pt for pt in time_series_data if pt.get("container") == container_name]
        recent_ts = container_ts[-3:] if len(container_ts) >= 3 else container_ts

        mem_limit = c_tel.get("memory_limit_bytes", 0)
        metrics_snapshot = []
        for pt in recent_ts:
            mem_pct = pt.get("memory_percent", 0.0)
            mem_bytes = int(mem_limit * (mem_pct / 100.0)) if mem_limit > 0 else 0
            metrics_snapshot.append({
                "timestamp": pt.get("timestamp"),
                "cpu_percent": pt.get("cpu_percent", 0.0),
                "memory_usage_bytes": mem_bytes,
                "memory_usage_percent": mem_pct
            })

        topo = topology_map.get(container_name, {
            "role": "service",
            "downstream_dependencies": [],
            "exposed_ports": []
        })

        service_health_status = {
            "docker_status": c_docker_status,
            "health_check": c_health,
            "dependency_states": c_stat.get("dependency_states", {})
        }

        chaos_mutation_desc = ""
        cluster_start = c_info["earliest_dt"].timestamp()
        cluster_end = c_info["latest_dt"].timestamp()

        for scenario in chaos_history_data:
            scenario_ts_str = scenario.get("timestamp", "")
            scenario_dt = cached_parse_dt(scenario_ts_str)
            scenario_dur = scenario.get("duration", 0)
            target_services = scenario.get("target_services", [])

            scen_start = scenario_dt.timestamp() - 300.0
            scen_end = scenario_dt.timestamp() + scenario_dur + 300.0

            if (cluster_start <= scen_end and cluster_end >= scen_start) and (container_name in target_services or not target_services):
                faults_str = ", ".join(scenario.get("faults", []))
                targets_str = ", ".join(target_services)
                chaos_mutation_desc = f"Infrastructure orchestrator triggered {faults_str} on {targets_str} (duration: {scenario_dur}s)."
                break

        incident_obj = {
            "system_context": {
                "objective": "Perform automated Multi-Agent Root Cause Analysis (RCA) and recommend corrective actions.",
                "environment": "Dockerized Microservices (Java/Spring Boot, PostgreSQL, Redis, RabbitMQ, OpenTelemetry)",
                "current_health_score": system_health_score,
                "active_warnings": active_warnings_count
            },
            "incident_event": {
                "incident_id": incident_key,
                "target_service": container_name,
                "priority_score": priority,
                "severity": severity_label,
                "occurrence_count": occ_count
            },
            "infrastructure_topology": topo,
            "service_health_status": service_health_status,
            "telemetry_evidence": {
                "log_cluster_template": c_info["template"],
                "log_samples": sorted_samples,
                "metrics_snapshot": metrics_snapshot
            },
            "injected_chaos_context": {
                "active_infrastructure_mutations": chaos_mutation_desc
            }
        }

        incidents_list.append(incident_obj)

    incidents_list.sort(key=lambda x: x["incident_event"]["priority_score"], reverse=True)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    final_payload = {
        "generated_at": now_iso,
        "incidents": incidents_list
    }

    atomic_write_json(output_file, final_payload)
    gc.collect()

    # Calculate trace context correlation ratio
    total_error_warn = 0
    correlated_trace_span = 0
    for incident in incidents_list:
        for sample in incident["telemetry_evidence"]["log_samples"]:
            if sample.get("level") in ("ERROR", "WARN"):
                total_error_warn += 1
                if sample.get("trace_id") and sample.get("span_id"):
                    correlated_trace_span += 1

    ratio = (correlated_trace_span / total_error_warn * 100.0) if total_error_warn > 0 else 100.0
    print(f"[+] Trace/Span ID Correlation Ratio for ERROR/WARN logs: {ratio:.1f}% ({correlated_trace_span}/{total_error_warn})")
    print(f"[+] Success! {len(incidents_list)} incidents clustered and exported to '{output_file}'.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-SRE Phase 1 Log Clustering Processor")
    parser.add_argument("--reset-drain", action="store_true", help="Delete Drain3 state file before processing to force fresh clustering")
    args = parser.parse_args()

    process_phase1_incidents(reset_drain=args.reset_drain)
def is_redis_noise(container_name: str, level: str, raw_content: str) -> bool:
    return is_infra_noise(container_name, level, raw_content)
