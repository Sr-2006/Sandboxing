import os
import json
import time
import hashlib
import tempfile
from datetime import datetime

DUMP_DIR = "telemetry_dumps"
OUTPUT_DIR = "frontend_data"
MAX_RECORDS = 500

def get_latest_batch_dir():
    try:
        dirs = [os.path.join(DUMP_DIR, d) for d in os.listdir(DUMP_DIR) if d.startswith("batch_")]
        if not dirs:
            return None
        return max(dirs, key=os.path.getmtime)
    except Exception:
        return None

def calculate_cpu_percent(stats):
    try:
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
        if system_delta > 0.0 and cpu_delta > 0.0:
            return (cpu_delta / system_delta) * len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100.0
    except KeyError:
        pass
    return 0.0

def atomic_write(filepath, data):
    dir_name = os.path.dirname(filepath)
    os.makedirs(dir_name, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_name)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=4)
    os.replace(temp_path, filepath)

def read_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return []

def run_sync_loop():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    empty_schemas = {
        "causality.json": {"root_cause": "", "confidence": 0, "evidence": []},
        "cost_and_roi.json": {"estimated_cost": 0.0, "impact": "none"},
        "analytics.json": {"system_health_score": 100, "active_warnings": 0}
    }
    
    for filename, schema in empty_schemas.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(filepath):
            atomic_write(filepath, schema)

    while True:
        latest_batch = get_latest_batch_dir()
        if latest_batch:
            time_series_path = os.path.join(OUTPUT_DIR, "time_series.json")
            events_path = os.path.join(OUTPUT_DIR, "events_and_incidents.json")
            status_path = os.path.join(OUTPUT_DIR, "status.json")

            time_series_data = read_json(time_series_path)
            events_data = read_json(events_path)

            network_state_file = os.path.join(latest_batch, "network_state.json")
            if os.path.exists(network_state_file):
                with open(network_state_file, 'r') as f:
                    status_data = json.load(f)
                atomic_write(status_path, status_data)

            for filename in os.listdir(latest_batch):
                filepath = os.path.join(latest_batch, filename)
                
                if filename.endswith("_metrics.json"):
                    with open(filepath, 'r') as f:
                        stats = json.load(f)
                    
                    container_name = filename.replace("_metrics.json", "")
                    cpu_pct = calculate_cpu_percent(stats)
                    mem_usage = stats.get('memory_stats', {}).get('usage', 0)
                    
                    metric_entry = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "container": container_name,
                        "cpu_percent": cpu_pct,
                        "memory_usage": mem_usage
                    }
                    time_series_data.append(metric_entry)

                elif filename.endswith("_logs.txt"):
                    with open(filepath, 'r') as f:
                        log_content = f.read().strip()
                    
                    if log_content:
                        container_name = filename.replace("_logs.txt", "")
                        log_hash = hashlib.sha256(log_content.encode()).hexdigest()
                        
                        event_entry = {
                            "timestamp": datetime.utcnow().isoformat(),
                            "container": container_name,
                            "log_hash": log_hash,
                            "content": log_content
                        }
                        
                        if not any(e.get("log_hash") == log_hash for e in events_data):
                            events_data.append(event_entry)

            time_series_data = time_series_data[-MAX_RECORDS:]
            events_data = events_data[-MAX_RECORDS:]

            atomic_write(time_series_path, time_series_data)
            atomic_write(events_path, events_data)

        time.sleep(5)

if __name__ == "__main__":
    run_sync_loop()