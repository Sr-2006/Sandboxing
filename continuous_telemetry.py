import docker
import json
import os
from datetime import datetime, timezone, timedelta
import time

client = docker.from_env()
DUMP_DIR = "telemetry_dumps"
POLL_INTERVAL = 5

if not os.path.exists(DUMP_DIR):
    os.makedirs(DUMP_DIR)

last_poll_time = datetime.now(timezone.utc) - timedelta(seconds=POLL_INTERVAL)

def get_backend_containers():
    return client.containers.list(all=True, filters={"label": "ara.topology.group=backend"})

def run_telemetry_loop():
    global last_poll_time
    
    while True:
        current_poll_time = datetime.now(timezone.utc)
        timestamp_str = current_poll_time.strftime("%Y%m%d_%H%M%S")
        batch_dir = os.path.join(DUMP_DIR, f"batch_{timestamp_str}")
        os.makedirs(batch_dir, exist_ok=True)

        containers = get_backend_containers()
        network_state = []
        
        for container in containers:
            state_info = {
                "id": container.id[:12],
                "name": container.name,
                "status": container.status,
                "health": container.attrs.get("State", {}).get("Health", {}).get("Status", "unknown")
            }
            network_state.append(state_info)
            
            if container.status == "running":
                stats = container.stats(stream=False)
                with open(os.path.join(batch_dir, f"{container.name}_metrics.json"), "w") as f:
                    json.dump(stats, f)
                    
            logs = container.logs(
                since=int(last_poll_time.timestamp()),
                until=int(current_poll_time.timestamp())
            )
            
            if logs:
                with open(os.path.join(batch_dir, f"{container.name}_logs.txt"), "wb") as f:
                    f.write(logs)
        
        with open(os.path.join(batch_dir, "network_state.json"), "w") as f:
            json.dump(network_state, f, indent=4)
            
        last_poll_time = current_poll_time
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_telemetry_loop()