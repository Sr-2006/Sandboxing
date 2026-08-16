import time
import random
import requests
import argparse
import uuid
import os
from utils import get_logger

logger = get_logger("load_generator")

TARGET_HOST = os.environ.get("TARGET_HOST", "localhost")
GATEWAY_URL = f"http://{TARGET_HOST}:8080"
CHAOS_SECRET = os.environ.get("CHAOS_SECRET", "dev-chaos-token")

# Explicit endpoint maps (Gateway path vs Direct service path)
ENDPOINTS = {
    "auth": [
        {
            "method": "POST",
            "gateway_path": "/api/v1/auth/register",
            "direct_path": "/api/v1/auth/register",
            "fallback_port": 8081,
            "payload": lambda: {"username": f"user_{uuid.uuid4().hex[:8]}", "password": "password123", "email": f"user_{uuid.uuid4().hex[:8]}@example.com"}
        },
        {
            "method": "POST",
            "gateway_path": "/api/v1/auth/login",
            "direct_path": "/api/v1/auth/login",
            "fallback_port": 8081,
            "payload": lambda: {"username": "admin", "password": "password"}
        }
    ],
    "order": [
        {
            "method": "POST",
            "gateway_path": "/api/v1/orders",
            "direct_path": "/api/orders",
            "fallback_port": 8082,
            "payload": lambda: {"userId": str(uuid.uuid4()), "item": "Laptop", "amount": 1200.0}
        },
        {
            "method": "GET",
            "gateway_path": "/api/v1/orders",
            "direct_path": "/api/orders",
            "fallback_port": 8082,
            "payload": None
        }
    ],
    "payment": [
        {
            "method": "POST",
            "gateway_path": "/api/v1/payments/process",
            "direct_path": "/api/payments/process",
            "fallback_port": 8083,
            "payload": lambda: {"orderId": str(uuid.uuid4()), "amount": 99.99, "currency": "USD"}
        }
    ]
}

CHAOS_ENDPOINTS = [
    {"type": "slow", "path": "/chaos/slow?delayMs=5000", "timeout": 8.0},
    {"type": "throw", "path": "/chaos/throw?type=connection-reset", "timeout": 3.0},
    {"type": "throw", "path": "/chaos/throw?type=null-pointer", "timeout": 3.0},
    {"type": "throw", "path": "/chaos/throw?type=sql-timeout", "timeout": 3.0}
]

CHAOS_PORTS = {
    "auth": 8081,
    "order": 8082,
    "payment": 8083
}

def send_request(target_service="all"):
    available = ["auth", "order", "payment"] if target_service == "all" else [target_service]
    service = random.choice(available)
    
    action = random.choice(["normal", "normal", "normal", "chaos"])
    
    if action == "normal":
        ep = random.choice(ENDPOINTS[service])
        url = f"{GATEWAY_URL}{ep['gateway_path']}"
        try:
            payload = ep['payload']() if ep['payload'] else None
            if ep['method'] == "POST":
                res = requests.post(url, json=payload, timeout=3.0)
            else:
                res = requests.get(url, timeout=3.0)
            logger.info(f"[{service.upper()}] {ep['method']} {ep['gateway_path']} -> {res.status_code}")
        except Exception:
            # Fallback to direct service port
            port = ep['fallback_port']
            fallback_url = f"http://{TARGET_HOST}:{port}{ep['direct_path']}"
            try:
                payload = ep['payload']() if ep['payload'] else None
                if ep['method'] == "POST":
                    res = requests.post(fallback_url, json=payload, timeout=3.0)
                else:
                    res = requests.get(fallback_url, timeout=3.0)
                logger.info(f"[FALLBACK] [{service.upper()}] {ep['method']} {fallback_url} -> {res.status_code}")
            except Exception as ex:
                logger.error(f"[{service.upper()}] {url} failed: {ex}")
    else:
        # Chaos trigger directly on service port with security header
        c_ep = random.choice(CHAOS_ENDPOINTS)
        port = CHAOS_PORTS.get(service, 8081)
        c_url = f"http://{TARGET_HOST}:{port}{c_ep['path']}"
        headers = {"X-Chaos-Token": CHAOS_SECRET}
        try:
            res = requests.get(c_url, headers=headers, timeout=c_ep['timeout'])
            logger.info(f"[CHAOS-TRIGGER] [{service.upper()}] GET {c_url} -> {res.status_code}")
        except Exception as e:
            logger.warning(f"[CHAOS-TRIGGER] [{service.upper()}] {c_url} -> Expected fault/timeout: {e}")

def run_generator(target_service="all", duration=0):
    start_time = time.time()
    logger.info(f"Starting Auto-SRE Traffic Generator (Target: {target_service}, Duration: {'Infinite' if duration == 0 else f'{duration}s'})...")
    
    while True:
        send_request(target_service)
        if duration > 0 and (time.time() - start_time) >= duration:
            logger.info("Traffic generation duration completed.")
            break
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-SRE Traffic & Fault Generator")
    parser.add_argument("--service", type=str, default="all", choices=["all", "auth", "order", "payment"], help="Target service")
    parser.add_argument("--duration", type=int, default=0, help="Run duration in seconds (0 = continuous)")
    args = parser.parse_args()
    
    run_generator(args.service, args.duration)
