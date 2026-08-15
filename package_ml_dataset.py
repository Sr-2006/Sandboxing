import os
import json
import yaml
import time
import gc
from datetime import datetime, timezone
from utils import atomic_write_json, read_json_file, parse_iso_dt
from phase1_schema import (
    UnifiedMasterDataset,
    SystemContext,
    Incident,
    IncidentEvent,
    InfrastructureTopology,
    ServiceHealthStatus,
    TelemetryEvidence,
    InjectedChaosContext,
    LogSample,
    MetricsSnapshot
)

COMPOSE_FILE = "docker-compose.yml"
STATUS_FILE = os.path.join("frontend_data", "status.json")
TIME_SERIES_FILE = os.path.join("frontend_data", "time_series.json")
PROCESSED_INCIDENTS_FILE = os.path.join("frontend_data", "processed_incidents.json")
CHAOS_HISTORY_FILE = os.path.join("frontend_data", "chaos_history.json")
OUTPUT_DATASET_FILE = os.path.join("frontend_data", "unified_master_dataset.json")

def parse_docker_compose_topology():
    if not os.path.exists(COMPOSE_FILE):
        return {}

    with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
        compose_cfg = yaml.safe_load(f) or {}

    services = compose_cfg.get("services", {})
    known_services = set(services.keys())
    topology = {}

    for name, s_cfg in services.items():
        # 1. Role extraction from label ara.topology.role
        labels = s_cfg.get("labels", [])
        role = name
        if isinstance(labels, list):
            for lbl in labels:
                if isinstance(lbl, str) and lbl.startswith("ara.topology.role="):
                    role = lbl.split("=", 1)[1]
        elif isinstance(labels, dict):
            role = labels.get("ara.topology.role", name)

        # 2. Downstream dependencies extraction
        deps = set()
        dep_on = s_cfg.get("depends_on", [])
        if isinstance(dep_on, list):
            deps.update(dep_on)
        elif isinstance(dep_on, dict):
            deps.update(dep_on.keys())

        # Environment variable service references
        env = s_cfg.get("environment", {})
        if isinstance(env, dict):
            for k, v in env.items():
                if isinstance(v, str):
                    for s in known_services:
                        if s != name and s in v:
                            deps.add(s)
        elif isinstance(env, list):
            for entry in env:
                if isinstance(entry, str) and "=" in entry:
                    k, v = entry.split("=", 1)
                    for s in known_services:
                        if s != name and s in v:
                            deps.add(s)

        # 3. Exposed ports
        raw_ports = s_cfg.get("ports", [])
        exposed_ports = [str(p) for p in raw_ports]

        topology[name] = {
            "role": role,
            "downstream_dependencies": sorted(list(deps)),
            "exposed_ports": exposed_ports
        }

    return topology

def package_dataset():
    start_time = time.time()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=== [Auto-SRE Phase 1] Packaging Unified Master Dataset for ML/LLM ===")

    # 1. Parse topology from docker-compose.yml
    topology_map = parse_docker_compose_topology()

    # 2. Read live data files
    status_data = read_json_file(STATUS_FILE, {})
    processed_incidents_data = read_json_file(PROCESSED_INCIDENTS_FILE, {})
    chaos_history_data = read_json_file(CHAOS_HISTORY_FILE, [])

    system_health_score = status_data.get("system_health_score", 100.0)
    active_warnings_count = status_data.get("active_warnings", 0)

    # Build status mapping for services
    status_services_map = {}
    for s in status_data.get("services", []):
        status_services_map[s.get("name")] = s

    # 3. Construct system context
    system_context = SystemContext(
        objective="Perform automated Multi-Agent Root Cause Analysis (RCA) and recommend corrective actions.",
        environment="Dockerized Microservices (Java/Spring Boot, PostgreSQL, Redis, RabbitMQ, OpenTelemetry)",
        current_health_score=system_health_score,
        active_warnings=active_warnings_count
    )

    incidents_raw = processed_incidents_data.get("incidents", [])
    packaged_incidents = []

    for inc in incidents_raw:
        ie_data = inc.get("incident_event", {})
        target_service = ie_data.get("target_service", "unknown")

        # Incident Event
        incident_event = IncidentEvent(
            incident_id=ie_data.get("incident_id"),
            target_service=target_service,
            priority_score=float(ie_data.get("priority_score", 0.0)),
            severity=ie_data.get("severity", "LOW"),
            occurrence_count=int(ie_data.get("occurrence_count", 1))
        )

        # Dynamic Infrastructure Topology
        topo_data = topology_map.get(target_service, {
            "role": target_service,
            "downstream_dependencies": [],
            "exposed_ports": []
        })
        infrastructure_topology = InfrastructureTopology(
            role=topo_data.get("role", target_service),
            downstream_dependencies=topo_data.get("downstream_dependencies", []),
            exposed_ports=topo_data.get("exposed_ports", [])
        )

        # Service Health Status
        sh_data = inc.get("service_health_status", {})
        s_stat = status_services_map.get(target_service, {})
        service_health_status = ServiceHealthStatus(
            docker_status=sh_data.get("docker_status") or s_stat.get("docker_status", "running"),
            health_check=sh_data.get("health_check") or s_stat.get("health_check", "healthy"),
            dependency_states=sh_data.get("dependency_states") or s_stat.get("dependency_states", {})
        )

        # Telemetry Evidence
        te_data = inc.get("telemetry_evidence", {})
        log_samples_raw = te_data.get("log_samples", [])
        metrics_snapshot_raw = te_data.get("metrics_snapshot", [])

        log_samples = [
            LogSample(
                timestamp=ls.get("timestamp", now_iso),
                level=ls.get("level", "INFO"),
                content=ls.get("content", ""),
                trace_id=ls.get("trace_id"),
                span_id=ls.get("span_id")
            )
            for ls in log_samples_raw[:5]
        ]

        metrics_snapshot = [
            MetricsSnapshot(
                timestamp=ms.get("timestamp", now_iso),
                cpu_percent=float(ms.get("cpu_percent", 0.0)),
                memory_usage_bytes=int(ms.get("memory_usage_bytes", 0)),
                memory_usage_percent=float(ms.get("memory_usage_percent", 0.0))
            )
            for ms in metrics_snapshot_raw[:3]
        ]

        telemetry_evidence = TelemetryEvidence(
            log_cluster_template=te_data.get("log_cluster_template", ""),
            log_samples=log_samples,
            metrics_snapshot=metrics_snapshot
        )

        # Injected Chaos Context
        chaos_mutation_desc = ""
        sample_dts = [parse_iso_dt(ls.timestamp) for ls in log_samples] if log_samples else [parse_iso_dt(now_iso)]
        cluster_start = min(sample_dts).timestamp()
        cluster_end = max(sample_dts).timestamp()

        for scenario in chaos_history_data:
            scenario_ts_str = scenario.get("timestamp", "")
            scenario_dt = parse_iso_dt(scenario_ts_str)
            scenario_dur = scenario.get("duration", 0)
            target_services = scenario.get("target_services", [])

            scen_start = scenario_dt.timestamp() - 300.0
            scen_end = scenario_dt.timestamp() + scenario_dur + 300.0

            if (cluster_start <= scen_end and cluster_end >= scen_start) and (target_service in target_services or not target_services):
                faults_str = ", ".join(scenario.get("faults", []))
                targets_str = ", ".join(target_services)
                chaos_mutation_desc = f"Infrastructure orchestrator triggered {faults_str} on {targets_str} (duration: {scenario_dur}s)."
                break

        injected_chaos_context = InjectedChaosContext(
            active_infrastructure_mutations=chaos_mutation_desc
        )

        incident_model = Incident(
            system_context=system_context,
            incident_event=incident_event,
            infrastructure_topology=infrastructure_topology,
            service_health_status=service_health_status,
            telemetry_evidence=telemetry_evidence,
            injected_chaos_context=injected_chaos_context
        )
        packaged_incidents.append(incident_model)

    # Build Master Dataset model
    master_dataset = UnifiedMasterDataset(
        generated_at=now_iso,
        system_context=system_context,
        incidents=packaged_incidents
    )

    # 4. Strict Schema Validation with Pydantic
    try:
        # Validate dump
        serialized_payload = master_dataset.model_dump()
        # Verify round-trip model validation
        UnifiedMasterDataset.model_validate(serialized_payload)
    except Exception as validation_err:
        print(f"[-] FATAL: Master dataset validation failed: {validation_err}")
        return

    # 5. Atomic write
    atomic_write_json(OUTPUT_DATASET_FILE, serialized_payload)
    gc.collect()

    elapsed = time.time() - start_time
    severity_counts = {}
    for inc in packaged_incidents:
        sev = inc.incident_event.severity
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    print(f"[+] SUCCESS! Master dataset packaged and validated with Pydantic in {elapsed:.3f}s.")
    print(f"    Total Incidents: {len(packaged_incidents)}")
    print(f"    Severity Breakdown: {json.dumps(severity_counts)}")
    print(f"    Exported to: '{OUTPUT_DATASET_FILE}'\n")

if __name__ == "__main__":
    package_dataset()
