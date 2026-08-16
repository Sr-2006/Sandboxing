import time
import random
import uuid
import os
import argparse
import gc
import docker

import chaos_orchestrator
from utils import get_logger

logger = get_logger("chaos_scenarios")

try:
    client = docker.from_env()
except Exception:
    client = None

CONTAINERS = ["api-gateway", "auth-service", "order-service", "payment-service", "postgres-db", "redis", "rabbitmq"]
HTTP_SERVICES = ["api-gateway", "auth-service", "order-service", "payment-service"]

# 13-type chaos orchestration catalog
FAULTS_CATALOG = [
    ("pause_container", "container", lambda: {}),
    ("restart_container", "container", lambda: {}),
    ("kill_container", "container", lambda: {}),
    ("cpu_throttle", "container", lambda: {}),
    ("memory_limit", "container", lambda: {}),
    ("network_latency", "container", lambda: {"latency_ms": 200}),
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
        container = chaos_orchestrator.get_container(container_name)
        host_config = container.attrs.get("HostConfig", {})
        return {
            "memory": host_config.get("Memory", 0),
            "memswap": host_config.get("MemorySwap", 0),
            "cpu_period": host_config.get("CpuPeriod", 0),
            "cpu_quota": host_config.get("CpuQuota", -1)
        }
    except Exception as e:
        logger.warning(f"Could not get original limits for {container_name}: {e}")
        return {"memory": 0, "memswap": 0, "cpu_period": 0, "cpu_quota": -1}

def select_and_run_scenario():
    scenario_id = str(uuid.uuid4())
    
    # Choose 2 or 3 distinct faults targeting different layers
    num_faults = random.choice([2, 3])
    selected_faults = random.sample(FAULTS_CATALOG, num_faults)
    
    injected = []
    targets_used = set()
    duration = random.randint(30, 120)
    
    logger.info(f"=== Starting Scenario {scenario_id} (Duration: {duration}s) ===")
    
    # Track original configs for recovery
    original_configs = {}
    
    try:
        for fault_name, target_type, param_gen in selected_faults:
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
            
            if fault_name in ("memory_limit", "cpu_throttle"):
                original_configs[target] = get_original_limits(target)
                
            try:
                chaos_orchestrator.apply_fault(fault_name, target, params)
                injected.append({
                    "fault": fault_name,
                    "target": target,
                    "params": params
                })
            except Exception as ex:
                logger.error(f"Failed to inject {fault_name} on {target}: {ex}")
                
        if not injected:
            logger.warning("No faults were successfully injected. Aborting scenario.")
            return
            
        logger.info(f"Sleeping for {duration} seconds while faults run...")
        time.sleep(duration)
        
    finally:
        logger.info("=== Recovering all injected faults ===")
        for inj in injected:
            fault_name = inj["fault"]
            target = inj["target"]
            orig_cfg = original_configs.get(target, None)
            try:
                chaos_orchestrator.recover_fault(fault_name, target, orig_cfg)
            except Exception as ex:
                logger.error(f"Failed to recover {fault_name} on {target}: {ex}")
                
    # If a container was killed, restart it to leave cluster in healthy state
    for inj in injected:
        if inj["fault"] == "kill_container":
            try:
                logger.info(f"Restarting killed container: {inj['target']}")
                c = chaos_orchestrator.get_container(inj["target"])
                c.start()
            except Exception as ex:
                logger.error(f"Failed to restart killed container {inj['target']}: {ex}")
                
    gc.collect()
    logger.info(f"Scenario {scenario_id} finished successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARA Chaos Scenarios Executor")
    parser.add_argument("--interval", type=int, default=60, help="Interval between scenarios in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single scenario and exit")
    parser.add_argument("--scenario", type=str, default="", help="Run named scenario e.g. smoke")
    args = parser.parse_args()
    
    if args.once or args.scenario:
        select_and_run_scenario()
    else:
        logger.info(f"Starting chaos loop with scenario interval: {args.interval}s")
        while True:
            try:
                select_and_run_scenario()
            except KeyboardInterrupt:
                logger.info("Chaos loop stopped by user.")
                break
            except Exception as e:
                logger.error(f"Error in chaos loop: {e}")
            time.sleep(args.interval)
