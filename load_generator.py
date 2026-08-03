import time
import random
import requests

SERVICES = {
    "auth": "http://localhost:8081/api/v1/auth",
    "order": "http://localhost:8082/api/orders",
    "payment": "http://localhost:8083/api/payments"
}

def generate_traffic():
    while True:
        choice = random.choice(["normal", "latency", "error"])
        
        try:
            if choice == "normal":
                res = requests.post(f"{SERVICES['payment']}/process", timeout=2)
                print(f"[NORMAL] Payment check: {res.status_code}")
            elif choice == "latency":
                print("[CHAOS] Triggering 5s payment latency...")
                res = requests.get(f"{SERVICES['payment']}/chaos/latency", timeout=7)
                print(f"[LATENCY] Response: {res.status_code}")
            else:
                print("[CHAOS] Triggering simulated payment decline...")
                res = requests.get(f"{SERVICES['payment']}/chaos/decline", timeout=2)
                print(f"[DECLINE] Response: {res.status_code}")
        except Exception as e:
            print(f"[ERROR] Request failed: {e}")
            
        time.sleep(random.uniform(1.0, 3.0))

if __name__ == "__main__":
    print("Starting Auto-SRE Traffic & Chaos Generator...")
    generate_traffic()
