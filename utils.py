import os
import sys
import time
import json
import uuid
import tempfile
import contextlib
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

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
        os.replace(temp_path, filepath)
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
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

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
    filepath: str = os.path.join("frontend_data", "chaos_history.json")
) -> Dict[str, Any]:
    """
    Standard single writer for chaos_history.json ensuring unified schema and file lock safety.
    """
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
