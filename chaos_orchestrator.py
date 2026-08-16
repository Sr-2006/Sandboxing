#!/usr/bin/env python3
import json
import os
import sys
import argparse
import socket
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import docker
import docker.errors
import requests
import requests.exceptions
import pika
import pika.exceptions

from utils import record_chaos_event, get_logger

logger = get_logger("chaos_orchestrator")

try:
    client = docker.from_env()
except docker.errors.DockerException as e:
    logger.warning(f"Docker client could not be initialized from env: {e}")
    client = None

TARGET_HOST = os.environ.get("TARGET_HOST", "localhost")
RABBITMQ_USER = os.environ.get("RABBITMQ_DEFAULT_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_DEFAULT_PASS", "guest")
CHAOS_SECRET = os.environ.get("CHAOS_SECRET", "dev-chaos-token")

SERVICE_PORTS = {
    "api-gateway": 8080,
    "auth-service": 8081,
    "order-service": 8082,
    "payment-service": 8083
}

def get_service_url(service_name: str) -> str:
    port = SERVICE_PORTS.get(service_name)
    if not port:
        for k, v in SERVICE_PORTS.items():
            if k in service_name:
                port = v
                break
    if not port:
        raise ValueError(f"Unknown service: {service_name}")
    
    # Check if target host port is accessible
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect((TARGET_HOST, port))
        s.close()
        return f"http://{TARGET_HOST}:{port}"
    except (socket.error, OSError):
        # Fall back to Docker service name routing
        return f"http://{service_name}:{port}"

def get_container(target: str):
    if not client:
        raise docker.errors.DockerException("Docker client is not initialized")
    try:
        return client.containers.get(target)
    except docker.errors.NotFound:
        for c in client.containers.list(all=True):
            if target in c.name:
                return c
        raise docker.errors.NotFound(f"Container '{target}' not found")

def log_chaos_event(
    fault_name: str,
    target: str,
    start_ts: str,
    end_ts: str,
    params: Optional[Dict[str, Any]],
    duration: float,
    status: str = "injected",
    scenario_id: str = "adhoc"
) -> None:
    try:
        record_chaos_event(
            fault_name=fault_name,
            target=target,
            start_ts=start_ts,
            end_ts=end_ts,
            params=params or {},
            duration_s=duration,
            status=status,
            scenario_id=scenario_id
        )
    except Exception as e:
        logger.error(f"Failed to record chaos history: {e}")

# --- Fault Implementations ---

def apply_fault(fault_name: str, target: str, params: Optional[Dict[str, Any]] = None, scenario_id: str = "adhoc") -> None:
    if params is None:
        params = {}
    
    start_time = datetime.now(timezone.utc)
    start_ts = start_time.isoformat()
    logger.info(f"Applying fault '{fault_name}' on target '{target}' with params: {params}")

    headers = {"X-Chaos-Token": CHAOS_SECRET}

    if fault_name == "pause_container":
        c = get_container(target)
        c.pause()
        logger.info(f"Container {c.name} paused")

    elif fault_name == "unpause_container":
        c = get_container(target)
        c.unpause()
        logger.info(f"Container {c.name} unpaused")

    elif fault_name == "restart_container":
        c = get_container(target)
        c.restart()
        logger.info(f"Container {c.name} restarted")

    elif fault_name == "kill_container":
        c = get_container(target)
        c.kill(signal="SIGKILL")
        logger.info(f"Container {c.name} killed (SIGKILL)")

    elif fault_name == "cpu_throttle":
        c = get_container(target)
        c.update(cpu_period=100000, cpu_quota=10000)
        logger.info(f"Container {c.name} CPU throttled to 0.1")

    elif fault_name == "memory_limit":
        c = get_container(target)
        c.update(mem_limit="384m", memswap_limit="384m")
        logger.info(f"Container {c.name} memory limited to 384m")

    elif fault_name == "network_latency":
        c = get_container(target)
        latency_ms = params.get("latency_ms", 200)
        try:
            c.exec_run(f"tc qdisc add dev eth0 root netem delay {latency_ms}ms")
            logger.info(f"Container {c.name} injected {latency_ms}ms network latency via tc")
        except Exception as e:
            logger.warning(f"Could not inject tc latency (missing cap_add NET_ADMIN?): {e}")

    elif fault_name == "rabbitmq_backlog":
        num_msg = int(params.get("messages", 1000))
        connection = None
        for host in [TARGET_HOST, "rabbitmq"]:
            try:
                credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=host, port=5672, credentials=credentials, connection_attempts=3, retry_delay=1)
                )
                break
            except (pika.exceptions.AMQPError, socket.error, OSError):
                continue
        if not connection:
            raise pika.exceptions.AMQPConnectionError("Could not connect to RabbitMQ broker")
        channel = connection.channel()
        channel.queue_declare(queue='chaos_queue', durable=False, exclusive=False, auto_delete=False)
        for i in range(num_msg):
            channel.basic_publish(exchange='', routing_key='chaos_queue', body=f'Chaos message {i}')
        connection.close()
        logger.info(f"Injected {num_msg} messages into chaos_queue")

    elif fault_name == "http_slow":
        url = get_service_url(target)
        delay = params.get("delayMs", 5000)
        try:
            r = requests.get(f"{url}/chaos/slow?delayMs={delay}", headers=headers, timeout=15)
            logger.info(f"HTTP slow response trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP slow request dropped or timed out (expected in chaos): {e}")

    elif fault_name == "http_throw":
        url = get_service_url(target)
        err_type = params.get("type", "null-pointer")
        try:
            r = requests.get(f"{url}/chaos/throw?type={err_type}", headers=headers, timeout=5)
            logger.info(f"HTTP throw response trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.info(f"HTTP throw triggered connection failure (expected): {e}")

    elif fault_name == "http_memory_leak":
        url = get_service_url(target)
        mb = params.get("mb", 150)
        try:
            r = requests.get(f"{url}/chaos/memory-leak?mb={mb}", headers=headers, timeout=10)
            logger.info(f"HTTP memory leak trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP memory leak trigger error: {e}")

    elif fault_name == "http_deadlock":
        url = get_service_url(target)
        try:
            r = requests.get(f"{url}/chaos/deadlock", headers=headers, timeout=5)
            logger.info(f"HTTP deadlock trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP deadlock trigger error: {e}")

    elif fault_name == "http_sql_lock":
        url = get_service_url(target)
        try:
            r = requests.get(f"{url}/chaos/sql-lock", headers=headers, timeout=5)
            logger.info(f"HTTP SQL lock trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP SQL lock trigger error: {e}")

    elif fault_name == "http_exhaust_pool":
        url = get_service_url(target)
        try:
            r = requests.get(f"{url}/chaos/exhaust-pool", headers=headers, timeout=5)
            logger.info(f"HTTP pool exhaustion trigger: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP pool exhaustion trigger error: {e}")

    else:
        raise ValueError(f"Unknown fault: {fault_name}")

    end_time = datetime.now(timezone.utc)
    end_ts = end_time.isoformat()
    duration = (end_time - start_time).total_seconds()
    log_chaos_event(fault_name, target, start_ts, end_ts, params, max(duration, 1.0), status="injected", scenario_id=scenario_id)

def recover_fault(fault_name: str, target: str, orig_config: Optional[Dict[str, Any]] = None, scenario_id: str = "adhoc") -> None:
    logger.info(f"Recovering fault '{fault_name}' on target '{target}'")
    if orig_config is None:
        orig_config = {}

    start_time = datetime.now(timezone.utc)
    start_ts = start_time.isoformat()
    headers = {"X-Chaos-Token": CHAOS_SECRET}

    if fault_name == "pause_container":
        c = get_container(target)
        c.unpause()
        logger.info(f"Container {c.name} unpaused (recovered)")

    elif fault_name == "kill_container":
        c = get_container(target)
        c.start()
        logger.info(f"Container {c.name} restarted (recovered)")

    elif fault_name == "cpu_throttle":
        c = get_container(target)
        c.update(cpu_period=100000, cpu_quota=-1)
        logger.info(f"Container {c.name} CPU quota restored to unlimited")

    elif fault_name == "memory_limit":
        c = get_container(target)
        orig_mem = orig_config.get("memory", 0)
        orig_memswap = orig_config.get("memswap", 0)
        c.update(mem_limit=orig_mem, memswap_limit=orig_memswap)
        logger.info(f"Container {c.name} memory limit restored to {orig_mem} (swap: {orig_memswap})")

    elif fault_name == "network_latency":
        c = get_container(target)
        try:
            c.exec_run("tc qdisc del dev eth0 root")
            logger.info(f"Container {c.name} network latency removed")
        except Exception as e:
            logger.warning(f"Could not remove tc latency: {e}")

    elif fault_name == "rabbitmq_backlog":
        connection = None
        for host in [TARGET_HOST, "rabbitmq"]:
            try:
                credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=host, port=5672, credentials=credentials, connection_attempts=3, retry_delay=1)
                )
                break
            except (pika.exceptions.AMQPError, socket.error, OSError):
                continue
        if connection:
            channel = connection.channel()
            try:
                channel.queue_purge(queue='chaos_queue')
                channel.queue_delete(queue='chaos_queue')
                logger.info("Purged and deleted chaos_queue successfully")
            except (pika.exceptions.AMQPError, socket.error, OSError) as e:
                logger.warning(f"Failed to clean rabbitmq queue: {e}")
            finally:
                connection.close()

    elif fault_name == "http_memory_leak":
        url = get_service_url(target)
        try:
            r = requests.get(f"{url}/chaos/memory-leak/clear", headers=headers, timeout=10)
            logger.info(f"HTTP memory leak cleared: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP memory leak clear request failed: {e}")

    elif fault_name == "http_deadlock":
        url = get_service_url(target)
        try:
            r = requests.get(f"{url}/chaos/deadlock/clear", headers=headers, timeout=10)
            logger.info(f"HTTP deadlock cleared: {r.status_code} - {r.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP deadlock clear request failed: {e}")

    elif fault_name == "http_sql_lock":
        logger.info("Recovery type for 'http_sql_lock': passive (DB sleep lock expires automatically)")
        end_time = datetime.now(timezone.utc)
        end_ts = end_time.isoformat()
        log_chaos_event(
            "http_sql_lock",
            target,
            start_ts,
            end_ts,
            {"recovery_type": "passive"},
            duration=10.0,
            status="recovered",
            scenario_id=scenario_id
        )
        return

    elif fault_name in ["unpause_container", "restart_container", "kill_container", "http_slow", "http_throw", "http_exhaust_pool"]:
        logger.info(f"No recovery required for '{fault_name}'")
    
    else:
        logger.warning(f"Unknown recovery for fault: {fault_name}")

    end_time = datetime.now(timezone.utc)
    end_ts = end_time.isoformat()
    duration = (end_time - start_time).total_seconds()
    log_chaos_event(fault_name, target, start_ts, end_ts, orig_config, max(duration, 1.0), status="recovered", scenario_id=scenario_id)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARA Chaos Orchestrator CLI")
    parser.add_argument("--fault", type=str, required=True, help="Chaos fault type")
    parser.add_argument("--target", type=str, required=True, help="Target container name or HTTP service name")
    parser.add_argument("--recover", action="store_true", help="Recover the specified fault")
    parser.add_argument("--params", type=str, default="{}", help="JSON params string")
    args = parser.parse_args()

    try:
        params_dict = json.loads(args.params)
    except (json.JSONDecodeError, TypeError):
        params_dict = {}

    try:
        if args.recover:
            orig_params = {}
            if args.fault in ("memory_limit", "cpu_throttle"):
                c = get_container(args.target)
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
    except (docker.errors.DockerException, requests.exceptions.RequestException, pika.exceptions.AMQPError, ValueError) as e:
        logger.error(f"Chaos Orchestrator command execution failed: {e}")
        sys.exit(1)