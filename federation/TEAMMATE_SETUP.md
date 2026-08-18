# Teammate Setup — Connect Your Laptop to the Auto-SRE Federation

> **You are joining a live mesh.** Laptop A (the host) already exposes Phase 1
> over a free Cloudflare tunnel. This guide shows you how to:
> 1. **Consume** the Phase 1 dataset from the host's tunnel (read-only).
> 2. **Expose your own phase** through your own tunnel.
> 3. **Register your URL** so every phase can find every other phase.

No domain, no port forwarding, no VPS, no firewall changes. Everything is free.

---

## 0. The live Phase 1 endpoint (hosted by Laptop A)

```
PHASE1_DATASET_URL = https://making-defines-handled-melbourne.trycloudflare.com
```

| Route | Returns |
|---|---|
| `GET /health` | server status + dataset freshness |
| `GET /dataset` | full `unified_master_dataset.json` |
| `GET /files` | list of available JSON artifacts |
| `GET /<name>.json` | any artifact, e.g. `/status.json` |

> ⚠️ This is a **quick tunnel** — the URL changes if the host restarts it.
> Always read the current URL from `federation/.env.federation` (committed in
> the repo), never hardcode it.

---

## 1. One-time setup on YOUR laptop

```powershell
# 1. Install git if missing
winget install --id Git.Git -e

# 2. Clone the repo (GitLab)
git clone https://gitlab.com/sre-group6103633/sre-project.git
cd sre-project

# 3. Python environment
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. Install the Cloudflare tunnel connector
winget install --id Cloudflare.cloudflared -e
# then OPEN A NEW TERMINAL so `cloudflared` is on PATH
```

---

## 2. Verify you can reach the host's Phase 1 tunnel

Run the included connectivity checker (stdlib only, no deps):

```powershell
python federation\test_phase1_url.py
```

Expected output:

```
[ok] health  -> status=ok dataset_present=True
[ok] dataset -> 343379 bytes, generated_at=2026-08-18T02:53:37Z
PHASE 1 ENDPOINT REACHABLE ✅
```

Or manually:

```powershell
Invoke-RestMethod https://making-defines-handled-melbourne.trycloudflare.com/health
```

If it fails: the host's tunnel may be down or the URL changed — ask the host to
re-run `.\federation\start-tunnel.ps1 -Phase phase1` and re-commit `.env.federation`.

---

## 3. Consume the dataset in your phase code

Read the URL from `federation/.env.federation` instead of hardcoding:

```python
from pathlib import Path
import httpx, json

def phase1_url() -> str:
    env = Path(__file__).resolve().parents[1] / "federation" / ".env.federation"
    for line in env.read_text().splitlines():
        if line.startswith("PHASE1_DATASET_URL="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("PHASE1_DATASET_URL not set in federation/.env.federation")

dataset = httpx.get(f"{phase1_url()}/dataset", timeout=30).json()
print(dataset["metadata"]["dataset_version"], len(dataset["incidents"]), "incidents")
```

---

## 4. Expose YOUR phase through your own tunnel

Start your phase's local service first, then open a tunnel. Pick your phase:

| Laptop | Phase | Start the service | Open the tunnel |
|---|---|---|---|
| B | Phase 2 ChromaDB | `pip install chromadb` then `chroma run --host 127.0.0.1 --port 8000` | `.\federation\start-tunnel.ps1 -Phase phase2` |
| C | Phase 3 MCP SSE | start your FastMCP servers on `8001` | `.\federation\start-tunnel.ps1 -Phase phase3` |
| C | Phase 3 Ollama | `ollama pull qwen2.5:3b` (API on `11434`) | `.\federation\start-tunnel.ps1 -Phase phase3 -Port 11434` |
| D | Phase 4 veto | `python <your_gateway>.py --port 8002` | `.\federation\start-tunnel.ps1 -Phase phase4` |

The script prints a public URL like:

```
https://some-random-words.trycloudflare.com
```

> Run **heavy workloads (Ollama + ChromaDB embeddings) on ONE laptop only** and
> let everyone else call it through its tunnel. Don't duplicate the model.

---

## 5. Register your URL

1. Open `federation/.env.federation`.
2. Paste your printed URL into the matching variable:

   ```
   PHASE2_CHROMA_URL=https://your-tunnel.trycloudflare.com
   ```

3. Commit and push so the whole team picks it up:

   ```powershell
   git add federation/.env.federation
   git commit -m "federation: register phase2 tunnel URL"
   git push
   ```

---

## 6. Verify the whole mesh

Once two or more URLs are registered, any laptop can reach any phase:

```powershell
# from any laptop, after pulling the latest .env.federation
Invoke-RestMethod $env:PHASE1_DATASET_URL/health     # Phase 1
Invoke-RestMethod $env:PHASE2_CHROMA_URL/api/v1/heartbeat   # Phase 2 (Chroma)
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cloudflared: command not found` | Open a **new** terminal after `winget install`, or re-run the installer |
| Tunnel script warns "nothing listening on port" | Start your phase's service **before** opening the tunnel |
| Public URL returns 502 / times out | Your local service crashed or isn't on the expected port |
| URL stopped working later | Quick-tunnel URLs change on restart — host re-runs `start-tunnel.ps1` and re-commits `.env.federation` |
| Need a permanent URL | Requires a domain (~$2/yr) + Cloudflare DNS → use `federation/cloudflared/named-tunnel-example.yml` |

---

## Quick reference

- Repo: `https://gitlab.com/sre-group6103633/sre-project.git`
- Host Phase 1 URL: `https://making-defines-handled-melbourne.trycloudflare.com`
- URL registry: `federation/.env.federation`
- Tunnel script: `federation/start-tunnel.ps1`
- Connectivity test: `federation/test_phase1_url.py`
- Full architecture: `federation/SETUP_GUIDE.md`
