#!/usr/bin/env python3
"""
shadow_sandbox/faults/fault_injector.py

Standalone fault injection module operating exclusively on shadow containers.
Enforces strict shadow- target name assertions on all operations.
"""

import json
import os
import sys
import time
import socket
import signal
import subprocess
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import docker

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "fault_history.json")

# Global holder for active held DB connection threads/sockets
HELD_CONNECTIONS: List[socket.socket] = []
HELD_LOCK = threading.Lock()


def assert_shadow_target(target: str) -> str:
    """Hard safety rule: Refuses to operate on any target not prefixed 'shadow-'."""
    if not target or not target.startswith("shadow-"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Refusing to inject/recover fault on non-shadow target '{target}'"
        )
    return target


def get_docker_client() -> docker.DockerClient:
    """Returns a connected Docker SDK client."""
    return docker.from_env()


def get_container(target: str):
    """Fetches a Docker container object after verifying shadow prefix."""
    target = assert_shadow_target(target)
    client = get_docker_client()
    return client.containers.get(target)


def get_baseline_state(target: str) -> Dict[str, Any]:
    """Captures before-state snapshot of target container/service."""
    target = assert_shadow_target(target)
    client = get_docker_client()
    try:
        container = client.containers.get(target)
        inspect = container.attrs
        state = inspect.get("State", {})
        host_config = inspect.get("HostConfig", {})

        baseline = {
            "target": target,
            "status": state.get("Status"),
            "running": state.get("Running"),
            "paused": state.get("Paused"),
            "memory_limit_bytes": host_config.get("Memory"),
            "nano_cpus": host_config.get("NanoCpus"),
            "cpu_quota": host_config.get("CpuQuota"),
            "captured_at": datetime.now(timezone.utc).isoformat()
        }

        # Check real active DB client connections directly from shadow-postgres-db
        if target == "shadow-postgres-db":
            held_count = 0
            try:
                res = container.exec_run(["psql", "-U", "postgres", "-t", "-c", "SELECT count(1) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname IS NOT NULL;"])
                if res.exit_code == 0:
                    held_count = int(res.output.decode("utf-8", errors="ignore").strip())
            except Exception:
                held_count = 0
            baseline["held_connections_count"] = held_count
            baseline["active_connections"] = held_count

        return baseline
    except Exception as e:
        return {"target": target, "error": str(e), "captured_at": datetime.now(timezone.utc).isoformat()}


def log_fault_event(incident_id: str, fault_type: str, target: str, parameters: Dict[str, Any], before_state: Dict[str, Any], active: bool = True):
    """Appends/updates entry in shadow_sandbox/faults/fault_history.json."""
    assert_shadow_target(target)
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    record = {
        "incident_id": incident_id,
        "fault_type": fault_type,
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parameters": parameters,
        "before_state": before_state,
        "active": active
    }

    # Deactivate existing active faults for this target if new fault applied
    if active:
        for item in history:
            if item.get("target") == target and item.get("active"):
                item["active"] = False

    history.append(record)

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


# ==============================================================================
# DOCKER-SDK FAULT PRIMITIVES
# ==============================================================================

def cpu_throttle(target: str, quota_percent: int = 20) -> Dict[str, Any]:
    """Throttles target container CPU (e.g. 20% limit)."""
    target = assert_shadow_target(target)
    container = get_container(target)

    # 100,000 quota period standard; 20% = 20,000 quota
    quota = int(quota_percent * 1000)
    container.update(cpu_quota=quota, cpu_period=100000)
    return {"target": target, "fault": "cpu_throttle", "quota_percent": quota_percent}


def memory_limit(target: str, limit_mb: int = 64) -> Dict[str, Any]:
    """Limits container memory (e.g. 64M)."""
    target = assert_shadow_target(target)
    container = get_container(target)
    mem_bytes = limit_mb * 1024 * 1024
    container.update(mem_limit=mem_bytes, memswap_limit=mem_bytes)
    return {"target": target, "fault": "memory_limit", "limit_mb": limit_mb}


def network_latency(target: str, latency_ms: int = 500) -> Dict[str, Any]:
    """Injects network latency via tc netem inside shadow container."""
    target = assert_shadow_target(target)
    container = get_container(target)

    # Reset any existing tc qdisc first
    container.exec_run("tc qdisc del dev eth0 root", user="root")
    cmd = f"tc qdisc add dev eth0 root netem delay {latency_ms}ms"
    res = container.exec_run(cmd, user="root")

    return {
        "target": target,
        "fault": "network_latency",
        "latency_ms": latency_ms,
        "exit_code": res.exit_code,
        "output": res.output.decode("utf-8", errors="ignore")
    }


def restart_container(target: str) -> Dict[str, Any]:
    """Restarts target shadow container."""
    target = assert_shadow_target(target)
    container = get_container(target)
    container.restart(timeout=10)
    return {"target": target, "fault": "restart_container", "status": "restarted"}


def pause_container(target: str) -> Dict[str, Any]:
    """Pauses execution of target shadow container."""
    target = assert_shadow_target(target)
    container = get_container(target)
    container.pause()
    return {"target": target, "fault": "pause_container", "status": "paused"}


def unpause_container(target: str) -> Dict[str, Any]:
    """Unpauses execution of target shadow container."""
    target = assert_shadow_target(target)
    container = get_container(target)
    container.unpause()
    return {"target": target, "fault": "unpause_container", "status": "unpaused"}


def rabbitmq_backlog(target: str, message_count: int = 1000) -> Dict[str, Any]:
    """Injects message backlog into RabbitMQ container."""
    target = assert_shadow_target(target)
    container = get_container(target)

    # Use rabbitmqadmin or python execution inside container to publish dummy messages
    cmd = f"python3 -c \"import pika; conn=pika.BlockingConnection(pika.ConnectionParameters('localhost')); ch=conn.channel(); ch.queue_declare(queue='order_queue'); [ch.basic_publish(exchange='', routing_key='order_queue', body='backlog_msg') for _ in range({message_count})]; conn.close()\""
    res = container.exec_run(f"sh -c \"{cmd}\"")

    return {
        "target": target,
        "fault": "rabbitmq_backlog",
        "message_count": message_count,
        "exit_code": res.exit_code
    }


PID_FILE = os.path.join(os.path.dirname(__file__), "pg_hold.pid")


def exhaust_postgres_connections(target: str = "shadow-postgres-db", connection_count: int = 100, host: str = "127.0.0.1", port: int = 15432) -> Dict[str, Any]:
    """
    Opens connection_count TCP connections to Postgres in a detached background daemon process
    to exhaust available max_connections pool until explicitly recovered.
    """
    assert_shadow_target(target)

    # Close previous daemon connections first
    close_exhausted_connections(target)

    # Launch detached background daemon process
    cmd = [sys.executable, "-m", "shadow_sandbox.faults.pg_hold_daemon", target, str(connection_count)]
    kwargs = {}
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, cwd=repo_root, **kwargs)

    # Wait up to 2 seconds for PID file to be written by daemon
    opened = 0
    for _ in range(20):
        time.sleep(0.1)
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    opened = meta.get("count_opened", 0)
                    break
            except Exception:
                pass

    return {
        "target": target,
        "fault": "exhaust_postgres_connections",
        "requested": connection_count,
        "opened_held": opened
    }


# ==============================================================================
# RECOVERY PRIMITIVES
# ==============================================================================

def recover_cpu_throttle(target: str) -> Dict[str, Any]:
    """Resets CPU quota to unthrottled."""
    target = assert_shadow_target(target)
    container = get_container(target)
    container.update(cpu_quota=0)
    return {"target": target, "recovery": "recover_cpu_throttle", "status": "reset"}


def recover_memory_limit(target: str) -> Dict[str, Any]:
    """Resets memory limit to unconstrained/default."""
    target = assert_shadow_target(target)
    container = get_container(target)
    container.update(mem_limit=0, memswap_limit=0)
    return {"target": target, "recovery": "recover_memory_limit", "status": "reset"}


def recover_network_latency(target: str) -> Dict[str, Any]:
    """Removes tc netem latency rules."""
    target = assert_shadow_target(target)
    container = get_container(target)
    res = container.exec_run("tc qdisc del dev eth0 root", user="root")
    return {
        "target": target,
        "recovery": "recover_network_latency",
        "exit_code": res.exit_code,
        "status": "cleared"
    }


def close_exhausted_connections(target: str = "shadow-postgres-db") -> Dict[str, Any]:
    """
    Closes all held TCP connections by terminating the background daemon AND executing
    SELECT pg_terminate_backend(pid) directly on shadow-postgres-db.
    Reports closed_count based strictly on a live before/after SQL query comparison.
    """
    assert_shadow_target(target)
    container = get_container(target)

    # 1. Live query client connection count BEFORE recovery
    conn_before = 0
    try:
        res_b = container.exec_run(["psql", "-U", "postgres", "-t", "-c", "SELECT count(1) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname IS NOT NULL;"])
        if res_b.exit_code == 0:
            conn_before = int(res_b.output.decode("utf-8", errors="ignore").strip())
    except Exception:
        conn_before = 0

    # 2. Terminate background daemon process if running
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                meta = json.load(f)
            pid = meta.get("pid")
            if pid:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass

    # 3. Terminate backend connection processes directly inside Postgres
    try:
        term_sql = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname IS NOT NULL;"
        container.exec_run(["psql", "-U", "postgres", "-t", "-c", term_sql])
    except Exception:
        pass

    # 4. Live query client connection count AFTER recovery
    conn_after = 0
    try:
        res_a = container.exec_run(["psql", "-U", "postgres", "-t", "-c", "SELECT count(1) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname IS NOT NULL;"])
        if res_a.exit_code == 0:
            conn_after = int(res_a.output.decode("utf-8", errors="ignore").strip())
    except Exception:
        conn_after = 0

    closed_count = max(0, conn_before - conn_after)

    return {
        "target": target,
        "recovery": "close_exhausted_connections",
        "closed_count": closed_count,
        "connections_before": conn_before,
        "connections_after": conn_after
    }


def recover_rabbitmq_backlog(target: str = "shadow-rabbitmq") -> Dict[str, Any]:
    """Purges RabbitMQ queues to clear backlog."""
    target = assert_shadow_target(target)
    container = get_container(target)
    res = container.exec_run("rabbitmqctl purge_queue order_queue")
    return {"target": target, "recovery": "recover_rabbitmq_backlog", "exit_code": res.exit_code}


def recover_all(target: str) -> Dict[str, Any]:
    """Master recovery routine: Resets persistent state faults for target."""
    target = assert_shadow_target(target)
    results = {}

    try:
        container = get_container(target)
        if container.status == "paused":
            container.unpause()
            results["unpause"] = "success"
    except Exception as e:
        results["unpause_error"] = str(e)

    try:
        results["cpu"] = recover_cpu_throttle(target)
    except Exception as e:
        results["cpu_error"] = str(e)

    try:
        results["net"] = recover_network_latency(target)
    except Exception as e:
        results["net_error"] = str(e)

    if target == "shadow-postgres-db":
        results["db_connections"] = close_exhausted_connections(target)

    if target == "shadow-rabbitmq":
        results["queue_backlog"] = recover_rabbitmq_backlog(target)

    return {"target": target, "master_recovery": results}
