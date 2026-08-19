# Auto-SRE Platform — Final Architecture (Cross-Network / Cloudflare Edition)

> Version: 2026-08-19 · Supersedes the quick-tunnel-only flow in `federation/SETUP_GUIDE.md`
> Assumption: **the 4 laptops are NOT on the same Wi-Fi.** All internal traffic crosses
> the internet, so we use **Cloudflare NAMED tunnels** (stable hostnames, SSE/WebSocket
> support, no 200-request quick-tunnel limit) + **Cloudflare Access** for identity.

---

## 0. The three decisions

| Concern | Decision | Why |
|---|---|---|
| Stable internal URLs | **Named tunnels**, one per laptop, subdomain per phase | Quick tunnels die on restart with a new random URL → sync breaks. Named tunnels survive reboots and support SSE/WebSocket. |
| Identity / "who connected" | **Cloudflare Access** (Zero Trust, free ≤50 users) with one shared **service token** | Every request carries `CF-Access-Client-Id/Secret`; Access **audit logs** show exactly which teammate hit which endpoint and when. Solves the "quick tunnels are anonymous" problem. |
| Shared event bus | **One RabbitMQ on Laptop A**, exposed as TCP through a tunnel; teammates run a local `cloudflared access tcp` relay | Code on every laptop keeps using `amqp://guest:guest@localhost:PORT` — zero code changes. |

Quick tunnels (`*.trycloudflare.com`) are kept **only** as an emergency fallback and for
last-minute public demo exposure.

---

## 1. Final network topology

```mermaid
flowchart TB
    subgraph CF["Cloudflare Edge (yourdomain.com)"]
        P1H["phase1.yourdomain.com"]
        P2H["phase2.yourdomain.com"]
        P3H["phase3.yourdomain.com"]
        P4H["phase4.yourdomain.com"]
        RABH["rabbit.yourdomain.com  (TCP)"]
        DEMO["demo.yourdomain.com  (public)"]
        ACCESS["Cloudflare Access<br/>service-token gate + audit logs"]
        P1H & P2H & P3H & P4H & RABH --- ACCESS
    end

    subgraph LA["💻 Laptop A — Phase 1 + shared RabbitMQ"]
        A1["serve_dataset.py :8090"]
        A2["rabbitmq :5672 (compose)"]
        T1["cloudflared tunnel phase1-net"]
        A1 --> T1
        A2 --> T1
    end

    subgraph LB["💻 Laptop B — Phase 2"]
        B1["ChromaDB :8000"]
        T2["cloudflared tunnel phase2-net"]
        B1 --> T2
        R2["cloudflared access tcp relay<br/>localhost:25672 → rabbit tunnel"]
    end

    subgraph LC["💻 Laptop C — Phase 3"]
        C1["MCP :8001 + Ollama :11434 (local only)"]
        T3["cloudflared tunnel phase3-net"]
        C1 --> T3
        R3["cloudflared access tcp relay"]
    end

    subgraph LD["💻 Laptop D — Phase 4"]
        D1["veto gateway :8002"]
        T4["cloudflared tunnel phase4-net"]
        D1 --> T4
        R4["cloudflared access tcp relay"]
    end

    T1 --> P1H & RABH
    T2 --> P2H
    T3 --> P3H
    T4 --> P4H
    R2 & R3 & R4 -. "AMQP over tunnel" .-> RABH

    JUDGE["Judge / browser"] --> DEMO
    DEMO -. "demo day only:<br/>tunnel to assembly host frontend" .-> LA

    GIT[("GitLab + CI<br/>contract gates · PATH A artifacts")]
    LA & LB & LC & LD --- GIT
```

**Rules**
- Ollama is **never** tunneled — the debate loop on Laptop C calls `localhost:11434` only.
- Cloudflare is the internal mesh *because* there is no shared LAN; if the team ever
  lands on one Wi-Fi, switch internal calls to direct `http://<lan-ip>:port` and keep
  Cloudflare for the demo ingress only.
- Every internal hostname sits behind Cloudflare Access; the public demo hostname does not.

---

## 2. Hostname map (edit `yourdomain.com` → your real domain)

| Hostname | Laptop | Local target | Purpose | Access |
|---|---|---|---|---|
| `phase1.yourdomain.com` | A | `http://localhost:8090` | dataset, `/health`, `/files`, live telemetry sync | service token |
| `rabbit.yourdomain.com` | A | `tcp://localhost:5672` | shared AMQP bus (TCP tunnel) | service token |
| `phase2.yourdomain.com` | B | `http://localhost:8000` | ChromaDB memory API | service token |
| `phase3.yourdomain.com` | C | `http://localhost:8001` | MCP (Streamable HTTP / SSE) | service token |
| `phase4.yourdomain.com` | D | `http://localhost:8002` | veto / safety gateway | service token |
| `demo.yourdomain.com` | assembly host | `http://localhost:3000` | judge-facing frontend (demo day) | **public** |

---

## 3. One-time setup

### 3.1 Cloudflare account + domain (Laptop A owner does this once)
```powershell
winget install --id Cloudflare.cloudflared -e
cloudflared tunnel login                    # browser auth
```
Create a **Zero Trust service token** (free):
`https://one.dash.cloudflare.com` → Access → Service Auth → Service Tokens →
create `autosre-team` → save `CF-Access-Client-Id` + `CF-Access-Client-Secret`.
For each internal hostname create an Access Application → policy "Service Token"
→ require `autosre-team`. (Leave `demo.*` without Access.)

### 3.2 Create the four tunnels (on the laptop that owns each phase)
```powershell
cloudflared tunnel create phase1-net        # Laptop A
cloudflared tunnel create phase2-net        # Laptop B
cloudflared tunnel create phase3-net        # Laptop C
cloudflared tunnel create phase4-net        # Laptop D

cloudflared tunnel route dns phase1-net phase1.yourdomain.com
cloudflared tunnel route dns phase1-net rabbit.yourdomain.com
cloudflared tunnel route dns phase2-net phase2.yourdomain.com
cloudflared tunnel route dns phase3-net phase3.yourdomain.com
cloudflared tunnel route dns phase4-net phase4.yourdomain.com
```
Fill in `federation/cloudflared/final-tunnels.yml` (tunnel id + credentials path)
on each laptop, then run:
```powershell
cloudflared tunnel --config federation\cloudflared\final-tunnels.yml run
cloudflared service install                 # optional: auto-start on boot
```

### 3.3 Teammates: RabbitMQ relay (Laptops B, C, D)
```powershell
# one-time: put the service token in your env / .env.federation
cloudflared access tcp `
  --hostname rabbit.yourdomain.com `
  --url tcp://localhost:25672 `
  --id $env:CF_ACCESS_CLIENT_ID --secret $env:CF_ACCESS_CLIENT_SECRET
```
Now every phase connects to the shared bus with **no code changes**:
```
AMQP_URL=amqp://guest:guest@localhost:25672
```
(`guest` works because the relay listens on localhost.)

---

## 4. Live telemetry sync workflow (host → teammates)

```mermaid
sequenceDiagram
    autonumber
    participant H as Host (Laptop A)
    participant CF as Cloudflare (phase1.*)
    participant TM as Teammate laptop

    Note over H: Terminal 1: python federation/serve_dataset.py --port 8090<br/>Terminal 2: cloudflared tunnel run phase1-net
    H->>H: python simulate_full_telemetry.py --fresh<br/>(writes frontend_data/*.json)
    Note over H: serve_dataset.py reads disk fresh per request —<br/>new data is live instantly, no restart
    loop every 5–10 s
        TM->>CF: GET /health  (+ service-token headers)
        CF->>H: forward
        H-->>TM: dataset_generated_at
        alt generated_at changed
            TM->>CF: GET /dataset (+ token)
            CF->>H: forward
            H-->>TM: unified_master_dataset.json (~343 KB)
            TM->>TM: atomic write to local frontend_data/
        end
    end
    Note over CF: Access audit log records every teammate hit<br/>(who synced, when) → answers "who is connected"
```

**Host verification loop** (Terminal 3):
```powershell
while ($true) {
  Clear-Host
  Invoke-RestMethod http://localhost:8090/health |
    Format-List status, dataset_present, dataset_generated_at, server_time
  Start-Sleep 5
}
```

**Latency budget (different networks, via Cloudflare edge):**
- `/health` poll RTT: ~80–250 ms → teammates see new telemetry within **one poll interval (≤10 s)**.
- Dataset pull: ~343 KB → <1 s on any broadband.
- Live incident events over AMQP: one tunnel hop, small payloads → sub-second.
- The slow path is AI debate (seconds–minutes), not transport. Keep Ollama local (rule above).

---

## 5. End-to-end incident flow over this network

```mermaid
sequenceDiagram
    autonumber
    participant P1 as Phase 1 (A)
    participant MQ as RabbitMQ on A<br/>(tunneled to B/C/D)
    participant P2 as Phase 2 (B)
    participant P3 as Phase 3 (C)
    participant P4 as Phase 4 (D)

    P1->>MQ: autosre.incident.raw
    MQ->>P2: via relay localhost:25672
    P2->>P2: fingerprint + Chroma + topology + history
    P2->>MQ: autosre.incident.enriched
    MQ->>P3: consume
    P3->>P3: debate (local Ollama + debate_evidence/)
    P3->>MQ: autosre.action.proposed
    MQ->>P4: consume
    P4->>P4: schema → normalize → semantic veto → policy
    alt ALLOW
        P4->>MQ: autosre.action.allowed → execution adapter → audit → new telemetry → Phase 1
    else VETO / timeout / unreachable
        P4->>MQ: autosre.action.vetoed
        Note over P4: FAIL CLOSED — unreachable ≠ approval.<br/>Action becomes RECOMMENDATION_ONLY.
    end
```

---

## 6. Failure modes & fallbacks

| Failure | Symptom | Response |
|---|---|---|
| Named tunnel down on one laptop | teammates' `/health` polls fail | `cloudflared tunnel run` restarts with the **same hostname** — no URL re-sharing needed. Emergency: `.\federation\start-tunnel.ps1 -Phase <n>` quick tunnel + update `.env.federation`. |
| RabbitMQ tunnel flaps | producers can't publish | producers spool locally + retry (never silently drop); consumers reconnect automatically. |
| Cloudflare Access 403 | teammate forgot token headers | check `CF_ACCESS_CLIENT_ID/SECRET` in their `.env.federation`. |
| Phase 4 offline | no ALLOW arrives | fail closed → RECOMMENDATION_ONLY / human review. |
| No internet at venue | everything cross-network dies | **single-laptop assembly mode**: `docker compose up -d --wait` + `python simulate_full_telemetry.py --fresh` on one machine (the judging path in `AUTO_SRE_FINAL_END_TO_END_PLAN.txt`). |

---

## 7. Final `federation/.env.federation` shape

```dotenv
# Stable named-tunnel hostnames (commit-safe, no random URLs)
PHASE1_DATASET_URL=https://phase1.yourdomain.com
PHASE2_CHROMA_URL=https://phase2.yourdomain.com
PHASE3_MCP_URL=https://phase3.yourdomain.com
PHASE3_OLLAMA_URL=http://localhost:11434        # Laptop C only — never tunneled
PHASE4_VETO_URL=https://phase4.yourdomain.com

# Shared event bus via local relay (same value on every laptop)
AMQP_URL=amqp://guest:guest@localhost:25672

# Cloudflare Access service token (do NOT commit the secret — use local env)
CF_ACCESS_CLIENT_ID=<from Zero Trust dashboard>
CF_ACCESS_CLIENT_SECRET=<from Zero Trust dashboard>
```

---

## 8. What changes vs today's repo

1. `federation/start-tunnel.ps1` stays as the **fallback**; named tunnels become primary.
2. `federation/cloudflared/final-tunnels.yml` — ready-to-edit config (added with this doc).
3. Teammates add one relay command (§3.3) and two env vars.
4. `serve_dataset.py` needs **no changes** (already reads disk fresh per request).
5. Optional later: replace the AMQP-over-tunnel hop with Tailscale if the team wants
   direct P2P latency (`tailscale status` also gives peer identity for free).
