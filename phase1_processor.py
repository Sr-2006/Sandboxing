import os
import json
import hashlib
import math
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.masking import MaskingInstruction

# ==========================================
# 1. DRAIN3 CONFIGURATION
# ==========================================
config = TemplateMinerConfig()

# Standardize variables like IPs, UUIDs, and numbers to group similar logs
config.masking_instructions = [
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})((?=[^A-Za-z0-9])|$)", mask_with="IP"),
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)(0x[a-fA-F0-9]+)((?=[^A-Za-z0-9])|$)", mask_with="HEX"),
    MaskingInstruction(pattern=r"((?<=[^A-Za-z0-9])|^)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})((?=[^A-Za-z0-9])|$)", mask_with="UUID"),
    MaskingInstruction(pattern=r"\d+", mask_with="NUM")
]
miner = TemplateMiner(config=config)

# ==========================================
# 2. DYNAMIC PRIORITIZATION & SEVERITY
# ==========================================
def analyze_severity(log_line):
    """Assigns base severity based on keywords."""
    line_upper = log_line.upper()
    if any(x in line_upper for x in ["OOM", "OUT OF MEMORY", "FATAL", "CONNECTION REFUSED", "TIMEOUT", "PANIC", "CONNECTION RESET"]):
        return "CRITICAL"
    elif any(x in line_upper for x in ["ERROR", "EXCEPTION", "FAILED", "SQLSTATE"]):
        return "HIGH"
    elif "WARN" in line_upper:
        return "MEDIUM"
    return "LOW"

def calculate_priority_score(severity, occurrence_count, container_state):
    """Calculates a mathematical composite priority score based on velocity and state."""
    severity_weights = {"CRITICAL": 40, "HIGH": 30, "MEDIUM": 20, "LOW": 10}
    base_score = severity_weights.get(severity, 10)
    
    # Velocity factor: Logarithmic scaling prevents high log volumes from breaking the scale
    velocity_factor = math.log10(occurrence_count + 1)
    
    # Penalty: If the container is physically down, it is an immediate priority
    state_penalty = 50 if container_state in ["exited", "paused", "unhealthy"] else 0
    
    return round((base_score * velocity_factor) + state_penalty, 2)

# ==========================================
# 3. PROCESSING & FILE GENERATION
# ==========================================
def process_json_telemetry():
    """Reads telemetry, extracts evidence, clusters logs, and outputs the final payload."""
    events_file = os.path.join("frontend_data", "events_and_incidents.json")
    status_file = os.path.join("frontend_data", "status.json")
    output_file = os.path.join("frontend_data", "processed_incidents.json")

    print(f"=== [Phase 1] Processing Inbound Telemetry ===")
    
    # Step A: Map Health Evidence from status.json
    container_state = {}
    if os.path.exists(status_file):
        with open(status_file, "r") as f:
            status_data = json.load(f)
            for item in status_data:
                container_state[item["name"]] = item["status"]

    if not os.path.exists(events_file):
        print(f"[-] Error: '{events_file}' not found. Ensure you are running this from the repository root.")
        return

    with open(events_file, "r", encoding="utf-8") as f:
        events_data = json.load(f)

    incidents = {}
    
    # Step B: Parse & Cluster Logs using Drain3
    for event in events_data:
        container_name = event.get("container", "unknown")
        current_status = container_state.get(container_name, "unknown")
        raw_content = event.get("content", "")
        
        # Slicer: Cut massive stack traces down to just the primary log header
        lines = raw_content.strip().split('\n')
        if not lines:
            continue
        main_log_line = lines[0].strip()
        
        severity = analyze_severity(main_log_line)
        
        # Noise Filter: Drop routine info logs
        if severity == "LOW":
            continue
            
        result = miner.add_log_message(main_log_line)
        drain_cluster_id = result["cluster_id"]
        template = result["template_mined"]
        
        # CRITICAL FIX: Create a composite key (e.g., "auth-service_1")
        incident_key = f"{container_name}_{drain_cluster_id}"
        
        # Group identical logs PER CONTAINER and aggregate occurrence counts
        if incident_key not in incidents:
            incidents[incident_key] = {
                "cluster_id": incident_key,  # Now outputting the unique composite ID
                "template_hash": hashlib.sha256(template.encode("utf-8")).hexdigest(),
                "template": template,
                "severity": severity,
                "source_container": container_name,
                "container_state": current_status,
                "occurrence_count": 1
            }
        else:
            incidents[incident_key]["occurrence_count"] += 1

            
    # Step C: Calculate Final Composite Priority Scores
    incident_list = list(incidents.values())
    for item in incident_list:
        item["priority_score"] = calculate_priority_score(
            item["severity"], 
            item["occurrence_count"], 
            item["container_state"]
        )

    # Sort array so the highest priority score is passed to Phase 2 first
    incident_list.sort(key=lambda x: x["priority_score"], reverse=True)

    # Step D: Construct & Write Output Payload
    payload = {
        "batch_id": "frontend_sync_batch",
        "incident_count": len(incident_list),
        "incidents": incident_list
    }

    # Export for Phase 2 integration
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[+] Success! {len(incident_list)} incidents processed and exported to '{output_file}'.\n")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    process_json_telemetry()