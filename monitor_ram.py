import time
import os
import psutil
from datetime import datetime, timezone

LOG_FILE = os.path.join("frontend_data", "health_warnings.log")
MAX_LOG_SIZE = 1024 * 1024  # 1 MB
THRESHOLD_PERCENT = 90.0
CHECK_INTERVAL_SECONDS = 10.0

def rotate_log_if_needed():
    if os.path.exists(LOG_FILE):
        try:
            if os.path.getsize(LOG_FILE) >= MAX_LOG_SIZE:
                backup_file = LOG_FILE + ".1"
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                os.rename(LOG_FILE, backup_file)
        except Exception as e:
            print(f"[RAM_MONITOR LOG ROTATION ERROR] {e}", flush=True)

def log_warning(msg: str):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{now_iso}] [RAM_MONITOR] {msg}\n"
    print(line.strip(), flush=True)
    rotate_log_if_needed()
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)

def run_ram_monitor():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] Starting System RAM Monitor (Threshold: {THRESHOLD_PERCENT}%, Interval: {CHECK_INTERVAL_SECONDS}s)...", flush=True)
    while True:
        try:
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024 ** 3)
            used_gb = mem.used / (1024 ** 3)
            percent = mem.percent

            if percent >= THRESHOLD_PERCENT:
                log_warning(f"HIGH MEMORY WARNING: System RAM usage at {percent:.1f}% ({used_gb:.2f} GB / {total_gb:.2f} GB used).")
        except Exception as e:
            print(f"[RAM_MONITOR ERROR] {e}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_ram_monitor()
