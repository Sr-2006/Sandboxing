import asyncio
import collections
import gc
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from aiodocker import Docker
from utils import atomic_write_json

RAW_TELEMETRY_FILE = os.path.join("frontend_data", "raw_telemetry.json")
EVENTS_FILE = os.path.join("frontend_data", "events_and_incidents.json")
POLL_INTERVAL = 5.0
MAX_SEEN_LOG_HASHES = 10000
MAX_EVENTS = 5000
BUFFER_MAXLEN = 20

# Metric rolling buffers: container_name -> metric_name -> deque
buffers = collections.defaultdict(lambda: {
    "cpu_percent": collections.deque(maxlen=BUFFER_MAXLEN),
    "memory_percent": collections.deque(maxlen=BUFFER_MAXLEN),
    "network_rx_rate": collections.deque(maxlen=BUFFER_MAXLEN),
    "network_tx_rate": collections.deque(maxlen=BUFFER_MAXLEN)
})

# Previous cumulative network bytes and timestamps for rate calculation
prev_net_state = {}
seen_log_hashes = set()
seen_log_hashes_queue = collections.deque(maxlen=MAX_SEEN_LOG_HASHES)

def log_msg(msg: str):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{now_iso}] {msg}", flush=True)

def compute_z_score(buffer: collections.deque, current_val: float) -> float:
    if len(buffer) < 5:
        return 0.0
    mean = sum(buffer) / len(buffer)
    variance = sum((x - mean) ** 2 for x in buffer) / len(buffer)
    std = math.sqrt(variance)
    epsilon = 1e-6
    z = (current_val - mean) / (std + epsilon)
    return z

def parse_trace_span_ids(line: str):
    if not line:
        return None, None

    # Pass 1: JSON pass
    stripped = line.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            def find_keys(d):
                t_val, s_val = None, None
                if isinstance(d, dict):
                    t_val = d.get("trace_id") or d.get("traceId") or d.get("trace")
                    s_val = d.get("span_id") or d.get("spanId") or d.get("span")
                    if t_val and s_val:
                        return str(t_val), str(s_val)
                    for k, v in d.items():
                        if isinstance(v, dict):
                            t_sub, s_sub = find_keys(v)
                            if t_sub and s_sub:
                                return t_sub, s_sub
                return t_val, s_val
            t_id, s_id = find_keys(data)
            if t_id and s_id:
                return str(t_id), str(s_id)
        except Exception:
            pass

    # Pass 2: W3C context header pass
    w3c_match = re.search(r'trace_id=(?P<t>[a-fA-F0-9]{32}),\s*span_id=(?P<s>[a-fA-F0-9]{16})|traceparent=00-(?P<t2>[a-fA-F0-9]{32})-(?P<s2>[a-fA-F0-9]{16})-', line)
    if w3c_match:
        t_id = w3c_match.group('t') or w3c_match.group('t2')
        s_id = w3c_match.group('s') or w3c_match.group('s2')
        if t_id and s_id:
            return t_id, s_id

    # Pass 3: OTel Logback & Spring Boot Micrometer tracing patterns
    spring_micrometer_match = re.search(r'\[[\w\-\.\s]+,\s*([a-fA-F0-9]{32}),\s*([a-fA-F0-9]{16})\]', line)
    if spring_micrometer_match:
        return spring_micrometer_match.group(1), spring_micrometer_match.group(2)

    otel_match = re.search(r'\[trace_id=([a-fA-F0-9]{32}),\s*span_id=([a-fA-F0-9]{16})\]', line)
    if otel_match:
        return otel_match.group(1), otel_match.group(2)

    bracket_match = re.search(r'\[([a-fA-F0-9]{32}),\s*([a-fA-F0-9]{16})\]', line)
    if bracket_match:
        return bracket_match.group(1), bracket_match.group(2)

    if "ERROR" in line.upper() or "WARN" in line.upper():
        thread_hex_match = re.search(r'\[[\w\-\.\s]+\]\s+([a-fA-F0-9]{32})\s+([a-fA-F0-9]{16})', line)
        if thread_hex_match:
            return thread_hex_match.group(1), thread_hex_match.group(2)

        t_m = re.search(r'\b([a-fA-F0-9]{32})\b', line)
        s_m = re.search(r'\b([a-fA-F0-9]{16})\b', line)
        if t_m and s_m:
            return t_m.group(1), s_m.group(1)

    return None, None

def determine_log_level(line: str) -> str:
    line_upper = line.upper()
    if "ERROR" in line_upper or "EXCEPTION" in line_upper or "FATAL" in line_upper:
        return "ERROR"
    elif "WARN" in line_upper or "WARNING" in line_upper:
        return "WARN"
    return "INFO"

def parse_line_timestamp(line: str) -> str:
    m = re.search(r'\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|Z[+-]\d{2}:?\d{2})?)\b', line)
    if not m:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = m.group(1).replace(" ", "T")
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

async def collect_container_telemetry(container, now_ts: float):
    info = await container.show()
    raw_name = info.get("Name", "")
    container_name = raw_name.lstrip("/")

    state = info.get("State", {})
    status = state.get("Status", "unknown").lower()
    health_obj = state.get("Health", {})
    health = health_obj.get("Status") if health_obj else None
    started_at = state.get("StartedAt")
    finished_at = state.get("FinishedAt") if status != "running" else None
    exit_code = state.get("ExitCode", 0) if status != "running" else 0

    cpu_percent = 0.0
    mem_usage = 0
    mem_limit = 0
    mem_percent = 0.0
    rx_bytes = 0
    tx_bytes = 0
    rx_rate = 0.0
    tx_rate = 0.0

    if status == "running":
        try:
            raw_stats = await container.stats(stream=False)
            stats = raw_stats[0] if isinstance(raw_stats, list) and raw_stats else raw_stats

            # CPU calculation
            cpu_stats = stats.get("cpu_stats", {})
            precpu_stats = stats.get("precpu_stats", {})
            cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
            online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])) or 1
            if system_delta > 0 and cpu_delta > 0:
                cpu_percent = round((cpu_delta / system_delta) * online_cpus * 100.0, 2)
            else:
                cpu_percent = 0.0

            # Memory calculation
            mem_stats = stats.get("memory_stats", {})
            mem_usage = mem_stats.get("usage", 0)
            mem_limit = mem_stats.get("limit", 0)
            if mem_limit > 0:
                mem_percent = round((mem_usage / mem_limit) * 100.0, 2)
            else:
                mem_percent = 0.0

            # Network calculation
            networks = stats.get("networks", {})
            rx_bytes = sum(net.get("rx_bytes", 0) for net in networks.values())
            tx_bytes = sum(net.get("tx_bytes", 0) for net in networks.values())

            if container_name in prev_net_state:
                prev_rx, prev_tx, prev_t = prev_net_state[container_name]
                dt = max(0.1, now_ts - prev_t)
                rx_rate = max(0.0, round((rx_bytes - prev_rx) / dt, 2))
                tx_rate = max(0.0, round((tx_bytes - prev_tx) / dt, 2))
            
            prev_net_state[container_name] = (rx_bytes, tx_bytes, now_ts)

        except Exception as e:
            log_msg(f"Warning: Failed to fetch stats for {container_name}: {e}")

    # Update rolling buffers
    c_buffers = buffers[container_name]
    
    # Compute z-scores before appending current value (or with historical sample)
    z_cpu = compute_z_score(c_buffers["cpu_percent"], cpu_percent)
    z_mem = compute_z_score(c_buffers["memory_percent"], mem_percent)
    z_rx = compute_z_score(c_buffers["network_rx_rate"], rx_rate)
    z_tx = compute_z_score(c_buffers["network_tx_rate"], tx_rate)

    c_buffers["cpu_percent"].append(cpu_percent)
    c_buffers["memory_percent"].append(mem_percent)
    c_buffers["network_rx_rate"].append(rx_rate)
    c_buffers["network_tx_rate"].append(tx_rate)

    active_warnings = 0
    anomalies = []
    for metric_name, z_val in [("cpu", z_cpu), ("memory", z_mem), ("rx_rate", z_rx), ("tx_rate", z_tx)]:
        if abs(z_val) > 2.5:
            active_warnings += 1
            anomalies.append(abs(z_val))

    anomaly_score = round(max(anomalies), 2) if anomalies else 0.0

    if status == "exited" and exit_code != 0:
        anomaly_score = max(anomaly_score, 30.0)
        active_warnings = max(active_warnings, 1)

    # Process logs
    new_event_entries = []
    try:
        raw_logs = await container.log(stdout=True, stderr=True, tail=100)
        for log_item in raw_logs:
            if isinstance(log_item, bytes):
                text_line = log_item.decode("utf-8", errors="ignore").strip()
            else:
                text_line = str(log_item).strip()

            if not text_line:
                continue

            line_ts = parse_line_timestamp(text_line)
            hash_key = hashlib.sha256(f"{container_name}_{line_ts}_{text_line}".encode("utf-8")).hexdigest()

            if hash_key not in seen_log_hashes:
                seen_log_hashes.add(hash_key)
                seen_log_hashes_queue.append(hash_key)
                if len(seen_log_hashes) > MAX_SEEN_LOG_HASHES:
                    old_hash = seen_log_hashes_queue.popleft()
                    seen_log_hashes.discard(old_hash)

                level = determine_log_level(text_line)
                trace_id, span_id = parse_trace_span_ids(text_line)

                new_event_entries.append({
                    "timestamp": line_ts,
                    "container": container_name,
                    "level": level,
                    "content": text_line[:8000],
                    "trace_id": trace_id,
                    "span_id": span_id
                })
    except Exception as e:
        log_msg(f"Warning: Failed to fetch logs for {container_name}: {e}")

    container_telemetry = {
        "name": container_name,
        "status": status,
        "health": health,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "cpu_percent": cpu_percent,
        "memory_usage_bytes": mem_usage,
        "memory_limit_bytes": mem_limit,
        "memory_percent": mem_percent,
        "network_rx_bytes": rx_bytes,
        "network_tx_bytes": tx_bytes,
        "network_rx_rate": rx_rate,
        "network_tx_rate": tx_rate,
        "anomaly_score": anomaly_score,
        "active_warnings": active_warnings
    }

    return container_telemetry, new_event_entries

async def main():
    log_msg("Starting Continuous Async Telemetry Daemon...")
    backoff = 1.0

    while True:
        try:
            async with Docker() as docker:
                while True:
                    start_time = time.time()
                    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    # Discover backend containers
                    containers = await docker.containers.list(
                        all=True,
                        filters={"label": ["ara.topology.group=backend"]}
                    )

                    if not containers:
                        log_msg("Warning: No backend containers found with label ara.topology.group=backend. Retrying...")
                        await asyncio.sleep(POLL_INTERVAL)
                        continue

                    # Collect metrics and logs concurrently
                    tasks = [collect_container_telemetry(c, start_time) for c in containers]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    telemetry_list = []
                    all_new_events = []

                    for res in results:
                        if isinstance(res, Exception):
                            log_msg(f"Error collecting telemetry: {res}")
                            continue
                        c_telemetry, new_events = res
                        telemetry_list.append(c_telemetry)
                        all_new_events.extend(new_events)

                    # 1. Atomically write raw_telemetry.json
                    raw_telemetry_payload = {
                        "generated_at": now_iso,
                        "containers": telemetry_list
                    }
                    atomic_write_json(RAW_TELEMETRY_FILE, raw_telemetry_payload)

                    # 2. Append events to events_and_incidents.json atomically
                    if all_new_events:
                        existing_events = []
                        if os.path.exists(EVENTS_FILE):
                            try:
                                with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                                    existing_events = json.load(f)
                                    if not isinstance(existing_events, list):
                                        existing_events = []
                            except Exception:
                                existing_events = []

                        combined_events = existing_events + all_new_events
                        # Keep only the last MAX_EVENTS
                        if len(combined_events) > MAX_EVENTS:
                            combined_events = combined_events[-MAX_EVENTS:]

                        atomic_write_json(EVENTS_FILE, combined_events)

                    log_msg(f"Telemetry cycle completed for {len(telemetry_list)} containers. Raw telemetry written.")
                    backoff = 1.0  # Reset backoff on success
                    gc.collect()

                    elapsed = time.time() - start_time
                    sleep_duration = max(0.1, POLL_INTERVAL - elapsed)
                    await asyncio.sleep(sleep_duration)

        except Exception as e:
            log_msg(f"Docker API / Loop error: {e}. Backing off for {backoff:.1f}s...")
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2.0)

if __name__ == "__main__":
    asyncio.run(main())