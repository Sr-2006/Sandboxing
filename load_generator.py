import time
import random
import requests
import argparse
import uuid

GATEWAY_URL = "http://localhost:8080"

# Endpoint maps via Gateway (with fallback to direct service ports)
ENDPOINTS = {
    "auth": [
        {"method": "POST", "path": "/api/v1/auth/register", "fallback_port": 8081, "payload": lambda: {"username": f"user_{uuid.uuid4().hex[:8]}", "password": "password123", "email": f"user_{uuid.uuid4().hex[:8]}@example.com"}},
        {"method": "POST", "path": "/api/v1/auth/login", "fallback_port": 8081, "payload": lambda: {"username": "admin", "password": "password"}}
    ],
    "order": [
        {"method": "POST", "path": "/api/v1/orders", "fallback_port": 8082, "payload": lambda: {"userId": str(uuid.uuid4()), "item": "Laptop", "amount": 1200.0}},
        {"method": "GET", "path": "/api/v1/orders", "fallback_port": 8082, "payload": None}
    ],
    "payment": [
        {"method": "POST", "path": "/api/v1/payments/process", "fallback_port": 8083, "payload": lambda: {"orderId": str(uuid.uuid4()), "amount": 99.99, "currency": "USD"}}
    ]
}

CHAOS_ENDPOINTS = [
    {"type": "slow", "path": "/chaos/slow?delayMs=5000", "timeout": 8.0},
    {"type": "throw", "path": "/chaos/throw?type=connection-reset", "timeout": 3.0},
    {"type": "throw", "path": "/chaos/throw?type=null-pointer", "timeout": 3.0},
    {"type": "throw", "path": "/chaos/throw?type=sql-timeout", "timeout": 3.0}
]

CHAOS_PORTS = {
    "gateway": 8080,
    "auth": 8081,
    "order": 8082,
    "payment": 8083
}

def send_request(target_service="all"):
    # Pick service
    available = ["auth", "order", "payment"] if target_service == "all" else [target_service]
    service = random.choice(available)
    
    action = random.choice(["normal", "normal", "normal", "chaos"])
    
    if action == "normal":
        ep = random.choice(ENDPOINTS[service])
        url = f"{GATEWAY_URL}{ep['path']}"
        try:
            payload = ep['payload']() if ep['payload'] else None
            if ep['method'] == "POST":
                res = requests.post(url, json=payload, timeout=3.0)
            else:
                res = requests.get(url, timeout=3.0)
            print(f"[LOAD] [{service.upper()}] {ep['method']} {ep['path']} -> {res.status_code}")
        except Exception:
            # Fallback to direct service port
            port = ep['fallback_port']
            fallback_path = ep['path'].replace("/api/v1/orders", "/api/orders").replace("/api/v1/payments", "/api/payments")
            fallback_url = f"http://localhost:{port}{fallback_path}"
            try:
                payload = ep['payload']() if ep['payload'] else None
                if ep['method'] == "POST":
                    res = requests.post(fallback_url, json=payload, timeout=3.0)
                else:
                    res = requests.get(fallback_url, timeout=3.0)
                print(f"[LOAD-FALLBACK] [{service.upper()}] {ep['method']} {fallback_url} -> {res.status_code}")
            except Exception as ex:
                print(f"[ERROR] [{service.upper()}] {url} failed: {ex}")
    else:
        # Chaos trigger
        c_ep = random.choice(CHAOS_ENDPOINTS)
        port = CHAOS_PORTS.get(service, 8080)
        c_url = f"http://localhost:{port}{c_ep['path']}"
        try:
            res = requests.get(c_url, timeout=c_ep['timeout'])
            print(f"[CHAOS-TRIGGER] [{service.upper()}] GET {c_url} -> {res.status_code}")
        except Exception as e:
            print(f"[CHAOS-TRIGGER] [{service.upper()}] {c_url} -> Expected fault/timeout: {e}")

def run_generator(target_service="all", duration=0):
    start_time = time.time()
    print(f"Starting Auto-SRE Traffic Generator (Target: {target_service}, Duration: {'Infinite' if duration == 0 else f'{duration}s'})...")
    
    while True:
        send_request(target_service)
        if duration > 0 and (time.time() - start_time) >= duration:
            print("[+] Traffic generation duration completed.")
            break
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-SRE Traffic & Fault Generator")
    parser.add_argument("--service", type=str, default="all", choices=["all", "auth", "order", "payment"], help="Target service")
    parser.add_argument("--duration", type=int, default=0, help="Run duration in seconds (0 = continuous)")
    args = parser.parse_args()
    
    run_generator(args.service, args.duration)
