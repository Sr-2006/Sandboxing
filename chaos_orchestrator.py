import docker
import time

client = docker.from_env()

def inject_chaos():
    print("[CHAOS] Initializing ARA Chaos Orchestrator...")
    try:
        # Locate the core database container
        postgres_container = client.containers.get("postgres-db")
        
        print(f"[CHAOS] Found target: {postgres_container.name}")
        print("[CHAOS] INJECTING FAULT: Pausing postgres-db to simulate critical outage...")
        postgres_container.pause()
        
        # Keep it paused for 30 seconds to allow the telemetry daemons to capture the failure state
        print("[CHAOS] Database is frozen. Let the telemetry sync catch the HTTP 503 errors...")
        for i in range(30, 0, -1):
            print(f"--- Restoring in {i} seconds...", end="\r")
            time.sleep(1)
            
        print("\n[CHAOS] REMEDIATION: Unpausing postgres-db...")
        postgres_container.unpause()
        print("[CHAOS] Database restored. Chaos test complete. Check your JSON files!")
        
    except docker.errors.NotFound:
        print("[ERROR] Could not find 'postgres-db'. Is the container running?")
    except Exception as e:
        print(f"[ERROR] Chaos injection failed: {e}")

if __name__ == "__main__":
    inject_chaos()