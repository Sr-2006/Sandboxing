# Auto-SRE Platform — Development Changelog & Work Notes

This document maintains a factual record of all architectural updates, security hardenings, defect resolutions, and validation results across the codebase.

---

## 📦 Version 2.1.0 — Platform Hardening & Adversarial Audit Remediation

A comprehensive hardening cycle resolved 23 audited defect IDs across the platform's core Python engine, Java 21 microservices, and observability infrastructure:

### 🔒 Security
* **FIX C1**: Closed direct-port authentication bypass on `order-service` and `payment-service` using Spring Security and `InternalAuthFilter` token verification.
  * *Files:* `order-service/pom.xml`, `order-service/src/main/java/com/autosre/orderservice/config/InternalAuthFilter.java`, `order-service/src/main/java/com/autosre/orderservice/config/SecurityConfig.java`, `payment-service/pom.xml`, `payment-service/src/main/java/com/autosre/paymentservice/config/InternalAuthFilter.java`, `payment-service/src/main/java/com/autosre/paymentservice/config/SecurityConfig.java`, `api-gateway/src/main/java/com/ecommerce/gateway/filter/JwtValidationFilter.java`, `docker-compose.yml`.
* **FIX C2**: Bound all exposed container ports to `127.0.0.1` and added `--requirepass` authentication to Redis.
  * *Files:* `docker-compose.yml`, `auth-service/src/main/resources/application.yml`, `.env.example`, `.env`.
* **FIX C6**: Implemented fail-closed chaos validation in startup scripts to abort on placeholder tokens or default configs.
  * *Files:* `run.ps1`, `run.sh`, `.env.example`, `.env`.
* **FIX H2**: Prevented shell command injection in `tc netem` latency and RabbitMQ backlog faults via parameter type/range checks and direct list execution.
  * *Files:* `chaos_orchestrator.py`.
* **FIX H6**: Removed default fallback credentials for Grafana administration in `docker-compose.yml`.
  * *Files:* `docker-compose.yml`.
* **FIX M4**: Removed hardcoded JWT signing fallback secret and enforced runtime secret length validation (>= 32 characters) on startup.
  * *Files:* `auth-service/src/main/resources/application.yml`, `auth-service/src/main/java/com/ecommerce/auth/util/JwtUtil.java`, `auth-service/src/test/java/com/ecommerce/auth/util/JwtUtilTest.java`.
* **FIX M9**: Updated downstream services to read user identity from verified `X-User-Id` gateway headers instead of unauthenticated body payloads.
  * *Files:* `order-service/src/main/java/com/autosre/orderservice/OrderController.java`, `payment-service/src/main/java/com/autosre/paymentservice/PaymentController.java`.

### ⚙️ Reliability
* **FIX C3**: Removed lock file deletion on unlock to prevent race conditions across concurrent processes.
  * *Files:* `utils.py`.
* **FIX C4**: Ensured atomic file writes flush and fsync descriptors prior to replacement.
  * *Files:* `utils.py`.
* **FIX C5**: Replaced stale module-level Drain3 miner with post-reset local instantiation.
  * *Files:* `phase1_processor.py`.
* **FIX H1**: Replaced brittle process name matching with CIM query (`Win32_Process`) and `pkill` in startup scripts.
  * *Files:* `run.ps1`, `run.sh`.
* **FIX H3**: Replaced intrinsic synchronized deadlock monitors with clearable `ReentrantLock` polling and `AtomicBoolean` cancellation tokens.
  * *Files:* `auth-service/src/main/java/com/ecommerce/auth/chaos/ChaosController.java`, `order-service/src/main/java/com/autosre/orderservice/chaos/ChaosController.java`, `payment-service/src/main/java/com/autosre/paymentservice/chaos/ChaosController.java`, `api-gateway/src/main/java/com/ecommerce/gateway/chaos/ChaosController.java`.
* **FIX H7**: Implemented standalone `chaos_watchdog.py` and pre-scenario hooks to reconcile stale chaos injections past their duration window.
  * *Files:* `chaos_watchdog.py`, `chaos_orchestrator.py`, `chaos_scenarios.py`.
* **FIX M1**: Tightened exception start regex token boundaries to avoid over-matching.
  * *Files:* `phase1_processor.py`.
* **FIX M2**: Preserved arrival order when stitching multi-line stack traces and ensured buffer continuation under load.
  * *Files:* `phase1_processor.py`.
* **FIX M8**: Added explicit `try/finally` resource cleanup for probe sockets and RabbitMQ broker connections.
  * *Files:* `chaos_orchestrator.py`.
* **FIX M10**: Converted file paths across all daemons and tools to use absolute project paths via `project_path()`.
  * *Files:* `utils.py`, `continuous_telemetry.py`, `frontend_data_sync.py`, `monitor_ram.py`, `phase1_processor.py`, `package_ml_dataset.py`, `chaos_scenarios.py`, `chaos_watchdog.py`.

### 📊 Observability
* **FIX H4**: Corrected health scoring to assign 0.0 to exited/dead containers and dynamically parsed service dependencies from compose topology.
  * *Files:* `frontend_data_sync.py`.
* **FIX H5**: Enabled Docker nanosecond timestamp ingestion to preserve error storms, and seeded existing event hashes on startup.
  * *Files:* `continuous_telemetry.py`.
* **FIX M3**: Unified incident-to-chaos correlation to use a shared time-window function across processors.
  * *Files:* `utils.py`, `phase1_processor.py`, `package_ml_dataset.py`.
* **FIX M6**: Removed redundant debug exporter from OpenTelemetry Collector configuration.
  * *Files:* `otel-collector-config.yaml`.
* **FIX M7**: Reduced log event payload maximum length to 2,000 characters and max queue capacity to 2,000 entries.
  * *Files:* `continuous_telemetry.py`.

### 🧪 Testing & Validation
* **Automated Regression Test Suite**: Implemented 8 new test modules covering concurrency races, fsync durability, Drain3 resetting, stack trace chronology, chaos correlation, watchdog recovery, dead container scoring, and command injection guards (`61/61` pytest tests passing).
  * *Files:* `tests/test_lock_race.py`, `tests/test_atomic_durability.py`, `tests/test_drain_reset_effective.py`, `tests/test_stitch_chronology.py`, `tests/test_chaos_correlation_shared.py`, `tests/test_chaos_watchdog.py`, `tests/test_health_score.py`, `tests/test_tc_injection_guard.py`, `tests/test_telemetry_dedup.py`.
* **Acceptance Gates**: Expanded static gate validator to 28 static gates and 37 total acceptance gates (`validate_10.py`).
  * *Files:* `validate_10.py`.

---

## 🛡️ Adversarial Audit Hardening — Phase 1 Fixes (Concurrency, Durability & Drain3 Reset)

### 1. FIX C3 — Lock File Race Elimination in `utils.py`
* **Defect:** `file_lock_context` unlinked `.lock` files inside `finally`, creating an inode race condition where waiting processes lose mutual exclusion.
* **Fix:** Completely removed `os.remove(lock_file)`. Lock files intentionally persist while unlocks (`msvcrt.LK_UNLCK` / `fcntl.LOCK_UN`) and file handle closure remain intact.

### 2. FIX C4 — Durable Atomic Writes with `fsync` in `utils.py`
* **Defect:** `atomic_write_json` lacked explicit `flush()` and `fsync()`.
* **Fix:** Enforced `f.flush()` and `os.fsync(f.fileno())` prior to `os.replace()`, plus best-effort parent directory `fsync` on POSIX systems.

### 3. FIX C5 — Elimination of Stale Module-Level Drain3 Miner in `phase1_processor.py`
* **Defect:** `TemplateMiner` was instantiated at import time; version reset deleted state files on disk but the in-memory miner restored old clusters upon saving.
* **Fix:** Removed module-level `miner` instantiation. `process_phase1_incidents()` now executes `check_drain_version_and_reset_if_needed(reset_drain)` first, then initializes and passes a fresh local `miner` instance into the processing loop.

### 4. FIX M1 & FIX M2 — Stricter Exception Matching & Chronological Stitched Ordering in `phase1_processor.py`
* **Defect:** `EXCEPTION_START_RE` was overly eager, disabled buffering on >50 blocks, and appended finished buffers to the end of the log list rather than maintaining first-line arrival order.
* **Fix:**
  * Updated to strict token-boundary regex: `r'^(?:\S+\s+){0,6}\S*(?:Exception|Error|Throwable)\b|^Caused by:|^[A-Za-z_$][\w.$]*(?:Exception|Error)\b'`.
  * Preserved chronological order: buffer target dictionary is appended to `stitched_events` at first-line encounter and updated in-place on continuation lines.
  * Ensured buffering is never disabled under load by flushing previous buffers and immediately opening fresh ones.

### 5. FIX M3 — Unified Window Chaos Correlation in `utils.py`
* **Defect:** `phase1_processor.py` and `package_ml_dataset.py` computed chaos correlation independently with differing timestamp windows.
* **Fix:**
  * Created shared `correlate_chaos_event(cluster_start_dt, cluster_end_dt, container_name, chaos_history_data)` in `utils.py`.
  * `phase1_processor.py` emits `earliest_ts` and `latest_ts` ISO timestamps on each incident object.
  * `package_ml_dataset.py` consumes `earliest_ts`/`latest_ts` and delegates to `correlate_chaos_event()`.

---

## 🛡️ Adversarial Audit Hardening — Phase 2 Fixes (Auth Bypass, Infra Exposure & Chaos Defaults)

### 1. FIX C1 & FIX M9 — Direct-Port Auth Bypass Closed & Header Identity Enforcement
* **Defect:** `order-service` and `payment-service` lacked Spring Security and trusted client-provided user IDs directly from body payloads; host-published ports allowed unauthenticated API access.
* **Fix:**
  * Added `spring-boot-starter-security` to both `pom.xml` files.
  * Created `InternalAuthFilter` and `SecurityConfig` in both services enforcing `X-Internal-Service-Token` and `X-User-Id` on `/api/**` routes while permitting `/actuator/health`, `/actuator/info`, `/actuator/prometheus`, `/chaos/**`, and `/error`.
  * Configured `api-gateway` `JwtValidationFilter` to forward `X-Internal-Service-Token` to downstream services after authenticating the caller.
  * Added unit test suites `InternalAuthFilterTest.java` to both services verifying 401 on missing/invalid tokens or missing user identity.

### 2. FIX C2 — Redis Password Authentication & Loopback Port Isolation
* **Defect:** Redis ran without authentication, and all service/infrastructure ports were exposed to the external network interface `0.0.0.0`.
* **Fix:**
  * Configured `redis` with `--requirepass "${REDIS_PASSWORD}"` in `docker-compose.yml` and wired `SPRING_REDIS_PASSWORD` in `auth-service`.
  * Bound all published ports in `docker-compose.yml` strictly to loopback (`127.0.0.1:N:N`).
  * Updated `.env.example` with `REDIS_PASSWORD` and `INTERNAL_SERVICE_TOKEN`.

### 3. FIX C6 — Safe Chaos Fail-Closed Defaults
* **Defect:** `run.ps1` unconditionally forced `ENABLE_CHAOS=true` and ran with default `dev-chaos-token`.
* **Fix:**
  * Removed unconditional override in `run.ps1`.
  * Both `run.ps1` and `run.sh` now exit immediately with an error if `ENABLE_CHAOS=true` and `CHAOS_SECRET` is set to default/placeholder values (`dev-chaos-token` or `CHANGE_ME_chaos_secret`).
  * `.env.example` sets `ENABLE_CHAOS=false` and `CHAOS_SECRET=CHANGE_ME_chaos_secret`.

### 4. FIX H6 — Grafana Strict Environment Credentials
* **Defect:** `docker-compose.yml` had `:-admin` fallback credentials for Grafana admin login.
* **Fix:** Replaced with required variables `GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:?...}` and `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?...}`.

### 5. FIX M4 — JWT Secret Validation & No Hardcoded Fallbacks
* **Defect:** `auth-service` contained hardcoded 64-character JWT secret fallback in `@Value`.
* **Fix:** Removed hardcoded defaults (`@Value("${jwt.secret:}")`), wired `jwt.secret` via `application.yml`, and added `@PostConstruct` validation in `JwtUtil` that fails fast if `jwtSecret` is blank or `< 32` characters.

### 6. FIX M6 — Removed Debug Exporter from OTel Collector
* **Defect:** `otel-collector-config.yaml` contained a `debug` exporter in traces, metrics, and logs pipelines, spamming logs in production.
* **Fix:** Removed `debug` exporter definition and pipeline attachments.

---

## 🛡️ Adversarial Audit Hardening — Phase 3 Fixes (Lifecycle, Injection, Deadlock & Recovery Watchdog)

### 1. FIX H1 — Reliable CIM Daemon Termination in `run.ps1` & `pkill` in `run.sh`
* **Defect:** `Get-Process` lacked `CommandLine` property, causing stale background daemons to persist across runs and create uncoordinated file races.
* **Fix:**
  * Replaced with `Get-CimInstance Win32_Process` query in [`run.ps1`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.ps1) matching `continuous_telemetry.py|frontend_data_sync.py|monitor_ram.py`.
  * Added `pkill -f 'continuous_telemetry.py|frontend_data_sync.py|monitor_ram.py' 2>/dev/null || true` to [`run.sh`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.sh).

### 2. FIX H2 — Command Injection Closed & Clamped CLI Parameters in `chaos_orchestrator.py`
* **Defect:** `network_latency` interpolated unvalidated `latency_ms` into shell strings executed as root in containers.
* **Fix:**
  * Validated and clamped `latency_ms` as `int` within `1..10000`.
  * Converted `c.exec_run` to list-form execution: `["tc", "qdisc", "add", "dev", "eth0", "root", "netem", "delay", f"{latency_ms}ms"]` (and list-form for recovery `["tc", "qdisc", "del", "dev", "eth0", "root"]`).
  * Validated and clamped `rabbitmq_backlog` `messages` as `int` within `1..100000`.

### 3. FIX H3 — Clearable Deadlock Simulation across all 4 Microservices
* **Defect:** `Thread.interrupt()` was incapable of interrupting threads blocked on synchronized monitors, causing thread leaks and false clearing status.
* **Fix:**
  * Replaced synchronized blocks with `ReentrantLock` instances and `AtomicBoolean deadlockCancelled = new AtomicBoolean(false)`.
  * Implemented responsive polling `tryLock(100, TimeUnit.MILLISECONDS)` loops in `auth-service`, `order-service`, `payment-service`, and `api-gateway` [`ChaosController.java`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/auth-service/src/main/java/com/ecommerce/auth/chaos/ChaosController.java).
  * `/deadlock/clear` signals cancellation, interrupts threads, joins with 2000ms timeout, and reports actual surviving alive threads (`deadlock_cleared` vs `deadlock_clear_partial`).
  * Reused clean cancellation and join path in `@PreDestroy cleanup()`.

### 4. FIX H7 — Autonomous Chaos Recovery Watchdog & Graceful Signal Handling
* **Defect:** Abrupt exit or crash during chaos execution left orphan faults in containers and dangling unrecovered events in `chaos_history.json`.
* **Fix:**
  * Implemented [`chaos_watchdog.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_watchdog.py) with `reconcile_stale_chaos_events()` reconciling unrecovered faults older than `start_ts + duration_s + 600s grace`.
  * Added `--reconcile` CLI flag to [`chaos_orchestrator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_orchestrator.py).
  * Added SIGINT/SIGTERM graceful shutdown handlers and pre-scenario watchdog reconciliation in [`chaos_scenarios.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_scenarios.py).
  * Created unit test suite [`tests/test_chaos_watchdog.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/tests/test_chaos_watchdog.py) verifying stale recovery, recent event ignoring, and resilient failure handling.

### 5. FIX M8 — Sockets & Broker Connections Leaks Closed in `chaos_orchestrator.py`
* **Defect:** Probe socket in `get_service_url()` and RabbitMQ connection in `rabbitmq_backlog` leaked descriptors on error paths.
* **Fix:** Wrapped sockets and broker connections in `try/finally` blocks with dedicated cleanup logic.

### 6. FIX M10 — Directory-Agnostic File Resolution via `project_path`
* **Defect:** CWD-relative file paths broke daemons and CLI tools executed from subdirectories or external working dirs.
* **Fix:**
  * Introduced `PROJECT_ROOT` and `project_path(*parts)` helper in [`utils.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/utils.py).
  * Converted all `frontend_data/...` and `docker-compose.yml` paths to `project_path` in `continuous_telemetry.py`, `frontend_data_sync.py`, `monitor_ram.py`, `phase1_processor.py`, `package_ml_dataset.py`, `chaos_scenarios.py`, and `chaos_watchdog.py`.

---

## 🛡️ Adversarial Audit Hardening — Phase 4 Fixes (Health Model, Log Ingestion, Dedup & Truncation)

### 1. FIX H4 — Realistic Health Model & Single-Source Dynamic Topology in `frontend_data_sync.py`
* **Defect:** Dead/exited containers received a 90/100 score (labeled "healthy"), and dependencies were statically hardcoded.
* **Fix:**
  * `compute_container_health_score()` immediately returns `0.0` for containers with status `exited` or `dead`.
  * Applied `-50.0` penalty for `health == "unhealthy"`, causing degraded health score.
  * Deleted hardcoded `SERVICE_DEPENDENCIES` dict and wired dynamic, cached `parse_docker_compose_topology()` single-source dependency resolution.
  * Added unit test suite [`tests/test_health_score.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/tests/test_health_score.py) proving dead containers return `0.0` and report `unhealthy` dependency status.

### 2. FIX H5 & FIX M7 — Docker-Timestamp Log Ingestion, Storm Dedup & Reduced Write Amplification
* **Defect:** Lines without timestamps were truncated to the same second, suppressing high-volume error storms into a single event; restarts re-ingested duplicate logs; tail saturation was silent; events exceeded 8000 chars.
* **Fix:**
  * Ingested logs with `timestamps=True` from Docker daemon; parsed nanosecond RFC3339 timestamps in `parse_docker_log_line()`.
  * Computed SHA256 log hash incorporating nanosecond timestamps so identical error storm lines are preserved.
  * Added `seed_seen_log_hashes_from_file()` to seed up to 500 existing event hashes on daemon startup, preventing duplicate ingestion on restart.
  * Added saturation warning log when `len(raw_logs) == 100`.
  * Capped event content length at 2000 chars (down from 8000) and `MAX_EVENTS` at 2000 (down from 5000) in [`continuous_telemetry.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/continuous_telemetry.py).
  * Added unit test suite [`tests/test_telemetry_dedup.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/tests/test_telemetry_dedup.py).

---

## 🛡️ Adversarial Audit Hardening — Phase 5 Fixes (Automated Regression Tests & Static Gates)

### 1. New Python Regression Test Suites (`tests/`)
* **`tests/test_lock_race.py`**: Spawned 2 concurrent `multiprocessing.Process` workers recording 100 events each against a temporary chaos history file; verified final history has exactly 200 items.
* **`tests/test_atomic_durability.py`**: Verified call ordering ensuring `f.flush()` and `os.fsync()` occur strictly before `os.replace()`.
* **`tests/test_drain_reset_effective.py`**: Verified obsolete Drain3 state files are unlinked, version metadata headers rewritten, and local `TemplateMiner` initialized strictly after version check.
* **`tests/test_stitch_chronology.py`**: Verified multi-line exception stack trace blocks maintain their initial chronological arrival order rather than being appended to the tail.
* **`tests/test_chaos_correlation_shared.py`**: Validated `correlate_chaos_event()` across in-window match (+/- 300s), out-of-window miss, service mismatch, and wildcard targets.
* **`tests/test_chaos_watchdog.py`**: Verified watchdog reconciliation for stale injected events, active grace periods, and failed recoveries.
* **`tests/test_health_score.py`**: Verified exited/dead containers score `0.0` and map to `unhealthy` dependency status.
* **`tests/test_tc_injection_guard.py`**: Verified input validation bounds on `tc netem` latency (1..10000ms) and RabbitMQ backlog queue size (1..100000), preventing shell command injection.

### 2. Extended Static & Acceptance Gates in `validate_10.py` (28 Static Gates Total)
* **`compose_no_fallback_creds`**: Fails if `docker-compose.yml` matches `r'\$\{[A-Z_]*(PASSWORD|PASS|SECRET|USER)[A-Z_]*:-'`.
* **`compose_ports_loopback`**: Asserts every published port is bound to `127.0.0.1`.
* **`redis_requirepass`**: Asserts redis service block contains `--requirepass`.
* **`downstream_security_deps`**: Asserts `order-service` and `payment-service` pom.xml include `spring-boot-starter-security`.
* **`no_hardcoded_jwt_secret`**: Asserts no Java source files contain the secret literal `"9a4f2c8d"`.
* **`atomic_write_has_fsync`**: Asserts `utils.py` calls `os.fsync()`.
* **`lock_file_never_deleted`**: Asserts `file_lock_context` in `utils.py` does not contain `os.remove`.
* **`chaos_latency_validated`**: Asserts `chaos_orchestrator.py` clamps latency to `1 <= latency_ms <= 10000`.
* **`deadlock_clearable`**: Asserts all 4 `ChaosController.java` classes implement `AtomicBoolean` and `tryLock`.
* **`run_scripts_fail_closed`**: Asserts `run.ps1` and `run.sh` fail-closed when placeholder chaos tokens are used.




* **End-to-End CI:** 🟢 **FULLY GREEN** — pipeline [#2764157052](https://gitlab.com/sre-group6103633/sre-project/-/pipelines/2764157052) (commit `bd852dd`, branch `main`): all 8 jobs passed including the **integration stage** (full Docker Compose stack, load generation, chaos smoke, Phase 1 processing, ML dataset packaging).

---

## 🚀 Volume 2: 10 Architectural & Security Gaps Resolved

### 1. Unified Chaos History Contract (GAP 1)
* **Goal:** Eliminate split schema and uncoordinated concurrent writes between `chaos_orchestrator.py` and `chaos_scenarios.py`.
* **Changes:**
  * Defined canonical `CHAOS_EVENT_SCHEMA` in [`utils.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/utils.py):
    ```json
    {
      "event_id": "str (uuid)",
      "scenario_id": "str (optional)",
      "fault_name": "str",
      "target": "str",
      "start_ts": "str (ISO 8601 UTC)",
      "end_ts": "str (ISO 8601 UTC)",
      "params": "dict",
      "duration_s": "float",
      "status": "str (injected|recovered|failed)"
    }
    ```
  * Added `record_chaos_event()` in [`utils.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/utils.py) wrapped in `file_lock_context` and `atomic_write_json`.
  * Migrated [`chaos_orchestrator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_orchestrator.py) and [`chaos_scenarios.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_scenarios.py) to write through `record_chaos_event()`.
  * Updated dataset builder [`package_ml_dataset.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/package_ml_dataset.py) and validator [`validate_10.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/validate_10.py) to parse the unified format.
  * Added test coverage: [`test_chaos_history_contract.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/tests/test_chaos_history_contract.py).

### 2. Chaos Endpoints Security & Isolation (GAP 2)
* **Goal:** Prevent public exposure of chaos injection endpoints via API Gateway and mandate token validation.
* **Changes:**
  * Added `.pathMatchers("/chaos/**").denyAll()` in [`GatewaySecurityConfig.java`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/api-gateway/src/main/java/com/ecommerce/gateway/config/GatewaySecurityConfig.java).
  * Updated `ChaosController.java` in all 4 microservices (`api-gateway`, `auth-service`, `order-service`, `payment-service`) with:
    * `@ConditionalOnProperty(name = "chaos.enabled", havingValue = "true", matchIfMissing = false)`
    * `X-Chaos-Token` header check against `chaos.token` (fails with `403 Forbidden` if missing/invalid).
    * **Fail-closed validation:** if `chaos.token` is unconfigured/empty, all chaos endpoints return `403 Forbidden` (no open-by-default behavior).
  * Updated `application.yml` in all 4 services with `chaos.enabled: ${CHAOS_ENABLED:false}` and `chaos.token: ${CHAOS_SECRET:}` (empty default — token must be supplied via environment; no committed secret).

### 3. Docker Compose & Environment Hardening (GAP 8 & GAP 3)
* **Goal:** Remove default hardcoded secrets and disable chaos mode by default.
* **Changes:**
  * Updated [`docker-compose.yml`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/docker-compose.yml):
    * `CHAOS_ENABLED: "${ENABLE_CHAOS:-false}"`
    * `CHAOS_SECRET: "${CHAOS_SECRET:?CHAOS_SECRET must be set in .env}"` (required-variable pattern — stack refuses to start without an explicit secret)
    * `JWT_SECRET: "${JWT_SECRET:?JWT_SECRET must be set in .env}"`
  * Added `CHAOS_SECRET` to committed [`.env.example`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/.env.example).
  * In [`chaos_orchestrator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_orchestrator.py), replaced hardcoded credentials with `os.environ.get("RABBITMQ_DEFAULT_USER", "guest")` and `os.environ.get("RABBITMQ_DEFAULT_PASS", "guest")`.

### 4. Dataset Lineage & Versioning (GAP 7)
* **Goal:** Provide provenance and reproducibility for ML training and LLM RCA dataset.
* **Changes:**
  * Added `DatasetMeta` model to [`phase1_schema.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/phase1_schema.py) (`dataset_version`, `processor_version`, `git_sha`, `source_files`, `schema_version`).
  * Updated [`package_ml_dataset.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/package_ml_dataset.py) to automatically record dataset metadata on export.

### 5. Prometheus & Grafana Provisioning (GAP 4)
* **Goal:** Auto-provision Prometheus datasource and dashboards upon container launch.
* **Changes:**
  * Created [`grafana/provisioning/datasources/prometheus.yml`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/grafana/provisioning/datasources/prometheus.yml).
  * Created [`grafana/provisioning/dashboards/default.yml`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/grafana/provisioning/dashboards/default.yml).
  * Created [`grafana/provisioning/dashboards/system-overview.json`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/grafana/provisioning/dashboards/system-overview.json) (HTTP 5xx rate, JVM Heap memory, p95 latency, live thread count).

### 6. Acceptance Gates & Validator Consolidation (GAP 6)
* **Goal:** Eliminate duplicate validators.
* **Changes:**
  * Standardized on [`validate_10.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/validate_10.py) covering 18 static gates.
  * Created [`validate.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/validate.py) as a lightweight compatibility forwarder.

### 7. 13-Fault Catalog & Honest SQL Lock Audit Trail (GAP 5)
* **Goal:** Ensure all 13 chaos faults are supported and accurately logged.
* **Changes:**
  * Added `network_latency` to `FAULTS_CATALOG` in [`chaos_scenarios.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_scenarios.py) and [`chaos_orchestrator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_orchestrator.py).
  * For `http_sql_lock`, explicitly marked recovery status as `recovered` with `recovery_type: "passive"`.

### 8. Load Generator Fallback Path & Security (GAP 9)
* **Goal:** Fix fallback routes and attach security credentials to chaos injection triggers.
* **Changes:**
  * Explicitly configured `gateway_path` and `direct_path` for all endpoints in [`load_generator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/load_generator.py).
  * Added `X-Chaos-Token` header for simulated chaos triggers.

### 9. Logging Standardization & Hygiene (GAP 10)
* **Goal:** Structured JSON logging across all backend Python scripts.
* **Changes:**
  * Added `get_logger(name)` in [`utils.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/utils.py).
  * Migrated [`chaos_orchestrator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_orchestrator.py), [`chaos_scenarios.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/chaos_scenarios.py), [`load_generator.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/load_generator.py), [`monitor_ram.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/monitor_ram.py), and [`package_ml_dataset.py`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/package_ml_dataset.py).
  * Updated `.gitignore` and `validate_10.py` to prevent tracking `.log` files.

### 10. Security Tests, Hardware Guardrails & Handoff Documentation
* **Goal:** Verify Chaos token security via automated tests, prevent out-of-memory lockups on 16GB host machines, enable kernel netem capabilities, and finalize Phase 2 contracts.
* **Changes:**
  * Added `ChaosControllerSecurityTest.java` across all 4 microservices (`auth-service`, `api-gateway`, `order-service`, `payment-service`) testing missing token, invalid token, and valid token access.
  * Added RAM pre-flight guardrail in [`run.ps1`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.ps1) and [`run.sh`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.sh) (warning when available memory < 6GB).
  * Added security warning in [`run.ps1`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.ps1) and [`run.sh`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/run.sh) when default `CHAOS_SECRET` is used with `ENABLE_CHAOS=true`.
  * Added `cap_add: - NET_ADMIN` to all 4 microservices in [`docker-compose.yml`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/docker-compose.yml) to enable the 13th chaos fault (`network_latency` via `tc netem`).
  * Updated [`phase2expectations.txt`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/phase2expectations.txt) and [`ML_HANDOVER_AND_ENGINE_GUIDE.md`](file:///c:/Users/sujay/Downloads/complex/auto-sre-platform/ML_HANDOVER_AND_ENGINE_GUIDE.md) documenting `DatasetMeta`, lineage fields for ChromaDB fingerprinting, and unified chaos history format.

---

## 🧪 Verification Matrix

| Area | Component | Verification Output | Status |
| :--- | :--- | :--- | :---: |
| **Java Unit Tests** | `auth-service` | `AuthControllerTest`, `JwtUtilTest`, `GlobalExceptionHandlerTest`, `LogContractTest`, `ChaosControllerSecurityTest` | 🟢 6 Test Suites |
| **Java Unit Tests** | `api-gateway` | `JwtValidationFilterTest`, `FailureInjectionFilterTest`, `TraceMDCWebFilterTest`, `LogContractTest`, `ChaosControllerSecurityTest` | 🟢 5 Test Suites |
| **Java Unit Tests** | `order-service` | `OrderControllerTest`, `TraceMDCFilterTest`, `LogContractTest`, `ChaosControllerSecurityTest` | 🟢 5 Test Suites |
| **Java Unit Tests** | `payment-service` | `PaymentControllerTest`, `TraceMDCFilterTest`, `LogContractTest`, `ChaosControllerSecurityTest` | 🟢 5 Test Suites |
| **Python Tests** | `tests/` | 29 Pytest suites covering atomic writes, schema contracts, masking, scoring, filtering, migration | 🟢 29/29 PASS |
| **Static Gates** | `validate_10.py` | 18 Static Acceptance Gates | 🟢 18/18 PASS |
| **Linter & Typing** | `ruff` + `mypy` | Strict check across Python codebase with `pyproject.toml` | 🟢 100% Clean |

> **Note:** Java test suites are compile-verified locally (IDE language server, zero errors). Execution verification runs via GitLab CI (`mvn test`, `.gitlab-ci.yml` stage `test-java`) since no local Maven install exists on this host.
>
> ✅ **CI-VERIFIED:** GitLab pipeline [#2764112083](https://gitlab.com/sre-group6103633/sre-project/-/pipelines/2764112083) (commit `b8a71a61`, branch `volume-2`) passed all 7 jobs / 72 tests: `lint`, `test-python`, `test-java` (all 4 services), and `validate`. All Java test suites are now execution-verified in CI.
>
> 🏆 **END-TO-END VERIFIED (10/10):** GitLab pipeline [#2764157052](https://gitlab.com/sre-group6103633/sre-project/-/pipelines/2764157052) (commit `bd852dd`, branch `main`) — **all 8 jobs green**, including the `integration` stage for the first time: Docker Compose stack boots healthy (postgres, rabbitmq, redis, 4 Java services, otel-collector, prometheus, loki, grafana), 60s load generation, chaos smoke injection, Phase 1 log processing, and ML dataset packaging all succeed inside CI.

---

## 📝 Ongoing Developer Notes & Next Actions
1. **Repository Sync:**
   - `volume-2` merged into `main` (merge commit `ee62ac6`); `main` is now the active branch.
   - **Pipeline #2764157052 fully green on `main`** (8 jobs incl. integration + validate).
   - Available to sync to GitHub `asre/main` when ready.
   - **CI fix commits (volume-2 era):**
     - `6975b7e` — corrected invalid type-stub pins in `requirements.txt` (`types-requests`, `types-PyYAML`) that broke the `lint` stage dependency install.
     - `8330b4a` — `GlobalExceptionHandler` now preserves `ResponseStatusException` status (auth-service chaos 403s were being swallowed as 500 by the generic `Exception` handler; fixed in auth/order/payment services).
     - `b8a71a6` — `validate_10.py` handles missing `git` binary in `python:3.11-slim` CI image (archive checkout) with a disk-check fallback.
   - **Integration-stage fix commits (on `main`):**
     - `4baa4a6` — integration job: added `gcc musl-dev python3-dev linux-headers make` to `apk add` so `psutil` builds from source on Alpine (Alpine Python reports `linux_x86_64`, so pip cannot use musllinux wheels).
     - `9b02ec7` — `order-service`/`payment-service` Dockerfiles bumped `maven:3.9-eclipse-temurin-17` → `21` and `eclipse-temurin:17-jre` → `21-jre-alpine` (poms target Java 21; builds failed with "release version 21 not supported").
     - `2c5e174` — removed the `otel-collector` compose healthcheck: the `otel/opentelemetry-collector-contrib` image is scratch-based (no shell/`wget`), so a `CMD wget` healthcheck can never pass and `docker compose up --wait` aborted.
     - `bd852dd` — `validate_10.py` `no_generated_artifacts_tracked` fallback is now gitignore-aware: the validate job reuses the integration build dir, so gitignored `frontend_data/*.json` exist on disk but are untracked.
2. **Next Steps / Roadmap:**
   - Multi-Agent RCA Engine implementation.
   - ChromaDB vector collection indexing using `git_sha` and `(target_service, log_cluster_template)`.
   - UI / Live Dashboard integrations.
