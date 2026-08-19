# Cloudflare Tunnel Federation & Data Sharing Guide

This guide contains complete, step-by-step instructions for **Host (Laptop A)** and **Teammates (Laptops B, C, D)** to establish connections, share URLs, sync `frontend_data`, and transfer files over Cloudflare Tunnels without paid accounts or port forwarding.

---

## Part 1: Host Guide (Laptop A)

### 1. Initial Setup from Scratch
Open PowerShell as Administrator or regular user:
```powershell
# 1. Navigate to the project root
cd C:\Users\sujay\Downloads\complex\auto-sre-platform

# 2. Setup Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Install Cloudflare tunnel client (one-time setup)
winget install --id Cloudflare.cloudflared -e
```
*(Restart terminal once if `cloudflared` is not recognized on PATH).*

---

### 2. Populate and Prepare `frontend_data/` from Scratch
To create or refresh all telemetry data and the master dataset:
```powershell
# Generate fresh dataset & JSON files inside frontend_data/
python package_ml_dataset.py
```
To share any extra file (like `context.txt` or `random.txt`) over the tunnel:
```powershell
# Any .json file placed in frontend_data/ is automatically hosted
Copy-Item context.txt frontend_data/context.json
Copy-Item random.txt frontend_data/random.json
```

---

### 3. Start the Connection (2 Terminals Required)

#### Terminal 1: Start the Local Dataset Server
```powershell
python federation/serve_dataset.py --port 8090
```
> **Keep this terminal running.** Output will show:
> `Phase 1 dataset endpoint on http://127.0.0.1:8090`

#### Terminal 2: Start the Cloudflare Tunnel
```powershell
.\federation\start-tunnel.ps1 -Phase phase1
```

---

### 4. How to Get Your Public URL
Look at the output box in **Terminal 2**. You will see:
```text
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com                                             |
+--------------------------------------------------------------------------------------------+
```
Copy that URL (`https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com`).

#### Update configuration:
Paste your live URL into `federation/.env.federation`:
```ini
PHASE1_DATASET_URL=https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com
```

---

### 5. Host Diagnostics & Status Commands
Run these in a 3rd terminal to check connection status and active peers:

* **Check if port 8090 is listening locally:**
  ```powershell
  Get-NetTCPConnection -LocalPort 8090 -State Listen
  ```
* **Check live connections (see when teammates connect):**
  ```powershell
  Get-NetTCPConnection -LocalPort 8090 -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, State
  ```
* **Verify tunnel health:**
  ```powershell
  python federation/test_phase1_url.py
  ```

---

## Part 2: Teammate Guide (Laptops B, C, D)

### 1. Teammate Setup from Scratch
Run in PowerShell on the teammate's machine:
```powershell
# 1. Clone the repository
git clone https://gitlab.com/sre-group6103633/sre-project.git
cd sre-project

# 2. Setup Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Install Cloudflare tunnel connector (needed when exposing their phase)
winget install --id Cloudflare.cloudflared -e
```

---

### 2. Verify Connection to Host
Replace `<HOST_URL>` with the host's URL (e.g. `https://tokyo-equivalent-reduce-integrating.trycloudflare.com`):

```powershell
# Run the built-in connectivity tester
python federation/test_phase1_url.py --url <HOST_URL>

# Or test directly in PowerShell
Invoke-RestMethod <HOST_URL>/health
```

---

### 3. Retrieve & Download Data from the Host

#### A. Download a Single File (e.g., Master Dataset, Context, Random)
```powershell
# Download the master dataset
Invoke-WebRequest -Uri "<HOST_URL>/dataset" -OutFile "frontend_data\unified_master_dataset.json"

# Download context.txt (hosted as context.json)
Invoke-WebRequest -Uri "<HOST_URL>/context.json" -OutFile "context.txt"

# Download random.txt (hosted as random.json)
Invoke-WebRequest -Uri "<HOST_URL>/random.json" -OutFile "random.txt"
```

#### B. Download the Entire `frontend_data` Folder from Host
Run this one-liner in PowerShell to download all JSON artifacts from the host automatically:
```powershell
New-Item -ItemType Directory -Force -Path "frontend_data" ; (Invoke-RestMethod "<HOST_URL>/files") | ForEach-Object { Invoke-WebRequest -Uri "<HOST_URL>/$_" -OutFile "frontend_data/$_" ; Write-Host "Downloaded $_" -ForegroundColor Green }
```

---

### 4. How Teammates Send / Expose Their Own Phases

When a teammate is ready to share their phase back with the host and team:

#### Laptop B (Phase 2 - ChromaDB):
```powershell
# Start ChromaDB locally
pip install chromadb
chroma run --host 127.0.0.1 --port 8000

# In a second terminal, start tunnel
.\federation\start-tunnel.ps1 -Phase phase2
```

#### Laptop C (Phase 3 - Ollama / FastMCP):
```powershell
# For MCP SSE Server on port 8001:
.\federation\start-tunnel.ps1 -Phase phase3

# For Ollama API on port 11434:
.\federation\start-tunnel.ps1 -Phase phase3 -Port 11434
```

#### Laptop D (Phase 4 - Veto Gateway):
```powershell
.\federation\start-tunnel.ps1 -Phase phase4
```

---

### 5. Register URLs in Git (Syncing the Team Mesh)
Whenever any teammate or host starts a tunnel and gets a URL:
1. Open `federation/.env.federation`
2. Add/update the respective URL variable:
   ```ini
   PHASE1_DATASET_URL=https://...
   PHASE2_CHROMA_URL=https://...
   PHASE3_MCP_URL=https://...
   PHASE3_OLLAMA_URL=https://...
   PHASE4_VETO_URL=https://...
   ```
3. Commit and push:
   ```powershell
   git add federation/.env.federation
   git commit -m "federation: update phase tunnel URLs"
   git push
   ```
4. Other teammates run `git pull` to receive updated endpoints.
