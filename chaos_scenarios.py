import time
import random
import uuid
import os
import argparse
import gc
import docker

import chaos_orchestrator
from utils import atomic_write_json, read_json_file, file_lock_context

try:
    client = docker.from_env()
except Exception:
    client = None

CONTAINERS = ["api-gateway", "auth-service", "order-service", "payment-service", "postgres-db", "redis", "rabbitmq"]
HTTP_SERVICES = ["api-gateway", "auth-service", "order-service", "payment-service"]

FAULTS_CATALOG = [
    ("pause_container", "container", lambda: {}),
    ("restart_container", "container", lambda: {}),
    ("kill_container", "container", lambda: {}),
    ("cpu_throttle", "container", lambda: {}),
    ("memory_limit", "container", lambda: {}),
    ("rabbitmq_backlog", "rabbitmq", lambda: {"messages": 1000}),
    ("http_slow", "http_service", lambda: {"delayMs": 5000}),
    ("http_throw", "http_service", lambda: {"type": random.choice(["null-pointer", "sql-timeout", "connection-reset"])}),
    ("http_memory_leak", "http_service", lambda: {"mb": 150}),
    ("http_deadlock", "http_service", lambda: {}),
    ("http_sql_lock", "http_service", lambda: {}),
    ("http_exhaust_pool", "http_service", lambda: {})
]

HISTORY_FILE = os.path.join("frontend_data", "chaos_history.json")

def get_original_limits(container_name):
    if not client:
        return {"memory": 0, "nano_cpus": 0}
    try:
        # Resolve prefix
        container = chaos_orchestrator.get_container(container_name)
        host_config = container.attrs.get("HostConfig", {})
        return {
            "memory": host_config.get("Memory", 0),
            "memswap": host_config.get("MemorySwap", 0),
            "cpu_period": host_config.get("CpuPeriod", 0),
            "cpu_quota": host_config.get("CpuQuota", -1)
        }
    except Exception as e:
        print(f"[WARNING] Could not get original limits for {container_name}: {e}")
        return {"memory": 0, "memswap": 0, "cpu_period": 0, "cpu_quota": -1}


def write_history_atomic(entry):
    with file_lock_context(HISTORY_FILE):
        history = read_json_file(HISTORY_FILE, [])
        if not isinstance(history, list):
            history = []
        history.append(entry)
        atomic_write_json(HISTORY_FILE, history)

def select_and_run_scenario():
    scenario_id = str(uuid.uuid4())
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    # Choose 2 or 3 distinct faults targeting different layers
    num_faults = random.choice([2, 3])
    selected_faults = random.sample(FAULTS_CATALOG, num_faults)
    
    injected = []
    targets_used = set()
    duration = random.randint(30, 120)
    
    print(f"\n[CHAOS SCENARIO] === Starting Scenario {scenario_id} (Duration: {duration}s) ===")
    
    # Track original configs for recovery
    original_configs = {}
    
    try:
        for fault_name, target_type, param_gen in selected_faults:
            # Pick a target that hasn't been used in this scenario yet
            target = None
            if target_type == "container":
                available = [c for c in CONTAINERS if c not in targets_used]
                if available:
                    target = random.choice(available)
            elif target_type == "http_service":
                available = [s for s in HTTP_SERVICES if s not in targets_used]
                if available:
                    target = random.choice(available)
            elif target_type == "rabbitmq":
                if "rabbitmq" not in targets_used:
                    target = "rabbitmq"
            
            if not target:
                continue
                
            targets_used.add(target)
            params = param_gen()
            
            # If changing container resource limits, fetch the current settings first
            if fault_name == "memory_limit" or fault_name == "cpu_throttle":
                original_configs[target] = get_original_limits(target)
                
            try:
                chaos_orchestrator.apply_fault(fault_name, target, params)
                injected.append({
                    "fault": fault_name,
                    "target": target,
                    "params": params
                })
            except Exception as ex:
                print(f"[ERROR] Failed to inject {fault_name} on {target}: {ex}")
                
        if not injected:
            print("[CHAOS SCENARIO] No faults were successfully injected. Aborting scenario.")
            return
            
        print(f"[CHAOS SCENARIO] Sleeping for {duration} seconds while faults run...")
        time.sleep(duration)
        
    finally:
        print("[CHAOS SCENARIO] === Recovering all injected faults ===")
        for inj in injected:
            fault_name = inj["fault"]
            target = inj["target"]
            orig_cfg = original_configs.get(target, None)
            try:
                chaos_orchestrator.recover_fault(fault_name, target, orig_cfg)
            except Exception as ex:
                print(f"[ERROR] Failed to recover {fault_name} on {target}: {ex}")
                
    # If a container was killed, restart it to leave cluster in healthy state
    for inj in injected:
        if inj["fault"] == "kill_container":
            try:
                print(f"[REMEDIATION] Restarting killed container: {inj['target']}")
                c = chaos_orchestrator.get_container(inj["target"])
                c.start()
            except Exception as ex:
                print(f"[ERROR] Failed to restart killed container {inj['target']}: {ex}")
                
    entry = {
        "scenario_id": scenario_id,
        "timestamp": timestamp,
        "faults": [inj["fault"] for inj in injected],
        "target_services": [inj["target"] for inj in injected],
        "duration": duration,
        "status": "completed"
    }
    
    write_history_atomic(entry)
    gc.collect()
    print(f"[CHAOS SCENARIO] Scenario {scenario_id} finished and logged successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARA Chaos Scenarios Executor")
    parser.add_argument("--interval", type=int, default=60, help="Interval between scenarios in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single scenario and exit")
    args = parser.parse_args()
    
    if args.once:
        select_and_run_scenario()
    else:
        print(f"[CHAOS SCENARIO] Starting chaos loop with scenario interval: {args.interval}s")
        while True:
            try:
                select_and_run_scenario()
            except KeyboardInterrupt:
                print("[CHAOS SCENARIO] Stopped by user.")
                break
            except Exception as e:
                print(f"[ERROR] Error in chaos loop: {e}")
            time.sleep(args.interval)
