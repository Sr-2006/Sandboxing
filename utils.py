import os
import sys
import time
import json
import tempfile
import contextlib
from datetime import datetime, timezone

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
