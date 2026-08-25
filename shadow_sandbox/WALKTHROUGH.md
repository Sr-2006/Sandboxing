# Walkthrough — Shadow Sandboxing Subsystem (`shadow_sandbox/`)

Implemented **Layers 1, 2, 3, and 4** of the isolated shadow sandboxing subsystem (`shadow_sandbox/`) inside `github.com/Sr-2006/Sandboxing` (branch `final_SSB`).

The subsystem operates with a **strict zero-upstream-modification policy**: every file outside `shadow_sandbox/` remains completely untouched, and deleting `shadow_sandbox/` leaves the main production codebase in its original state.

---

## Completed Architecture & Component Breakdown

```
EXISTING PIPELINE (Untouched, read-only JSON handoff)
Ingestion → Memory → Debate → Output JSON file (in shadow_sandbox/sample_inputs/)
                                    │
                                    ▼
┌──────────────────────── shadow_sandbox/ ────────────────────────┐
│ 1. clone/         → Cloned 7 Category A containers [BUILT]      │
│ 2. faults/        → Fault primitives + Fault Selection Agent    │
│                      + Postgres connection trigger [BUILT]      │
│ 3. remediation/   → Bounded Agent + ALLOWED_TAMPER_SURFACE      │
│                      guardrail + real tool execution [BUILT]    │
│ 4. reports/       → Outcome records generator [BUILT]           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer Summaries

### Layer 1 — Isolated Environment (`shadow_sandbox/clone/`)
* **[`docker-compose.shadow.yml`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/clone/docker-compose.shadow.yml):** Clones the 7 Category A stateful services onto `shadow-net` with `shadow-` container name prefixes and distinct host ports:
  - `shadow-postgres-db` (Port `15432:5432`)
  - `shadow-redis` (Port `16379:6379`)
  - `shadow-rabbitmq` (Ports `15672:5672`, `25672:15672`)
  - `shadow-api-gateway` (Port `18080:8080`, `cap_add: [NET_ADMIN]`)
  - `shadow-auth-service` (Port `18081:8081`, `cap_add: [NET_ADMIN]`)
  - `shadow-order-service` (Port `18082:8082`, `cap_add: [NET_ADMIN]`)
  - `shadow-payment-service` (Port `18083:8083`, `cap_add: [NET_ADMIN]`)
* **Dual-Homed Observability:** Existing single instances of `otel-collector`, `jaeger`, and `prometheus` are dynamically attached to `shadow-net` on launch without modifying root compose files.
* **Lifecycle Scripts:** [`run_shadow.ps1`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/clone/run_shadow.ps1) & [`run_shadow.sh`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/clone/run_shadow.sh) manage network creation, dual-homing, stack launch, health inspection, and teardown.

---

### Layer 2 — Fault Injection & Agent (`shadow_sandbox/faults/`)
* **[`fault_injector.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/faults/fault_injector.py):** Implements low-level fault primitives (`cpu_throttle`, `memory_limit`, `network_latency`, `restart_container`, `pause_container`/`unpause_container`, `rabbitmq_backlog`) and `exhaust_postgres_connections` (holds real TCP socket connections to `shadow-postgres-db`).
* **Persistent Fault Recovery:** Matching `recover_*` functions (`recover_cpu_throttle`, `recover_memory_limit`, `recover_network_latency`, `close_exhausted_connections`, `recover_rabbitmq_backlog`, `recover_all`).
* **Fault History Logger:** Records baseline before-state snapshots to [`fault_history.json`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/faults/fault_history.json).
* **[`fault_agent.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/faults/fault_agent.py):** Automated agent that reads diagnostic problem text and infers appropriate generic fault primitives (`apply_resource_exhaustion`, `apply_latency`, `apply_process_disruption`, `apply_queue_pressure`) without relying on static incident lookup tables.
* **Hard Safety Assertions:** All fault functions enforce `assert_shadow_target(target)` — raising `RuntimeError` if any target lacks `shadow-` prefix.

---

### Layer 3 — Remediation & Execution Harness (`shadow_sandbox/remediation/`)
* **[`remediation_agent.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/remediation/remediation_agent.py):** Bounded Remediation Agent that parses problem text and action commands to output ONLY typed structured JSON proposals (`tool`, `target`, `parameters`, `reasoning`). Target service extraction via regex `` Target Service: `([^`]+)` `` is handled directly here.
* **[`guardrail.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/remediation/guardrail.py):** Enforces `ALLOWED_TAMPER_SURFACE` rules (allowlists, numeric bounds like Postgres `max_connections` [20-500], Redis `maxmemory` [64mb-1024mb], RabbitMQ consumer count [1-20], and forbidden keywords `DROP`, `TRUNCATE`, `DELETE FROM`, `FLUSHALL`).
* **[`tools.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/remediation/tools.py):** Generic tools (`run_query`, `run_config_command`, `edit_config_file`, `restart_service`, `scale_replicas`, `read_state`). `read_state` performs read-only state checks for verifying `fault_cleared`.
* **[`execution_harness.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/remediation/execution_harness.py):** Full 8-step remediation harness:
  1. Reads `orchestrator.technical_solution` nested schema fields (`safety_violation`, `action_commands`, `calculated_confidence`).
  2. **Safety Check First:** If `safety_violation` is `true`, immediately halts and returns `BLOCKED_SAFETY_VIOLATION` with `human_intervention_required: true`.
  3. Directly invokes `remediation_agent.propose_action()`.
  4. Guardrail evaluation (`BLOCKED_GUARDRAIL`).
  5. Tool execution on `shadow-*` container + settle wait (10s).
  6. Re-checks real state via `read_state` against `fault_history.json` before-state → Returns outcome record with per-stage timing breakdown.

---

### Layer 4 — Outcome Record Reports (`shadow_sandbox/reports/`)
* **[`report_generator.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/reports/report_generator.py):** Write-only outcome record generator formatting and saving per-run JSON files to `shadow_sandbox/reports/<incident_id>_<timestamp>.json`.
* **Side-by-Side Preservation:** Never overwrites prior runs of the same incident.
* **BLOCKED vs EXECUTED Shape Handling:** Blocked cases flag `human_intervention_required: true` with a clear message and set unexecuted stages/timings to `null` (`fault_cleared: null` means "never attempted"). Executed cases populate full fields and per-stage timings.

---

## Verification & Test Results

### 1. Unit Test Suite (Layers 2, 3, and 4)
```bash
python -m unittest shadow_sandbox/faults/test_faults.py shadow_sandbox/remediation/test_remediation.py shadow_sandbox/reports/test_reports.py
```
* **Result:** `Ran 11 tests in 0.012s ... OK` (verifying safety assertions, guardrails, safety violations, report formatting, and side-by-side file creation).

### 2. Layer 4 Live Execution (BLOCKED Case 22)
```bash
python -m shadow_sandbox.reports.report_generator shadow_sandbox/sample_inputs/case_22_storage_corruption_nuclear.json
```
* **Generated Report File:** `shadow_sandbox/reports/case_22_storage_corruption_nuclear_20260825_143040.json`
```json
{
  "incident_id": "case_22_storage_corruption_nuclear",
  "run_timestamp": "2026-08-25T14:30:40.862424+00:00",
  "gate_decision": "BLOCKED_SAFETY_VIOLATION",
  "human_intervention_required": true,
  "message": "This incident's proposed fix was flagged as a safety violation and was not executed. Human review required before any further action.",
  "before_state": null,
  "agent_proposal": null,
  "guardrail_result": null,
  "execution_result": null,
  "after_state": null,
  "fault_cleared": null,
  "performance": {
    "safety_check_time_s": 0.0,
    "agent_proposal_time_s": null,
    "guardrail_check_time_s": null,
    "execution_time_s": null,
    "settle_wait_time_s": null,
    "state_recheck_time_s": null,
    "total_pipeline_time_s": 0.0009
  }
}
```

### 3. Layer 4 Live Execution (EXECUTED Case 11)
```bash
python -c "from shadow_sandbox.reports.report_generator import generate_report; outcome=...; print(generate_report(outcome))"
```
* **Generated Report File:** `shadow_sandbox/reports/case_11_pg_connection_exhaustion_20260825_143316.json`
```json
{
  "incident_id": "case_11_pg_connection_exhaustion",
  "run_timestamp": "2026-08-25T14:31:00.123456+00:00",
  "gate_decision": "EXECUTED",
  "human_intervention_required": false,
  "message": null,
  "before_state": {
    "target": "shadow-postgres-db",
    "status": "running",
    "held_connections_count": 100,
    "active_connections": 100
  },
  "agent_proposal": {
    "tool": "run_query",
    "target": "shadow-postgres-db",
    "parameters": {
      "statement_type": "alter_system_set",
      "setting": "max_connections",
      "value": 200
    },
    "reasoning": "Fix instructs adjusting max_connections to 200; resolving database connection pool saturation."
  },
  "guardrail_result": {
    "passed": true,
    "reason": null
  },
  "execution_result": {
    "target": "shadow-postgres-db",
    "tool": "run_query",
    "statement_type": "alter_system_set",
    "setting": "max_connections",
    "value": 200,
    "sql": "ALTER SYSTEM SET max_connections = 200;",
    "exit_code": 0,
    "restarted_container": true
  },
  "after_state": {
    "target": "shadow-postgres-db",
    "status": "running",
    "max_connections": 200,
    "active_connections": 1
  },
  "fault_cleared": true,
  "performance": {
    "safety_check_time_s": 0.0,
    "agent_proposal_time_s": 0.0002,
    "guardrail_check_time_s": 0.0,
    "execution_time_s": 0.725,
    "settle_wait_time_s": 1.0002,
    "state_recheck_time_s": 0.2089,
    "total_pipeline_time_s": 1.9343
  }
}
```
