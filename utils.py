import os
import sys
import time
import json
import uuid
import tempfile
import contextlib
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def project_path(*parts: str) -> str:
    return os.path.join(PROJECT_ROOT, *parts)

CHAOS_EVENT_SCHEMA = {
    "event_id": str,        # uuid
    "scenario_id": str,     # group faults into scenarios
    "fault_name": str,
    "target": str,
    "start_ts": str,        # ISO-8601 UTC
    "end_ts": str,
    "params": dict,
    "duration_s": float,
    "status": str           # injected | recovered | failed
}

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def atomic_write_json(filepath: str, data):
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
        # best-effort directory fsync (POSIX only)
        if sys.platform != "win32":
            try:
                dir_fd = os.open(dir_name or ".", os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise

def read_json_file(filepath: str, default_val, retries: int = 3, retry_delay: float = 0.2):
    if not os.path.exists(filepath):
        return default_val
    for attempt in range(retries):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            if attempt < retries - 1:
                time.sleep(retry_delay)
            else:
                return default_val
    return default_val

def parse_iso_dt(ts_str: str) -> datetime:
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        ts = ts_str.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

@contextlib.contextmanager
def file_lock_context(filepath: str):
    lock_file = filepath + ".lock"
    dir_name = os.path.dirname(lock_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    f = open(lock_file, "w")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()
        # Lock files are intentionally never deleted to prevent race conditions
        # where a process holding a lock file reference has it unlinked while another
        # process opens a new inode, breaking exclusivity.

def record_chaos_event(
    fault_name: str,
    target: str,
    start_ts: str,
    end_ts: str,
    params: Optional[Dict[str, Any]] = None,
    duration_s: float = 0.0,
    status: str = "injected",
    scenario_id: str = "adhoc",
    event_id: Optional[str] = None,
    filepath: Optional[str] = None
) -> Dict[str, Any]:
    """
    Standard single writer for chaos_history.json ensuring unified schema and file lock safety.
    """
    if filepath is None:
        filepath = project_path("frontend_data", "chaos_history.json")
    if params is None:
        params = {}
    
    event_entry = {
        "event_id": event_id or str(uuid.uuid4()),
        "scenario_id": scenario_id,
        "fault_name": fault_name,
        "target": target,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "params": params,
        "duration_s": float(duration_s),
        "status": status
    }

    with file_lock_context(filepath):
        history = read_json_file(filepath, [])
        if not isinstance(history, list):
            history = []
        history.append(event_entry)
        atomic_write_json(filepath, history)
    
    return event_entry

def correlate_chaos_event(
    cluster_start_dt: datetime,
    cluster_end_dt: datetime,
    container_name: str,
    chaos_history_data: list
) -> str:
    """
    Correlate a log cluster with injected chaos events using a unified +/- 300s window.
    Returns the human/LLM-readable mutation description string, or empty string if none.
    """
    cluster_start = cluster_start_dt.timestamp()
    cluster_end = cluster_end_dt.timestamp()

    for ev in chaos_history_data:
        if not isinstance(ev, dict):
            continue
        s_ts = ev.get("start_ts", "")
        e_ts = ev.get("end_ts", "")
        f_target = ev.get("target", "")
        f_name = ev.get("fault_name", "")
        dur = float(ev.get("duration_s", ev.get("duration", 0.0)))

        ev_start = parse_iso_dt(s_ts).timestamp() - 300.0
        ev_end = parse_iso_dt(e_ts).timestamp() + 300.0 if e_ts else ev_start + dur + 300.0

        if (cluster_start <= ev_end and cluster_end >= ev_start) and (container_name == f_target or not f_target or container_name in f_target):
            status_str = ev.get("status", "injected")
            return f"Infrastructure orchestrator triggered {f_name} on {f_target} (duration: {dur:.1f}s, status: {status_str})."
    return ""

def migrate_legacy_chaos_history(filepath: Optional[str] = None) -> int:
    """
    One-time migration of legacy scenario-schema chaos history entries to the unified
    CHAOS_EVENT_SCHEMA.
    """
    if filepath is None:
        filepath = project_path("frontend_data", "chaos_history.json")

    with file_lock_context(filepath):
        history = read_json_file(filepath, [])
        if not isinstance(history, list) or not history:
            return 0

        migrated: List[Dict[str, Any]] = []
        legacy_count = 0
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if "start_ts" in entry and "end_ts" in entry:
                migrated.append(entry)  # already unified
                continue
            if "timestamp" not in entry or "faults" not in entry:
                migrated.append(entry)  # unknown shape, preserve as-is
                continue

            legacy_count += 1
            scenario_id = entry.get("scenario_id", "legacy")
            start_dt = parse_iso_dt(entry.get("timestamp", ""))
            duration = float(entry.get("duration", 0.0))
            end_dt = start_dt + timedelta(seconds=duration)
            status = entry.get("status", "completed")
            unified_status = "recovered" if status in ("completed", "recovered") else "injected"
            faults = entry.get("faults", []) or ["unknown"]
            targets = entry.get("target_services", []) or ["unknown"]

            for idx, fault_name in enumerate(faults):
                target = targets[idx] if idx < len(targets) else (targets[-1] if targets else "unknown")
                migrated.append({
                    "event_id": str(uuid.uuid4()),
                    "scenario_id": scenario_id,
                    "fault_name": fault_name,
                    "target": target,
                    "start_ts": start_dt.isoformat(),
                    "end_ts": end_dt.isoformat(),
                    "params": {"migrated_from_legacy": True},
                    "duration_s": duration,
                    "status": unified_status
                })

        if legacy_count > 0:
            atomic_write_json(filepath, migrated)
        return legacy_count
