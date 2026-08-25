#!/usr/bin/env python3
"""
shadow_sandbox/faults/pg_hold_daemon.py

Detached background daemon process for holding PostgreSQL TCP socket connections open.
Persists across independent CLI/process invocations until killed by close_exhausted_connections().
"""

import os
import sys
import time
import socket
import json
import signal
from typing import List

PID_FILE = os.path.join(os.path.dirname(__file__), "pg_hold.pid")

def hold_connections(target: str, count: int, host: str = "127.0.0.1", port: int = 15432):
    sockets: List[socket.socket] = []
    opened = 0

    for _ in range(count):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect((host, port))
            sockets.append(s)
            opened += 1
        except Exception:
            break

    # Save PID metadata
    meta = {
        "pid": os.getpid(),
        "target": target,
        "count_requested": count,
        "count_opened": opened,
        "started_at": time.time()
    }
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    # Keep sockets alive until process receives terminate signal
    def handle_signal(sig, frame):
        for s in sockets:
            try:
                s.close()
            except Exception:
                pass
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        handle_signal(None, None)

if __name__ == "__main__":
    target_arg = sys.argv[1] if len(sys.argv) > 1 else "shadow-postgres-db"
    count_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    hold_connections(target_arg, count_arg)
