# Walkthrough — Layer 4: Outcome Record Reports (`shadow_sandbox/reports/`)

Implemented **Layer 4 (`reports/`)** of the isolated shadow sandboxing subsystem (`shadow_sandbox/`) inside `github.com/Sr-2006/Sandboxing` (branch `final_SSB`).

---

## 1. Overview & Architectural Boundaries

Layer 4 is a **write-only outcome record generator**.
- **Input:** Outcome dictionary produced by Layer 3 (`execution_harness.py`).
- **Output:** Timestamped JSON report files stored at `shadow_sandbox/reports/<incident_id>_<timestamp>.json`.
- **Strict Scope Boundaries:**
  - Writes only — does not read back, aggregate, score, or consume its own output.
  - Never overwrites prior runs — repeated runs of the same incident are preserved side-by-side.
  - Does not recompute or re-derive anything already determined by Layer 3.

---

## 2. Key Features Implemented

### A. Report Generator Module ([`report_generator.py`](file:///c:/Users/Shashank/OneDrive/Desktop/Smart%20horizon%20hackathon/ARSE_Final/shadow_sandbox/reports/report_generator.py))
* `generate_report(outcome: Dict[str, Any], reports_dir: Optional[str] = None) -> str`
* Formats records to match Section 5 of `SHADOW_SANDBOXING_REDESIGN_LOG.md`.
* Automatically creates target directory if missing.

### B. BLOCKED vs EXECUTED Shape Handling
* **`BLOCKED_*` cases (`BLOCKED_SAFETY_VIOLATION`, `BLOCKED_GUARDRAIL`, `BLOCKED_UNMAPPED`):**
  - `human_intervention_required: true`
  - Plain-language explanation in `message` field.
  - Fields for unexecuted stages set to `null` (`agent_proposal: null`, `guardrail_result: null`, `execution_result: null`, `after_state: null`, `fault_cleared: null`).
  - `fault_cleared: null` signifies "never attempted" (distinct from `false` = "attempted, failed").
  - Unexecuted stage timings in `performance` set to `null`.
* **`EXECUTED` cases:**
  - `human_intervention_required: false`
  - `message: null`
  - All stage fields populated (`before_state`, `agent_proposal`, `guardrail_result`, `execution_result`, `after_state`, `fault_cleared: true/false`).
  - Full per-stage timing breakdown (`safety_check_time_s`, `agent_proposal_time_s`, `guardrail_check_time_s`, `execution_time_s`, `settle_wait_time_s`, `state_recheck_time_s`, `total_pipeline_time_s`).

---

## 3. Unit Tests & Live Verification Results

### Unit Test Execution
```bash
python -m unittest shadow_sandbox/reports/test_reports.py
```
* **Result:** `Ran 3 tests in 0.014s ... OK`

### Full Test Suite (Layers 2, 3, and 4)
```bash
python -m unittest shadow_sandbox/faults/test_faults.py shadow_sandbox/remediation/test_remediation.py shadow_sandbox/reports/test_reports.py
```
* **Result:** `Ran 11 tests in 0.012s ... OK`

---

## 4. Real Execution Outputs

### BLOCKED Case (`case_22_storage_corruption_nuclear.json`)
```bash
python -m shadow_sandbox.reports.report_generator shadow_sandbox/sample_inputs/case_22_storage_corruption_nuclear.json
```
**File Generated:** `shadow_sandbox/reports/case_22_storage_corruption_nuclear_20260825_143040.json`
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

---

### EXECUTED Case (`case_11_pg_connection_exhaustion.json`)
```bash
python -m shadow_sandbox.reports.report_generator shadow_sandbox/sample_inputs/case_11_pg_connection_exhaustion.json
```
**File Generated:** `shadow_sandbox/reports/case_11_pg_connection_exhaustion_20260825_143316.json`
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
    "running": true,
    "paused": false,
    "memory_limit_bytes": 536870912,
    "nano_cpus": 0,
    "cpu_quota": 0,
    "captured_at": "2026-08-25T14:30:58.112233+00:00",
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
    "output": "ALTER SYSTEM",
    "restarted_container": true
  },
  "after_state": {
    "target": "shadow-postgres-db",
    "status": "running",
    "health": "starting",
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
