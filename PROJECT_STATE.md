# Auto-SRE Platform: Project State & Architecture Registry

## Metadata & Status Stamp

| Attribute | Details |
| :--- | :--- |
| **Project Name** | Smart Horizon Hackathon - V2 Microservices & Auto-SRE Platform |
| **Last Modified Date** | August 17, 2026 |
| **Current State** | Hardened platform with loopback-only ports, Redis password authentication, downstream internal-token authentication, fail-closed chaos configuration, durable atomic writes with `fsync`, persistent file locks, versioned Drain3 reset, watchdog-based chaos recovery, 61 unit/contract tests, and 28 static gates (37 total acceptance gates). |
| **Repository State** | Dockerized microservices stack with end-to-end distributed telemetry and observability, OpenTelemetry MDC trace propagation, Logstash JSON logging, Grafana Loki log pipeline, Prometheus metrics (provisioned datasource + system-overview dashboard), Jaeger traces, 13-type chaos orchestration catalog (unified `CHAOS_EVENT_SCHEMA` ground truth), versioned Drain3 clustering (v2), dynamic priority score engine, and validated Pydantic v2 Unified Master Dataset with `DatasetMeta` lineage. |

---

## 1. Current System Security & Operational Architecture

The Auto-SRE platform is an event-driven, containerized microservices platform built on Java 21 (Spring Boot 3.2.x) and Python 3.11, hardened for security, concurrency durability, and automated incident clustering.

### A. Network & Authentication Posture
* **Loopback Port Isolation:** All published container ports in `docker-compose.yml` (database, broker, cache, microservices, observability UIs) are bound strictly to `127.0.0.1` to prevent unauthenticated network exposure.
* **Downstream Internal Token Auth:** `order-service` and `payment-service` enforce Spring Security filters (`InternalAuthFilter`) verifying the `X-Internal-Service-Token` header for all `/api/**` traffic, with caller identity extracted from `X-User-Id` headers injected by `api-gateway`.
* **Redis Authentication:** Redis runs with `--requirepass` authentication configured via `REDIS_PASSWORD` from `.env`.
* **Fail-Closed Chaos Protection:** Automated startup scripts (`run.ps1`, `run.sh`) fail-fast if placeholder tokens (`dev-chaos-token`, `CHANGE_ME_chaos_secret`) are present when chaos injection is enabled, while `ENABLE_CHAOS` defaults to `false`.

### B. Core Concurrency & Durability Mechanisms
* **Persistent File Locks:** `utils.py` `file_lock_context` uses file-descriptor locking (`msvcrt` on Windows, `fcntl` on POSIX) without unlinking lock files on release, eliminating inode race conditions between concurrent worker processes.
* **Durable Atomic Writes:** `atomic_write_json` flushes memory buffers and executes `os.fsync()` before file replacement (`os.replace`), with best-effort directory fsync on POSIX systems.
* **Drain3 Reset & Dynamic Instantiation:** `phase1_processor.py` manages `drain3_version.meta` to invalidate and purge outdated cluster state trees upon version increments, creating fresh local `TemplateMiner` instances post-reset.
* **Watchdog-Based Chaos Recovery:** `chaos_watchdog.py` periodically reconciles active chaos state, automatically recovering unrecovered mutations whose run duration exceeds the fault window plus a 600-second grace buffer.

---

## 2. Microservices & Component Inventory

* **Edge / Entry (`api-gateway`):**
  * **Technology:** Spring Cloud Gateway (WebFlux / Netty, Java 21).
  * **Port:** `127.0.0.1:8080`.
  * **Responsibilities:** JWT token validation, user authentication, downstream routing, `X-Internal-Service-Token` and `X-User-Id` header injection, and edge chaos simulation (`FailureInjectionFilter.java`).
  * **Tracing & MDC:** Standardized via `TraceMDCWebFilter.java` and `GlobalWebExceptionHandler.java`.
* **Auth Service (`auth-service`):**
  * **Technology:** Spring Boot 3.2.5 (Servlet / Tomcat, Java 21).
  * **Port:** `127.0.0.1:8081`.
  * **Responsibilities:** User registration, authentication, BCrypt password hashing, HMAC-SHA256 JWT minting/validation with minimum 32-character secret enforcement, Redis session caching, and PostgreSQL persistence.
* **Order Service (`order-service`):**
  * **Technology:** Spring Boot 3.2.3 (Servlet / Tomcat, Java 21).
  * **Port:** `127.0.0.1:8082`.
  * **Responsibilities:** Order lifecycle management, state transitions, RabbitMQ asynchronous event publishing, `InternalAuthFilter` authentication, and PostgreSQL persistence.
* **Payment Service (`payment-service`):**
  * **Technology:** Spring Boot 3.2.3 (Servlet / Tomcat, Java 21).
  * **Port:** `127.0.0.1:8083`.
  * **Responsibilities:** Payment processing, transaction ledger management, `InternalAuthFilter` authentication, and PostgreSQL persistence.
* **Middleware & Data Stores:**
  * **PostgreSQL 16:** Database container with isolated service schemas (`postgres`, `auth_db`, `order_db`, `payment_db`), versioned via Flyway migrations.
  * **Redis 7 (Alpine):** Password-authenticated cache (`127.0.0.1:6379`).
  * **RabbitMQ 3 (Management Alpine):** Asynchronous message broker (`127.0.0.1:5672`, UI `127.0.0.1:15672`).
* **Observability Infrastructure:**
  * **OpenTelemetry Collector (`otel-collector`):** Ingests OTLP traces (`4317`/`4318`), routing traces to Jaeger and logs to Loki.
  * **Grafana Loki:** High-performance log aggregation engine (`127.0.0.1:3100`).
  * **Prometheus:** Metrics time-series scraper (`127.0.0.1:9090`).
  * **Jaeger:** Distributed tracing visualization engine (`127.0.0.1:16686`).
  * **Grafana:** Centralized dashboard UI with provisioned Prometheus datasource and system overview dashboard (`127.0.0.1:3000`).

---

## 3. Telemetry & Dataset Layer (`frontend_data/`)

| File | Purpose |
| :--- | :--- |
| `raw_telemetry.json` | Container metrics, CPU/memory stats, network rates, exit codes, and anomaly scores. |
| `status.json` | Real-time system health score, active warnings, and dynamic compose dependency connectivity states. |
| `time_series.json` | Rolling historical window of CPU and memory utilization per container. |
| `events_and_incidents.json` | Normalized log event stream with timestamps, levels, container names, and correlated trace/span IDs. |
| `processed_incidents.json` | Clustered incident templates with priority scores, log samples, metrics snapshots, and chaos metadata. |
| `unified_master_dataset.json`| **Master ML Deliverable:** The fully validated Pydantic dataset feeding vectorization and multi-agent RCA. |
| `drain3_state.bin` | Persisted Drain3 clustering state tree. |
| `drain3_version.meta` | Version migration header file for automatic cache invalidation. |
| `chaos_history.json` | Audit log conforming to canonical `CHAOS_EVENT_SCHEMA` tracking all fault injections and recoveries. |
| `analytics.json` | Historical health scores and degradation event records. |

---

## 4. Test Suite & Validation Gates Inventory

### A. Python Regression Test Suites (`tests/` — 61 Tests Total)
* `tests/test_atomic_durability.py`: Verifies `flush()` and `os.fsync()` execution before `os.replace()`.
* `tests/test_atomic_writes.py`: Validates atomic operations, persistent lock retention, and shared correlation.
* `tests/test_chaos_correlation_shared.py`: Unit-tests `correlate_chaos_event()` across window, target, and wildcard scenarios.
* `tests/test_chaos_history_contract.py`: Validates `CHAOS_EVENT_SCHEMA` structure, concurrency, and legacy migration.
* `tests/test_chaos_watchdog.py`: Tests watchdog reconciliation for stale injected events and recovery error handling.
* `tests/test_drain_reset_effective.py`: Verifies Drain3 version migration, state unlinking, and local miner instantiation.
* `tests/test_health_score.py`: Verifies dead container zero-scoring and dynamic topology dependency derivation.
* `tests/test_lock_race.py`: Multiprocessing concurrency race validation ensuring exact event counts across workers.
* `tests/test_masking.py`: Stack trace masking and class name preservation.
* `tests/test_noise_filter.py`, `test_rabbitmq_noise_filter.py`, `test_redis_noise_filter.py`: Lifecycle noise suppression.
* `tests/test_priority_score.py`: Multi-factor incident priority score calculations.
* `tests/test_schema.py`, `test_schema_contract.py`: Pydantic v2 data contract validation against frozen fixtures.
* `tests/test_severity_bucket.py`: Incident severity classification thresholds.
* `tests/test_stack_trace_stitching.py`, `test_stitch_chronology.py`: Multi-line exception stitching and arrival chronology preservation.
* `tests/test_tc_injection_guard.py`: Input validation bounds preventing command injection in traffic control faults.
* `tests/test_telemetry_dedup.py`: Docker RFC3339 timestamp parsing, nanosecond dedup preservation, and hash seeding.
* `tests/test_timestamp_parsing.py`: Resilient ISO-8601 parsing across pathological timestamp formats.
* `tests/test_topology_single_source.py`: Verifies single-source topology extraction from `docker-compose.yml`.
* `tests/test_trace_extraction.py`: W3C header, JSON key, Logback pattern, and OTel key-value trace extraction.

### B. Static & Runtime Acceptance Gates (`validate_10.py` — 28 Static / 37 Total Gates)
* **Static Gates (28):**
  1. `compose_no_latest_tags`: All images pinned to specific version tags.
  2. `compose_no_default_creds`: No hardcoded database or broker credentials.
  3. `env_example_exists`: `.env.example` template present in repository root.
  4. `env_gitignored`: `.env` ignored by version control.
  5. `no_generated_artifacts_tracked`: Output artifacts untracked.
  6. `requirements_pinned`: All Python requirements pinned with exact versions (`==`).
  7. `gitlab_ci_stages`: Required CI stages present (`lint`, `test-python`, `test-java`, `integration`, `validate`).
  8. `java_tests_api-gateway`: Unit/integration tests present.
  9. `java_tests_auth-service`: Unit/integration tests present.
  10. `java_tests_order-service`: Unit/integration tests present.
  11. `java_tests_payment-service`: Unit/integration tests present.
  12. `orchestrator_uses_logging`: Structured logger utilized without standard output `print` calls.
  13. `orchestrator_no_bare_except`: No bare `except:` clauses.
  14. `no_hardcoded_creds`: Credentials sourced from environment variables.
  15. `redis_allowlist_typo_fixed`: Correct error keyword matching in noise filters.
  16. `grafana_prometheus_provisioned`: Prometheus datasource configuration provisioned.
  17. `grafana_dashboard_provisioned`: System overview dashboard JSON provisioned.
  18. `cross_platform_entrypoint`: Cross-platform execution entrypoint (`run.sh` / `Makefile`) present.
  19. `compose_no_fallback_creds`: No `:-` fallback credentials in `docker-compose.yml`.
  20. `compose_ports_loopback`: All published ports bound to `127.0.0.1`.
  21. `redis_requirepass`: Redis configured with `--requirepass`.
  22. `downstream_security_deps`: Downstream services include `spring-boot-starter-security`.
  23. `no_hardcoded_jwt_secret`: No secret literals present in Java source trees.
  24. `atomic_write_has_fsync`: Atomic JSON writes call `os.fsync()`.
  25. `lock_file_never_deleted`: `file_lock_context` preserves lock files.
  26. `chaos_latency_validated`: Network latency input validated to 1..10000ms.
  27. `deadlock_clearable`: All `ChaosController.java` classes implement clearable `AtomicBoolean` and `tryLock`.
  28. `run_scripts_fail_closed`: Startup scripts abort on default placeholder tokens.
* **Runtime Gates (9):**
  1. `trace_ratio_errwarn>=0.95`: Trace correlation ratio on error/warn logs.
  2. `redis_med_high==0`: Noise filter eliminates false-positive Redis medium/high incidents.
  3. `rabbitmq_in_top5==0`: Startup broker noise excluded from top-5 incident ranking.
  4. `top5_no_stack_fragments`: Orphan stack trace lines excluded from cluster templates.
  5. `timestamps_iso8601`: Valid ISO-8601 UTC timestamps across all incident log samples.
  6. `chaos_label_coverage>=0.90`: Correlated chaos mutation labels on High/Critical incidents.
  7. `topology_consistent`: All incident target services mapped in topology graph.
  8. `dataset_fresh<24h`: Generated master dataset freshness window.
  9. `dataset_metadata_lineage`: Presence of `DatasetMeta` lineage metadata (`dataset_version`, `processor_version`, `git_sha`).