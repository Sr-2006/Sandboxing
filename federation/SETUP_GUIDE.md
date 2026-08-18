# Auto-SRE Federation Setup Guide — 4 Laptops → 1 Unified Platform (all free)

Goal: each laptop owns ONE phase; Git + GitLab CI is the "unified app"; Cloudflare
Tunnels provide free live cross-laptop calls when needed.

---

## 0. Accounts to create (exact URLs, all free)

| # | Service | Sign-up URL | Free plan gives you | Needed by |
|---|---------|-------------|---------------------|-----------|
| 1 | **GitLab** | https://gitlab.com/users/sign_up | 400 CI min/month (shared runners), 5 GiB repo storage, unlimited MRs | Everyone (1 account each, or 1 shared team account) |
| 2 | **Cloudflare** | https://dash.cloudflare.com/sign-up | Unlimited tunnel bandwidth, no port forwarding | Only for **named** tunnels (stable URLs). Quick tunnels need NO account |
| 3 | **Domain** (optional) | https://porkbun.com or https://www.namecheap.com (~$2–10/yr for a `.dev`/`.xyz`) | Stable hostnames like `chroma.yourdomain.com` | Only if you want stable tunnel names. Skip → use quick tunnels |
| 4 | **Docker Desktop** | https://www.docker.com/products/docker-desktop/ | Free for personal & companies <250 employees | Assembly host + any laptop running the compose stack |
| 5 | **Ollama** | https://ollama.com/download | 100% free, runs locally, no account | Laptop C only |
| 6 | **ChromaDB** | `pip install chromadb` (OSS, no account) | Free | Laptop B only |

> No VPS, no ngrok, no paid CI. If you have no domain and want zero accounts,
> quick tunnels (`*.trycloudflare.com`) cover the whole hackathon.

---

## 1. One-time repo setup (Laptop A)

```powershell
winget install --id Git.Git -e
# On gitlab.com: New project → "Create blank project" → name: auto-sre-platform
cd C:\path\to\auto-sre-platform
git remote add origin https://gitlab.com/<your-group>/auto-sre-platform.git
git push -u origin main
```

- GitLab → project → **Build → Pipelines**: your existing `.gitlab-ci.yml` runs
  automatically on free shared runners (enabled by default).
- GitLab → project → **Settings → Merge requests → Merge checks**: enable
  **"Pipelines must succeed"**. This makes the `contract` job (schema contract
  tests + `validate_10.py --static`) a hard merge gate — a phase branch cannot
  break another phase's interface.
- GitLab → project → **Settings → General → Visibility**: keep Private.
- The pipeline already enforces the contract gate: `test-python` (schema contract
  tests) → `integration` (full compose + dataset regen) → `validate` (`validate_10.py`).
  **Rule: a phase branch merges to `main` only when its pipeline is green.**

## 2. Every laptop: clone + environment

```powershell
git clone https://gitlab.com/<your-group>/auto-sre-platform.git
cd auto-sre-platform
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Branch convention (keeps CI meaningful):
- Laptop A → `phase1/*` branches · Laptop B → `phase2/*` · Laptop C → `phase3/*` · Laptop D → `phase4/*`
- Work → push → open Merge Request in GitLab → pipeline green → merge. That MR flow IS your "unified application".

## 3. Laptop A — Phase 1 dataset endpoint (port 8090)

```powershell
python federation/serve_dataset.py --port 8090     # serves frontend_data/*.json
.\federation\start-tunnel.ps1 -Phase phase1
```

## 4. Laptop B — Phase 2 ChromaDB (port 8000)

```powershell
pip install chromadb
chroma run --host 127.0.0.1 --port 8000
.\federation\start-tunnel.ps1 -Phase phase2
```

## 5. Laptop C — Phase 3 MCP + Ollama (ports 8001 / 11434)

```powershell
winget install --id Ollama.Ollama -e
ollama pull qwen2.5:3b                              # Ollama API: http://localhost:11434
# start your FastMCP SSE servers on 8001, then:
.\federation\start-tunnel.ps1 -Phase phase3          # MCP SSE
.\federation\start-tunnel.ps1 -Phase phase3 -Port 11434   # second tunnel for Ollama
```

> Run Ollama + Chroma embeddings on THIS laptop only. Others call it via tunnel —
> never duplicate the heavy model on 4 machines.

## 6. Laptop D — Phase 4 veto gateway (port 8002)

```powershell
python <your_phase4_gateway>.py --port 8002
.\federation\start-tunnel.ps1 -Phase phase4
```

## 7. Share the URLs

Each `start-tunnel.ps1` run prints a public URL like
`https://random-words.trycloudflare.com`. Paste them into `federation/.env.federation`
(copy from `.env.federation.example`) and commit — or just drop them in team chat.
Every phase reads the other phases' URLs from that file instead of `localhost`.

### Stable URLs (optional — needs Cloudflare account + domain)

On the laptop that owns the service:

```powershell
cloudflared tunnel login                              # browser opens, authorize
cloudflared tunnel create phase2-chroma               # prints a TUNNEL_ID
cloudflared tunnel route dns phase2-chroma chroma.yourdomain.com
# edit federation/cloudflared/named-tunnel-example.yml (tunnel id + credentials path),
# then:
cloudflared tunnel --config federation\cloudflared\named-tunnel-example.yml run phase2-chroma
cloudflared service install                           # optional: auto-start on boot
```

## 8. Demo day — ONE assembly host

```powershell
git checkout main ; git pull
copy .env.example .env                                # fill the secrets
docker compose up -d --wait
python simulate_full_telemetry.py --fresh             # auto-runs phase1 → package → validate
python validate_10.py --static                        # expect 37/37
```

The assembly host is a local mirror of what the GitLab `integration` job already
does — so the demo cannot drift from what CI validated.

---

## Why this is "zero-latency, low-load" in practice

- **Contract integration is event-driven**: triggered by `git push` (webhook), not polling. Zero idle cost.
- **Tunnels are on-demand**: no heartbeat cluster traffic across NAT'd laptops.
- **Heavy workloads live on one machine** (Laptop C), everyone else calls it.
- **The merged dataset travels as a Git artifact**, not as live RPC — Phase 2 never
  needs Phase 1's laptop awake, only its validated `unified_master_dataset.json`.
