# Auto-SRE Platform — Ongoing Development Changelog & Work Notes

This document maintains a real-time record of all development changes, architectural decisions, security hardenings, and validation results across the codebase.

---

## 📌 Active Development Snapshot
* **Current Active Branch:** `main` (`volume-2` fully merged at `ee62ac6`)
* **Base Upstream Branch:** `main` / `phase-4`
* **GitLab Remote (`origin`):** `https://gitlab.com/sre-group6103633/sre-project.git`
* **GitHub Remote (`asre`):** `https://github.com/sk101-art/asre.git`
* **Static Acceptance Score:** `18/18 PASS (100%)` via `validate_10.py --static`
* **Unit & Contract Tests:** `29/29 PASS (100%)` via `pytest -v tests/`
* **Code Standards:** Clean via `ruff check .` & `mypy`
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
