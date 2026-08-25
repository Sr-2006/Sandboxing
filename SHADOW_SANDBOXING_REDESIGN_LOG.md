# Shadow Sandboxing Redesign — Finalized Design Log
### A living document. Updated only when something is explicitly confirmed ("yes").
### Working repo: github.com/Sr-2006/Sandboxing (branch final_SSB) — this repo
### contains a cloned copy of the real production system's files, kept
### separate specifically so the real production repo is never touched.
### Real production system referenced for context: github.com/sk101-art/asre
### Fix input source (read-only, external): github.com/sk101-art/debate (branch final_v1)

---

## 0. THE GOAL (confirmed)

Build a subsystem that:
1. Clones the production environment, isolated.
2. Takes a fix proposed by the existing tri-debate RCA system (a separate,
   already-built black box) and actually applies it to the clone.
3. Observes whether the real underlying problem actually got resolved.
4. Does **nothing else** — must never modify, extend, or depend on code from
   the existing Ingestion → Memory → Debate pipeline. That pipeline is
   read-only from this subsystem's point of view: we only ever read the JSON
   files it produces.

**The litmus test for the whole design:** you must be able to delete this
entire subsystem and have the existing Ingestion/Memory/Debate pipeline run
identically to how it did before this subsystem ever existed. If deleting it
would break or change anything upstream, the boundary has been violated.

**Why this boundary is non-negotiable:** if this subsystem ever modifies
files belonging to the existing Ingestion/Memory/Debate pipeline directly —
adding parameters to its functions, adding new functions inside its shared
modules — it becomes load-bearing logic inside that pipeline rather than a
separate thing that reads its output. That is the specific failure mode this
design exists to prevent.

---

## 1. HIGH-LEVEL ARCHITECTURE (confirmed)

**Implementation status:** Layer 1 (`clone/`) has been built and is running.
Layers 2–4 are design-complete but not yet built.

```
EXISTING PIPELINE (untouched, never imported by shadow code)
Ingestion → Memory → Debate → writes a fix JSON file to disk
                                        │
                                        │ read-only file handoff —
                                        │ the ONLY connection point
                                        ▼
┌─────────────────────── shadow_sandbox/ ───────────────────────┐
│                                                                  │
│  1. clone/         → isolated copy of the real environment      │
│                      [BUILT]                                    │
│  2. faults/        → fault-selection agent reads the incident   │
│                      description, chooses + applies a matching  │
│                      fault via generic primitives [DESIGNED]    │
│  3. remediation/   → reads the fix JSON, a bounded agent         │
│                      proposes a structured action, applies it,  │
│                      checks it [DESIGNED]                       │
│  4. reports/       → outcome files, written here only           │
│                      [DESIGNED]                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. LAYER 1 — `clone/` (confirmed)

**What gets cloned (Category A — real, stateful, "the environment"):**
Sourced from the actual `docker-compose.yml` in `asre` (branch `final_cf`):

| Service | Image / build | Why cloned |
|---|---|---|
| `postgres-db` | `postgres:16.2-alpine` | Real connection limits, real data |
| `redis` | `redis:7.2.4-alpine` | Real memory-eviction behavior |
| `rabbitmq` | `rabbitmq:3.13.0-management-alpine` | Real queue-backlog behavior |
| `api-gateway` | built from `./api-gateway` | Real application logic |
| `auth-service` | built from `./auth-service` | Real application logic |
| `order-service` | built from `./order-service` | Real application logic |
| `payment-service` | built from `./payment-service` | Real application logic |

**Example:** `shadow-postgres-db` is the same Postgres image, initialized with
the same `postgres-init/init.sql` schema, just on `shadow-net` with different
host ports — so a real connection-exhaustion test genuinely exhausts a real
Postgres, just not the one customers use.

**What does NOT get cloned (Category B — observability tooling, not "the environment"):**
`jaeger`, `otel-collector`, `prometheus`, `grafana`, `loki`. These hold no
state that a fault or a fix would ever target — they're windows, not patients.
Instead, the existing single instances of these tools should simply be able to
see both networks (dual-homed), so shadow activity shows up in the same
dashboards you already use, rather than duplicating them.

**Confirmed detail:** production's `api-gateway`, `auth-service`,
`order-service`, `payment-service` already carry `cap_add: [NET_ADMIN]` in the
real compose file — the clone inherits this as-is, no new capability grant
needed for network-level faults.

---

## 3. LAYER 2 — `faults/fault_injector.py` + fault-selection agent (confirmed)

**Core design (confirmed):** a small, standalone tool. Does not import or
extend the real `chaos_orchestrator.py`. Every function refuses to operate on
any container whose name doesn't start with `shadow-`.

**Two fault mechanisms exist in the real system, and only one is in scope for v1:**

| Mechanism | Example | In scope for v1? |
|---|---|---|
| **Docker-SDK faults** — Docker acting on a container from the outside; the app inside has no idea anything happened | `cpu_throttle`, `memory_limit`, `network_latency` (`tc qdisc`), `restart_container`, `pause_container` | **Yes** |
| **HTTP faults** — a real HTTP call to a `/chaos/*` route *built into the Spring Boot app itself*, which deliberately misbehaves on request | `http_deadlock`, `http_sql_lock`, `http_exhaust_pool` (all use `X-Chaos-Token` header auth) | **Deferred** — these test app-level failures (a stuck thread, a leaking heap); the sample cases are mostly infrastructure-level (DB/cache/broker), so they're not needed to test those real-scope cases. (Note: since the shadow services are built from the same source as production, these endpoints likely work automatically once cloned — no extra wiring needed if/when they're added later.) |

**Example of the difference:** `cpu_throttle("shadow-postgres-db")` works the
instant the container exists — Docker doesn't care what's running inside.
`http_exhaust_pool` only works if `payment-service`'s Java code already
contains a controller route for `/chaos/exhaust-pool` — it's the app breaking
itself on request, not Docker acting from outside.

### CONFIRMED: fault selection is agent-driven, not a manual or hand-mapped step

**The requirement:** the full pipeline must be automated end to end — nothing
in this subsystem should require a person to read an incident and manually
decide which fault to inject.

**Why a hand-written `incident_type → fault` mapping was considered and
rejected:** a fixed table only knows what someone anticipated in advance —
the exact same closed-world limitation already identified and rejected for
the remediation layer's action dispatch. A brand-new incident description
the table's author never imagined gets no fault at all. For genuine
automation against incidents not known in advance, this doesn't hold up.

**Confirmed instead: a fault-selection agent, using generic fault
primitives** — not one bespoke function per specific incident type:
```python
apply_resource_exhaustion(target, resource_type, severity)  # connections, memory, disk, etc.
apply_latency(target, delay_ms)
apply_process_disruption(target, mode)                      # pause / restart / kill
apply_queue_pressure(target, backlog_size)
```
The agent reads an incident's diagnostic description (its problem statement)
and decides which primitive, on which target, at what severity, best
approximates the described condition — the same kind of inference the
remediation-layer agent performs on a fix instruction, just applied to a
fault description instead.

**Confirmed: the input schema this subsystem consumes is NOT modified to
support this.** The diagnostic fields available (a plain-language incident
description, root-cause summary, reasoning) describe an incident the way an
engineer would describe a real outage after the fact — they do not, and are
not expected to, contain an explicit fault-reproduction recipe (a specific
value to set, a specific command to run to break something). This is
confirmed as correct and NOT a gap to fix by requesting a schema change from
the fix-input source: doing so would create a two-way dependency (this
subsystem requiring an upstream system to change specifically to serve it),
breaking the one-directional, read-only relationship this design otherwise
maintains everywhere else. The fault-selection agent's entire purpose is to
bridge exactly this gap — inferring a reproduction approach from language
that was never written with fault-injection in mind — the same justification
already used for the remediation-layer agent inferring a fix from language
that was never written as a structured command.

**Confirmed: the safety guardrail for this agent is deliberately simpler
than the remediation layer's.** A wrong or imprecise fault choice here is
low-stakes by construction — the shadow environment is fully disposable, so
an inaccurate fault selection just means the wrong test happened, not that
anything is damaged in a way a stack teardown/rebuild doesn't reset. One
hard rule is sufficient:
```python
if not target.startswith("shadow-"):
    raise RuntimeError("Refusing to inject a fault into a non-shadow target")
```
Severity bounds (e.g. capping how full a disk gets filled) may be added for
realism later, but are not a required safety control the way the
remediation layer's category-level guardrails are.

**Confirmed, accepted trade-off:** the same non-determinism already accepted
for the remediation layer applies here too — re-processing the same incident
could result in the agent choosing a different fault primitive or severity
each time. Accepted as consistent with the same trade-off already made
elsewhere in this design, not treated as a new risk requiring a new fix.

### Gap found, not yet built: connection-exhaustion trigger
None of the Docker-SDK primitives (`restart`/`pause`/`cpu_throttle`/
`memory_limit`/`network_latency`) can reproduce a Postgres connection-pool
exhaustion — Postgres's connection limit is an application-level setting
inside Postgres, not a container resource Docker can throttle. **Needs its
own function**: a small script that opens N real connections to
`shadow-postgres-db` (e.g. via `psycopg2`) and holds them open until the
pool is full. This becomes one of the concrete implementations behind the
`apply_resource_exhaustion` primitive above.

### Gap found, not yet built: fault-history logging
`fault_injector.py` needs a minimal local JSON log recording what fault was
applied, by the agent, to what target, at what time, and with what "before"
state — e.g. `shadow_sandbox/faults/fault_history.json`, written by this
layer only. Without this, the remediation layer has no baseline to compare
"after the fix" against.

### Gap found, not yet built: recovery functions
Faults split into two behavioral categories:
- **Instant faults** (`restart`, `kill`) — happen once, nothing lingers, no
  recovery needed.
- **Persistent-state faults** (`cpu_throttle`, `memory_limit`,
  `network_latency`, the connection-exhaustion script) — set a condition that
  **stays in effect until explicitly undone**. Re-running the same fault
  without recovering first doesn't cleanly retrigger it — it risks *stacking*
  (e.g. opening another 100 connections on top of an already-held 100, or an
  unclear "does the second `tc qdisc` call replace or stack on the first"
  outcome).

**Needs**: a matching `recover_*` function per persistent fault
(`recover_cpu_throttle`, `recover_memory_limit`, `recover_network_latency`,
`close_exhausted_connections`), used in this sequence:
```
1. Recover (reset to clean baseline, in case a prior test left state behind)
2. Agent selects and applies a fault → shadow environment is genuinely broken, once
3. Run the harness's fix
4. Check if it cleared
5. Recover again → clean, ready for the next test
```
This is a deliberate, explicit step — not an automatic self-healing watchdog.

---

## 4. LAYER 3 — `remediation/` (confirmed & built)

### Confirmed: correct schema reading
The real fix JSON (from `debate` repo, `output3b/case_11_pg_connection_exhaustion.json`)
nests everything three levels deep:
```json
{
  "incident_id": "case_11_pg_connection_exhaustion",
  "problem": "Target Service: `postgres-db` - PostgreSQL max connection limit reached...",
  "orchestrator": {
    "technical_solution": {
      "action_commands": ["Reset max_connections and adjust connection pool limit"],
      "confidence": 63,
      "safety_violation": false
    }
  }
}
```
These fields must be read from this correct nested path — `safety_violation`,
`action_commands`, and `confidence` do **not** exist at the top level of the
file, so any code reading them there would silently get incorrect defaults
(`False`, `[]`, `0`) instead of the real values. This redesign reads the
correct nested path from the start.

### Confirmed: translation consolidation in `remediation_agent.py`
- `action_adapter.py` was removed entirely. Target service extraction (via regex
  `` Target Service: `([^`]+)` ``) and translation of action commands into typed
  structured proposals is handled fully inside `remediation_agent.py`.
- `execution_harness.py` calls `remediation_agent.propose_action()` directly.

### Confirmed: `execution_harness.py` step-by-step flow
```
run(fix_json_path: str) -> outcome_record

1. Load the JSON file.
2. Read incident["orchestrator"]["technical_solution"] (correct nesting).
3. If safety_violation is true → STOP immediately.
   Write outcome: BLOCKED_SAFETY_VIOLATION. No agent call, no guardrail check, no Docker call.
4. Call remediation_agent.propose_action() directly on problem text & action_commands.
5. If unmapped/invalid proposal → STOP. Write outcome: BLOCKED_UNMAPPED.
6. Evaluate proposal against ALLOWED_TAMPER_SURFACE guardrail.
   If guardrail failed → STOP. Write outcome: BLOCKED_GUARDRAIL.
7. For mapped & validated action:
   a. Force target to shadow-{target} — hard-checked in tools.py and harness.
   b. Apply the action for real against that shadow-* container/service.
   c. Wait a bounded settle time (default 10s).
8. Re-check real state via read_state tool against live container / Postgres query.
9. Write outcome: fault_cleared: true/false, performance timing breakdown, plus what was attempted.
```
**Dependency note:** step 7 reads Layer 2's fault-history log file. This is
the one and only link between Layer 2 and Layer 3 — a file read, not a code
import — preserving the "delete any layer, the others still work" property.

### Confirmed (important): step 6b must be REAL execution, not a stub
**Question raised and resolved:** should non-`restart` actions (like
`reset_config_param`) just log "would execute X" in v1, with real execution
added later?

**Answer: no — this would defeat the subsystem's entire purpose.** The whole
point of shadow sandboxing is answering "did the fix actually work?" If step
6b only logs what it *would* do without doing it, step 7's check has nothing
real to measure — the fault condition would still show as unresolved on
*every* non-restart case, regardless of whether the tri-debate's fix was
actually good. That's not "tested and failed," it's "never tested," dressed
up to look like a real result. So: **real, per-service handlers are required
from the first working version**, not deferred.

**Scope, per the real `output3b` sample set (5 cases match your actual stack):**
- Postgres config changes (`case_11`, `case_14`)
- Redis eviction-policy change (`case_12`)
- RabbitMQ consumer scaling (`case_16`)
- (gRPC/app-level, `case_20` — app-level, may need the deferred HTTP-fault
  mechanism from Layer 2 to test meaningfully; not yet designed)

### CONFIRMED: bounded agent + allow/forbid rules (final decision for Layer 3 execution)

**The path not taken, briefly:** a hand-written `(intent, service_type) →
function` dispatch table (fully deterministic, no agent) was on the table as
the safer default. **Decided against, in favor of an agent-based approach —
explicitly WITHOUT any skill-store / self-healing / repeat-skipping loop.**

**What was ruled out along the way, and why (for the record):**
- A fully unbounded agent with direct execution access — rejected. Blurs
  accountability (can't tell "tri-debate's fix was bad" from "the sandbox's
  own agent misapplied it"), and reintroduces the exact "guessing when
  unsure" risk that `UNMAPPED_ACTION` was designed to avoid.
- A skill-store / RL self-healing loop (cache a working fix by fingerprint,
  auto-replay it on a repeat, skip tri-debate + sandboxing) — raised, explored
  in depth, then explicitly ruled **out of scope**. Reasoning: (1) it would
  have required new logic inside the *existing* Ingestion/Debate pipeline
  (a fingerprint-and-skip hook), directly violating the "shadow_sandbox only
  ever reads the existing pipeline's output, never changes its behavior" rule;
  (2) it's a different phase's job entirely — the user was explicit that
  hashing/logging/fingerprinting-based repeat-detection is **not part of this
  task**; sandboxing's only job is "take a fix, apply it to the clone, check
  if it worked." Nothing about skills, suggestions, or repeat-detection lives
  in `shadow_sandbox/`.

**Final design, confirmed:**
```
Fix text ("Reset max_connections and adjust connection pool limit")
   │
   ▼
Bounded agent interprets the fix and PROPOSES a specific action
(e.g. "run pg_reset_config on shadow-postgres-db, set max_connections=150")
   │
   ▼
Proposal checked against ALLOWED_TAMPER_SURFACE rules (per service type) —
this check lives OUTSIDE the agent, the agent cannot bypass it
   │
   ├── Proposal matches an allowed operation → execute it for real,
   │   via the same real, deterministic per-service functions discussed
   │   earlier (pg_reset_config, redis_reset_config, etc.) — the agent
   │   picks WHICH known-safe action to take, it does not invent or run
   │   arbitrary commands itself.
   │
   └── Proposal matches a forbidden operation, or isn't recognized →
       BLOCKED, same fail-closed behavior as BLOCKED_UNMAPPED, with the
       agent's full reasoning logged for a human to review.
```

**Rules structure, confirmed shape (values are illustrative, not final):**
```python
ALLOWED_TAMPER_SURFACE = {
    "postgres": {
        "allowed_settings": ["max_connections", "shared_buffers", "work_mem"],
        "forbidden_operations": ["DROP", "TRUNCATE", "DELETE FROM", "ALTER TABLE", "GRANT", "REVOKE"],
    },
    "redis": {
        "allowed_settings": ["maxmemory-policy", "maxmemory"],
        "forbidden_operations": ["FLUSHALL", "FLUSHDB", "CONFIG SET requirepass"],
    },
    "rabbitmq": {
        "allowed_operations": ["scale_consumer_count", "adjust_prefetch"],
        "forbidden_operations": ["delete_queue", "delete_vhost"],
    },
}
```

**Known, accepted trade-off (explicitly not being fixed):** without a skill
store, the agent's non-determinism (same incident, possibly different
proposed action on different runs) is **not resolved** — re-testing the same
incident twice could genuinely produce two different real actions and two
different outcomes. This was raised directly and accepted as an out-of-scope
cost, since fixing it would require the skill-store approach that was just
ruled out. Full detailed logging of the agent's reasoning and proposed action
(before execution) is the mitigation — it makes any such variance fully
inspectable after the fact, even though it doesn't prevent the variance.

**Confirmed & Implemented:** `ALLOWED_TAMPER_SURFACE` guardrail rules per service are implemented in `shadow_sandbox/remediation/guardrail.py`, evaluating structured agent proposals against allowed settings, numeric bounds, and forbidden keywords.

### CONFIRMED: real-schema findings from reviewing all 12 `output3b` cases

Reviewing the actual JSON structure of all 12 sample cases (not just one)
surfaced four concrete corrections to how Layer 3 must read the fix schema.
These are now locked in as confirmed, not assumptions:

1. **`orchestrator.technical_solution.confidence` is not a usable gating
   signal.** It reads exactly `95` in all 12 sample cases, including the
   vetoed `case_22` (`safety_violation: true`) — it does not vary and
   appears to be the orchestrator's own self-reported number rather than
   anything computed from evidence. **Gate on
   `orchestrator.technical_solution.calculated_confidence` instead** — this
   field genuinely varies (61–88 across the sample set) and tracks real
   signals like `component_agreement`.

2. **`consensus_quality` is unproven as a discriminating signal.** All 12
   cases read `"HIGH"`, even ones where `calculated_confidence` is as low as
   61 and `component_agreement` as low as 0.333 (only 1 of 3 agents agreed).
   Do not rely on this field to distinguish strong cases from shaky ones
   until it's seen varying on a larger dataset.

3. **`round_2` is `null` in every one of the 12 cases.** The schema supports
   a second debate round when `consensus.debate_required` is true, but this
   sample set never actually populates it. Layer 3 has never been tested
   against a file where `round_2` contains real data — treat that as an
   **untested schema branch**, not an assumed-safe one, when building the
   parser.

4. **Confirmed, with direct evidence: `safety_violation` must be checked
   first and never re-derived from reading `action_commands` text.**
   `case_22`'s actual `action_commands` read as completely benign —
   *"Initiate a rolling restart of the storage-controller service,"*
   *"Monitor disk usage,"* *"Perform data scrub if necessary"* — nothing
   in them looks dangerous. The actual hazard (a proposed `rm -rf`) only
   surfaces inside `scoring_metadata.blocked_command`, which is itself a
   large blob of concatenated narrative text, not a clean, isolated command
   string. **This proves a text/keyword scan over `action_commands` would
   have missed this case's real danger entirely** — the boolean
   `safety_violation` flag is the only reliable signal, exactly as already
   designed in the harness's step 2. This is now a confirmed, evidence-backed
   requirement, not just a cautious default.

### CONFIRMED: the three remaining Layer 3 open questions, resolved

**1. Agent output format: structured schema, not free text.**
The agent must emit a fixed JSON shape — tool name, target, and a
`parameters` object with typed fields — never a raw SQL string or shell
command:
```json
{
  "tool": "run_query",
  "target": "postgres-db",
  "parameters": {"statement_type": "alter_system_set", "setting": "max_connections", "value": 200},
  "reasoning": "Fix instructs lowering/adjusting max_connections; current value is 100/100 saturated."
}
```
Reasoning: a guardrail comparing `parameters.setting` against an allowlist
and `parameters.value` against numeric bounds is reliable arithmetic/set-
membership. A guardrail parsing a raw generated SQL/command string for the
same intent has to correctly parse language and catch every phrasing
variant of the same dangerous command — a known-fragile pattern. The actual
tool function (`run_query`, etc.) is responsible for turning validated
structured parameters into the real command; the agent never free-texts
the command itself.

**2. `read_state` tool — confirmed, added to the tool set.**
```python
def read_state(connection_target: str, query: str) -> dict:
    if not connection_target.startswith("shadow-"):
        raise RuntimeError(f"Refusing to read state from non-shadow target: {connection_target}")
    conn = get_connection_for(connection_target)
    return {"result": conn.execute_read_only(query)}
```
Required, not optional — the harness's step 7 (re-checking real state to
determine `fault_cleared`) has no other way to function. Lowest-risk tool
in the set since it's read-only by construction; needs only the same
shadow-only target check every other tool has, no category-level guardrail
beyond that.

**3. Concrete allow/forbid values — first real version, scoped to the 5
real-case categories (Postgres, Redis, RabbitMQ), not an open-ended list:**
```python
ALLOWED_TAMPER_SURFACE = {
    "postgres": {
        "statement_types": {
            "alter_system_set": {
                "allowed_settings": ["max_connections", "shared_buffers", "work_mem", "statement_timeout"],
                "bounds": {
                    "max_connections": {"min": 20, "max": 500},
                    "shared_buffers": {"min": "64MB", "max": "2GB"}
                }
            },
            "set": {"allowed_settings": ["work_mem", "statement_timeout"]}
        },
        "forbidden_always": ["drop", "truncate", "delete from", "alter table", "grant", "revoke"]
    },
    "redis": {
        "config_keys": {
            "maxmemory-policy": {"allowed_values": ["volatile-lru", "allkeys-lru", "volatile-ttl", "noeviction"]},
            "maxmemory": {"bounds": {"min": "64mb", "max": "1gb"}}
        },
        "forbidden_always": ["flushall", "flushdb", "config set requirepass"]
    },
    "rabbitmq": {
        "operations": {
            "scale_consumer_count": {"bounds": {"min": 1, "max": 20}},
            "adjust_prefetch": {"bounds": {"min": 1, "max": 1000}}
        },
        "forbidden_always": ["delete_queue", "delete_vhost", "delete_exchange"]
    }
}
```
These values are drawn directly from what the 5 real-scope `output3b`
cases actually need (Postgres connection/memory tuning for `case_11`/
`case_14`, Redis eviction policy for `case_12`, RabbitMQ consumer scaling
for `case_16`) — not speculative. Numeric bounds are conservative starting
points meant to be tightened or loosened after real test runs, not treated
as final.

**Layer 3 (`remediation/`) is fully implemented, verified, and built.**

---

## 5. LAYER 4 — `reports/` (confirmed & built)

**Role:** write-only assembly of what happened, per incident. Not a
decision-maker — every field traces back to something an earlier layer
already produced. No new logic lives here.

**Confirmed: one outcome-record file per incident run**, at
`shadow_sandbox/reports/<incident_id>_<timestamp>.json`. Files are never
overwritten — repeated runs of the same incident (expected, given the
agent's known non-determinism) are preserved side by side rather than
replacing each other, so multiple runs of the same case can be compared.

**Confirmed shape, for a fully executed case:**
```json
{
  "incident_id": "case_11_pg_connection_exhaustion",
  "run_timestamp": "2026-08-23T10:15:00Z",
  "gate_decision": "EXECUTED",
  "before_state": {
    "source": "fault_injector.py's fault_history.json",
    "active_connections": 100,
    "max_connections": 100
  },
  "agent_proposal": {
    "tool": "run_query",
    "target": "shadow-postgres-db",
    "parameters": {"statement_type": "alter_system_set", "setting": "max_connections", "value": 200},
    "reasoning": "Fix instructs adjusting max_connections; current value is 100/100 saturated."
  },
  "guardrail_result": {"passed": true, "reason": null},
  "execution_result": {"executed": true, "tool_output": "ALTER SYSTEM SET max_connections = 200; restarted container"},
  "after_state": {
    "read_via": "read_state tool",
    "active_connections": 42,
    "max_connections": 200
  },
  "fault_cleared": true,
  "performance": {
    "safety_check_time_s": 0.01,
    "agent_proposal_time_s": 11.4,
    "guardrail_check_time_s": 0.02,
    "execution_time_s": 1.8,
    "settle_wait_time_s": 10.0,
    "state_recheck_time_s": 0.3,
    "total_pipeline_time_s": 23.53
  }
}
```

**Confirmed shape, for a blocked case** (`gate_decision` is one of
`BLOCKED_SAFETY_VIOLATION` / `BLOCKED_GUARDRAIL` / `BLOCKED_UNMAPPED`):
fields for stages that never ran are `null`, not a default value like
`false` or `0` — `fault_cleared: null` means "never attempted," which is
distinct from `fault_cleared: false` ("attempted, did not work"). A
`human_intervention_required` field and a plain-language `message` are
included specifically for blocked cases, so a person scanning reports
later can immediately tell which incidents need their attention without
having to interpret `gate_decision` codes. Example:
```json
{
  "incident_id": "case_22_storage_corruption_nuclear",
  "run_timestamp": "...",
  "gate_decision": "BLOCKED_SAFETY_VIOLATION",
  "human_intervention_required": true,
  "message": "This incident's proposed fix was flagged as a safety violation and was not executed. Human review required before any further action.",
  "agent_proposal": null,
  "guardrail_result": null,
  "execution_result": null,
  "after_state": null,
  "fault_cleared": null,
  "performance": {
    "safety_check_time_s": 0.01,
    "agent_proposal_time_s": null,
    "guardrail_check_time_s": null,
    "execution_time_s": null,
    "settle_wait_time_s": null,
    "state_recheck_time_s": null,
    "total_pipeline_time_s": 0.01
  }
}
```
For an `EXECUTED` case, `human_intervention_required` is `false` and
`message` is `null`.

**Confirmed: a blocked case never halts the pipeline.** The safety gate
that produced the block still fires exactly as designed — nothing here
weakens that. What changes is what happens immediately after: the
orchestrator writes this report, with `human_intervention_required: true`
clearly flagged, and **moves on to the next incident automatically**,
rather than stopping the whole run to wait for a person. This keeps the
safety guarantee (a human must review this specific incident before it
goes further) while still keeping the overall pipeline fully unattended —
one incident needing review does not block every incident after it.

**Confirmed: per-stage timing, not a single total-time number.** Each
pipeline stage's wall-clock time is recorded individually (safety check,
agent proposal, guardrail check, execution, settle wait, state re-check),
plus a total. Reasoning: a single aggregate number would hide exactly the
kind of thing worth knowing later — e.g. confirming the agent call is
consistently the dominant cost, or that a flat settle-wait value is too
short for a specific kind of operation (such as a full service restart)
versus too long for another (such as a live config change with no
restart). Per-stage timing lets this be discovered from real outcome data
later, rather than guessed at design time.

**Confirmed: no aggregate scoring gate in this layer.** Only a
per-incident outcome record — nothing here computes a pass/fail threshold,
an accuracy percentage, or any summary across multiple runs. The stated
goal for this subsystem is "did this specific fix work on this specific
incident" — that question is fully answered by one clean record per run.
An aggregate trust score across many runs is a distinct, separate question
that has not been scoped as part of this design.

**Confirmed: nothing reads these files back automatically.** No dashboard,
no consumer script, no aggregation step exists yet. These are terminal
output, meant to be opened by a human (or by tooling built later, as a
separate, explicitly scoped decision) — Layer 4 produces, it does not
consume, matching every other layer's boundary in this design.

---

## 6. THE PIPELINE ORCHESTRATOR (confirmed — build last, after Layers 2-4)

**Why this exists, and why it's separate from the four layers above:**
each layer (`faults/`, `remediation/`, `reports/`) is built to process ONE
incident per invocation — that was deliberate, so each layer stays small
and independently testable. But full automation — pointing the system at
`sample_inputs/` and having it work through every incident unattended,
with no manual invocation per case — does not happen automatically just
because each layer is automated internally. Something has to call the
layers, in the right order, once per incident, in a loop. That something
is this orchestrator. It contains no new decision-making logic of its own
— it is purely sequencing.

**Confirmed: build this only after Layers 2 (faults/), 3 (remediation/),
and 4 (reports/) all individually exist and work standalone.** There is
nothing to orchestrate until all three exist, and guessing at Layer 3/4's
interface before they're built would likely require rewriting this
component once their real return shapes are known.

**Confirmed flow, per incident, whether triggered by a one-time batch run
or by watch mode (below):**
```python
def process_incident(incident_file):
    incident = load(incident_file)

    fault_decision = fault_agent.select_fault(incident)
    if fault_decision.primitive is None:
        # matches the fail-closed behavior confirmed in section 3 —
        # an incident type with no honestly-reproducible fault
        report.write(incident, gate_decision="SKIPPED_NO_SUITABLE_FAULT")
        return

    fault_injector.recover_all(fault_decision.target)   # clean baseline first
    fault_injector.apply(fault_decision)                 # break it, for real
    fault_injector.log_fault_event(fault_decision)

    outcome = execution_harness.run(incident_file)       # Layer 3: fix it, check it

    fault_injector.recover_all(fault_decision.target)   # clean up after
    reports.write(outcome)                               # Layer 4, including
                                                           # human_intervention_required
                                                           # and message for blocked cases

    # a BLOCKED_* outcome never halts the pipeline — the safety gate still
    # fired correctly, but processing simply moves on to the next incident
```

**Confirmed: two run modes, both calling `process_incident()` per file —
this was raised as a genuine automation gap and is now addressed:**

1. **Batch mode** — loops once over every file already present in
   `sample_inputs/` (or wherever incidents are read from) and exits when
   done. Useful for a one-off test run against a known set of sample
   cases.

2. **Watch mode (the actual default for "fully automated")** — the
   orchestrator does not exit after one pass. It continuously watches a
   designated incoming-incidents folder (e.g. via polling on an interval,
   or a filesystem-change watcher), and the moment a new fix JSON appears
   there, it is picked up and run through `process_incident()`
   automatically — no manual copy step, no manual re-invocation of the
   script per incident. This is the mode that actually satisfies "the
   whole thing runs on its own": once started, it requires no further
   action for new incidents to be processed as they arrive.

Starting the orchestrator itself (i.e. running the process at all) is
still a one-time action — this design does not include an OS-level
service/auto-start mechanism, since that is an environment/deployment
concern, not a design decision about this subsystem's logic. Everything
*after* that one start is unattended.

**Confirmed location:** `shadow_sandbox/run_pipeline.py` — sits at the
`shadow_sandbox/` top level, not inside any single layer's folder, since
it depends on and calls all three.

---



## 7. STATUS

**Layers 1 (`clone/`), 2 (`faults/`), 3 (`remediation/`), and 4 (`reports/`) are implemented and built.** 
- **Layer 1 (`clone/`):** Cloned 7 Category A containers, dual-homed observability.
- **Layer 2 (`faults/`):** Docker-SDK fault primitives, connection-exhaustion daemon, persistent recovery, fault-history logging, and fault-selection agent built.
- **Layer 3 (`remediation/`):** Bounded Remediation Agent, `ALLOWED_TAMPER_SURFACE` guardrail, container tools, and 8-step execution harness built. Translation consolidated into `remediation_agent.py` (`action_adapter.py` removed).
- **Layer 4 (`reports/`):** Write-only outcome record generator formatting and preserving side-by-side JSON reports (`shadow_sandbox/reports/<incident_id>_<timestamp>.json`).

The pipeline orchestrator (section 6) is design-complete and scheduled to be built as the final layer.

---

*This document reflects only what has been explicitly confirmed ("yes") in
conversation. Anything marked "open" or "not yet decided" is deliberately
excluded from being treated as settled design.*
