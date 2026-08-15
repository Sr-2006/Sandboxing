import json
import os
import uuid
import time
import sys
import argparse
import socket
import docker
import requests
import pika

try:
    client = docker.from_env()
except Exception:
    client = None

SERVICE_PORTS = {
    "api-gateway": 8080,
    "auth-service": 8081,
    "order-service": 8082,
    "payment-service": 8083
}

def get_service_url(service_name):
    port = SERVICE_PORTS.get(service_name)
    if not port:
        # If the service name itself is not found, try to match by prefix
        for k, v in SERVICE_PORTS.items():
            if k in service_name:
                port = v
                break
    if not port:
        raise ValueError(f"Unknown service: {service_name}")
    
    # Check if localhost port is accessible (running on host)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return f"http://localhost:{port}"
    except Exception:
        # Fall back to Docker service name routing
        return f"http://{service_name}:{port}"

def get_container(target):
    if not client:
        raise Exception("Docker client is not initialized")
    try:
        return client.containers.get(target)
    except docker.errors.NotFound:
        # Try matching by service name prefix if full container name is not passed
        for c in client.containers.list(all=True):
            if target in c.name:
                return c
        raise Exception(f"Container '{target}' not found")

# --- Fault Implementations ---

def apply_fault(fault_name, target, params=None):
    if params is None:
        params = {}
    print(f"[CHAOS ORCHESTRATOR] Applying fault '{fault_name}' on target '{target}' with params: {params}")

    if fault_name == "pause_container":
        c = get_container(target)
        c.pause()
        print(f"[CHAOS] Container {c.name} paused")

    elif fault_name == "unpause_container":
        c = get_container(target)
        c.unpause()
        print(f"[CHAOS] Container {c.name} unpaused")

    elif fault_name == "restart_container":
        c = get_container(target)
        c.restart()
        print(f"[CHAOS] Container {c.name} restarted")

    elif fault_name == "kill_container":
        c = get_container(target)
        c.kill(signal="SIGKILL")
        print(f"[CHAOS] Container {c.name} killed (SIGKILL)")

    elif fault_name == "cpu_throttle":
        c = get_container(target)
        c.update(cpu_period=100000, cpu_quota=10000)
        print(f"[CHAOS] Container {c.name} CPU throttled to 0.1")

    elif fault_name == "memory_limit":
        c = get_container(target)
        # Apply 384m limit, set memswap_limit to 384m to avoid swap conflict
        c.update(mem_limit="384m", memswap_limit="384m")
        print(f"[CHAOS] Container {c.name} memory limited to 384m")

    elif fault_name == "rabbitmq_backlog":
        num_msg = int(params.get("messages", 1000))
        connection = None
        for host in ["localhost", "rabbitmq"]:
            try:
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=host, port=5672, credentials=pika.PlainCredentials('guest', 'guest'), connection_attempts=3, retry_delay=1)
                )
                break
            except Exception:
                continue
        if not connection:
            raise Exception("Could not connect to RabbitMQ broker")
        channel = connection.channel()
        channel.queue_declare(queue='chaos_queue', durable=False, exclusive=False, auto_delete=False)
        for i in range(num_msg):
            channel.basic_publish(exchange='', routing_key='chaos_queue', body=f'Chaos message {i}')
        connection.close()
        print(f"[CHAOS] Injected {num_msg} messages into chaos_queue")

    elif fault_name == "http_slow":
        url = get_service_url(target)
        delay = params.get("delayMs", 5000)
        r = requests.get(f"{url}/chaos/slow?delayMs={delay}", timeout=15)
        print(f"[CHAOS] HTTP slow response trigger: {r.status_code} - {r.text}")

    elif fault_name == "http_throw":
        url = get_service_url(target)
        err_type = params.get("type", "null-pointer")
        try:
            r = requests.get(f"{url}/chaos/throw?type={err_type}", timeout=5)
            print(f"[CHAOS] HTTP throw response trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            # Some exceptions (e.g. connection reset) will naturally cause HTTP request to drop
            print(f"[CHAOS] HTTP throw triggered connection failure (expected): {e}")

    elif fault_name == "http_memory_leak":
        url = get_service_url(target)
        mb = params.get("mb", 200)
        r = requests.get(f"{url}/chaos/memory-leak?mb={mb}", timeout=10)
        print(f"[CHAOS] HTTP memory leak trigger: {r.status_code} - {r.text}")

    elif fault_name == "http_deadlock":
        url = get_service_url(target)
        r = requests.get(f"{url}/chaos/deadlock", timeout=5)
        print(f"[CHAOS] HTTP deadlock trigger: {r.status_code} - {r.text}")

    elif fault_name == "http_sql_lock":
        url = get_service_url(target)
        r = requests.get(f"{url}/chaos/sql-lock", timeout=5)
        print(f"[CHAOS] HTTP SQL Lock trigger: {r.status_code} - {r.text}")

    elif fault_name == "http_exhaust_pool":
        url = get_service_url(target)
        r = requests.get(f"{url}/chaos/exhaust-pool", timeout=5)
        print(f"[CHAOS] HTTP pool exhaustion trigger: {r.status_code} - {r.text}")

    else:
        raise ValueError(f"Unknown fault: {fault_name}")


def recover_fault(fault_name, target, orig_config=None):
    print(f"[CHAOS ORCHESTRATOR] Recovering fault '{fault_name}' on target '{target}'")
    if orig_config is None:
        orig_config = {}

    if fault_name == "pause_container":
        c = get_container(target)
        if c.status == "paused":
            c.unpause()
            print(f"[CHAOS] Container {c.name} unpaused")

    elif fault_name == "cpu_throttle":
        c = get_container(target)
        orig_period = orig_config.get("cpu_period", 100000)
        orig_quota = orig_config.get("cpu_quota", -1)
        c.update(cpu_period=orig_period, cpu_quota=orig_quota)
        print(f"[CHAOS] Container {c.name} CPU limit restored to period={orig_period}, quota={orig_quota}")

    elif fault_name == "memory_limit":
        c = get_container(target)
        # Restore original memory limits
        orig_mem = orig_config.get("memory", 0)
        orig_memswap = orig_config.get("memswap", 0)
        c.update(mem_limit=orig_mem, memswap_limit=orig_memswap)
        print(f"[CHAOS] Container {c.name} memory limit restored to {orig_mem} (swap: {orig_memswap})")

    elif fault_name == "rabbitmq_backlog":
        connection = None
        for host in ["localhost", "rabbitmq"]:
            try:
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=host, port=5672, credentials=pika.PlainCredentials('guest', 'guest'), connection_attempts=3, retry_delay=1)
                )
                break
            except Exception:
                continue
        if connection:
            channel = connection.channel()
            try:
                channel.queue_purge(queue='chaos_queue')
                channel.queue_delete(queue='chaos_queue')
                print("[CHAOS] Purged and deleted chaos_queue successfully")
            except Exception as e:
                print(f"[WARNING] Failed to clean rabbitmq queue: {e}")
            finally:
                connection.close()

    elif fault_name == "http_memory_leak":
        url = get_service_url(target)
        r = requests.get(f"{url}/chaos/memory-leak/clear", timeout=10)
        print(f"[CHAOS] HTTP memory leak cleared: {r.status_code} - {r.text}")

    elif fault_name == "http_deadlock":
        url = get_service_url(target)
        r = requests.get(f"{url}/chaos/deadlock/clear", timeout=10)
        print(f"[CHAOS] HTTP deadlock cleared: {r.status_code} - {r.text}")

    elif fault_name in ["unpause_container", "restart_container", "kill_container", "http_slow", "http_throw", "http_sql_lock", "http_exhaust_pool"]:
        # These faults are either self-healing, process restarts, or don't require recovery step
        print(f"[CHAOS] No recovery required for '{fault_name}'")
    
    else:
        print(f"[CHAOS] Unknown recovery for fault: {fault_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARA Chaos Orchestrator CLI")
    parser.add_argument("--fault", type=str, required=True, help="Chaos fault type")
    parser.add_argument("--target", type=str, required=True, help="Target container name or HTTP service name")
    parser.add_argument("--recover", action="store_true", help="Recover the specified fault")
    parser.add_argument("--params", type=str, default="{}", help="JSON params string")
    args = parser.parse_args()

    try:
        params_dict = json.loads(args.params)
    except Exception:
        params_dict = {}

    try:
        if args.recover:
            # For manual CLI recovery, we don't have orig_config state easily unless passed. We assume defaults.
            # E.g. we query current container status to guess recovery parameters
            orig_params = {}
            if args.fault == "memory_limit" or args.fault == "cpu_throttle":
                c = get_container(args.target)
                # If we're updating memory/cpu, we restore to container default limits from config
                if "api-gateway" in c.name:
                    orig_params = {"memory": "512m", "memswap": "512m", "cpu_period": 100000, "cpu_quota": -1}
                elif "auth-service" in c.name:
                    orig_params = {"memory": "384m", "memswap": "384m", "cpu_period": 100000, "cpu_quota": -1}
                elif "order-service" in c.name or "payment-service" in c.name:
                    orig_params = {"memory": "512m", "memswap": "512m", "cpu_period": 100000, "cpu_quota": -1}
                else:
                    orig_params = {"memory": 0, "memswap": 0, "cpu_period": 100000, "cpu_quota": -1}
            recover_fault(args.fault, args.target, orig_params)
        else:
            apply_fault(args.fault, args.target, params_dict)
    except Exception as e:
        print(f"[ERROR] Chaos Orchestrator command execution failed: {e}")
        sys.exit(1)