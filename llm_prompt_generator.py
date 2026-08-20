import os
import json
import hashlib
import yaml

# Updated File Paths matching Phase 1 architecture
DATASET_PATH = os.path.join("frontend_data", "unified_master_dataset.json") # Often placed in frontend_data or ml_dataset
# Fallback if it is in ml_dataset
if not os.path.exists(DATASET_PATH):
    DATASET_PATH = os.path.join("ml_dataset", "unified_master_dataset.json")

COMPOSE_PATH = "docker-compose.yml"
CHAOS_STATE_PATH = os.path.join("frontend_data", "chaos_history.json")
OUTPUT_PATH = "llm_agent_prompt.json"

def parse_dynamic_topology(target_service):
    """Dynamically reads docker-compose.yml to find real-time dependencies and ports."""
    topology = {
        "role": "microservice",
        "downstream_dependencies": [],
        "exposed_ports": []
    }
    
    if not os.path.exists(COMPOSE_PATH):
        return topology

    try:
        with open(COMPOSE_PATH, "r") as f:
            compose_data = yaml.safe_load(f)
            
        services = compose_data.get("services", {})
        service_config = services.get(target_service, {})
        
        if "depends_on" in service_config:
            if isinstance(service_config["depends_on"], list):
                topology["downstream_dependencies"] = service_config["depends_on"]
            elif isinstance(service_config["depends_on"], dict):
                topology["downstream_dependencies"] = list(service_config["depends_on"].keys())
                
        if "ports" in service_config:
            topology["exposed_ports"] = service_config["ports"]
            
        if "gateway" in target_service:
            topology["role"] = "edge-routing-and-rate-limiting"
        elif "db" in target_service or "postgres" in target_service:
            topology["role"] = "relational-database"
        elif "auth" in target_service:
            topology["role"] = "user-auth-and-jwt"
        elif "order" in target_service:
            topology["role"] = "order-management"
        elif "payment" in target_service:
            topology["role"] = "payment-processing"
            
    except Exception as e:
        print(f"[-] Warning: Failed to parse topology - {e}")
        
    return topology

def generate_deterministic_hash(service, severity, template):
    """Generates an O(1) lookup key for exact match historical memory."""
    raw_string = f"{service}::{severity}::{template}"
    return hashlib.sha256(raw_string.encode('utf-8')).hexdigest()

def build_llm_prompt():
    print("=== [Phase 2] Generating LLM Prompt & Memory Fingerprint ===")
    
    if not os.path.exists(DATASET_PATH):
        print(f"[-] Error: '{DATASET_PATH}' not found. Run Phase 1 packager first.")
        return

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # FIXED: Extract incidents array handling the new Pydantic DatasetMeta format
    incident_list = dataset.get("incidents", []) if isinstance(dataset, dict) else dataset

    if not incident_list:
        print("[-] Dataset is empty. No incidents to process.")
        return

    # Grab the highest priority incident
    top_incident = incident_list[0]
    target_service = top_incident.get("target_service", "unknown")
    
    dynamic_topology = parse_dynamic_topology(target_service)
    
    memory_hash = generate_deterministic_hash(
        target_service,
        top_incident.get("incident_severity", "UNKNOWN"),
        top_incident.get("log_pattern_template", "")
    )

    # FIXED: Read from the new chaos_history.json array
    chaos_context = "No active infrastructure mutations detected."
    if os.path.exists(CHAOS_STATE_PATH):
        with open(CHAOS_STATE_PATH, "r", encoding="utf-8") as f:
            try:
                chaos_data = json.load(f)
                if isinstance(chaos_data, list) and len(chaos_data) > 0:
                    latest_chaos = chaos_data[-1]  # Get the most recent chaos event
                    chaos_context = json.dumps(latest_chaos) # Pass the full schema object to the LLM
                elif isinstance(chaos_data, dict):
                    chaos_context = json.dumps(chaos_data)
            except Exception:
                pass

    llm_payload = {
        "system_context": {
            "objective": "Perform automated Multi-Agent Root Cause Analysis (RCA) and recommend corrective actions.",
            "environment": "Dockerized Microservices (Java/Spring Boot, PostgreSQL, Redis, RabbitMQ, OpenTelemetry)",
            "current_health_score": 70, 
            "active_warnings": 4,
            "incident_fingerprint_sha256": memory_hash 
        },
        "incident_event": {
            "incident_id": top_incident.get("incident_id"),
            "target_service": target_service,
            "priority_score": top_incident.get("incident_priority_score"),
            "severity": top_incident.get("incident_severity"),
            "occurrence_count": top_incident.get("occurrence_count")
        },
        "infrastructure_topology": dynamic_topology,
        "service_health_status": {
            "docker_status": top_incident.get("service_health_at_capture", {}).get("docker_status"),
            "health_check": top_incident.get("service_health_at_capture", {}).get("health_check"),
            "dependency_states": {}
        },
        "telemetry_evidence": {
            "log_cluster_template": top_incident.get("log_pattern_template"),
            "log_samples": top_incident.get("associated_logs_samples", [])[-2:], 
            "metrics_snapshot": top_incident.get("service_performance_samples", [])[-2:]
        },
        "injected_chaos_context": {
            "active_infrastructure_mutations": chaos_context
        },
        "agent_instruction": f"Analyze the provided telemetry evidence and dependency states. Determine the root cause of the failure in the {target_service} and output a remediation plan."
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(llm_payload, f, indent=4)

    print(f"[+] Success! Generated prompt with SHA-256 Fingerprint: {memory_hash}")
    print(f"[+] Output saved to: {OUTPUT_PATH}")

if __name__ == "__main__":
    build_llm_prompt()