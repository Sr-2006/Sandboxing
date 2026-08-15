# Auto-SRE Platform: Project State & Architecture Registry

## Metadata & Status Stamp

| Attribute | Details |
| :--- | :--- |
| **Project Name** | Smart Horizon Hackathon - V2 Microservices & Auto-SRE Platform |
| **Last Modified Date** | August 15, 2026 |
| **Current Phase** | Phase 1 Hardening 10/10 Completed — Fully Validated & Ready for Phase 2 (ChromaDB Fingerprinting & Multi-Agent RCA) |
| **Repository State** | Dockerized microservices stack with end-to-end distributed telemetry and observability, OpenTelemetry MDC trace propagation, Logstash JSON logging, Grafana Loki log pipeline, Prometheus metrics, Jaeger traces, 13-type chaos orchestration catalog, versioned Drain3 clustering (v2), dynamic priority scoring engine, validated Pydantic v2 Unified Master Dataset, and comprehensive 24-test pytest suite (100% pass). Hardened for 16GB RAM / RTX 3050. |

---

## 1. System Architecture & Component Inventory

The Auto-SRE system is an event-driven, containerized microservices platform built on Java 21/17 (Spring Boot 3.2.x) and Python 3.11, instrumented for full-stack observability, active fault injection, and automated incident clustering.

### Microservices Infrastructure

*   **Edge / Entry (API Gateway):**
    *   **Technology:** Spring Cloud Gateway (WebFlux / Netty, Java 21).
    *   **Port:** `8080` (public ingress).
    *   **Responsibilities:** JWT token validation, request routing, downstream service discovery, and edge chaos simulation (`FailureInjectionFilter.java`).
    *   **Tracing & MDC:** Equipped with `TraceMDCWebFilter.java` (`com.ecommerce.gateway.config`) and `GlobalWebExceptionHandler.java` ensuring reactor exchange trace context propagation and in-scope error logging.
*   **Auth Service:**
    *   **Technology:** Spring Boot 3.2.5 (Servlet / Tomcat, Java 21).
    *   **Port:** `8081` (internal).
    *   **Responsibilities:** User registration, login authentication, BCrypt password hashing, JWT minting/validation, Redis session caching, and PostgreSQL persistence.
    *   **Tracing & MDC:** Standardized with `TraceMDCFilter.java` and `@ControllerAdvice GlobalExceptionHandler.java` (`com.ecommerce.auth.config`).
*   **Order Service:**
    *   **Technology:** Spring Boot 3.2.3 (Servlet / Tomcat, Java 17).
    *   **Port:** `8082` (internal).
    *   **Responsibilities:** Order lifecycle management, state transitions, RabbitMQ asynchronous event publishing, and PostgreSQL persistence.
    *   **Tracing & MDC:** Standardized with `TraceMDCFilter.java` and `@ControllerAdvice GlobalExceptionHandler.java` (`com.autosre.orderservice.config`).
*   **Payment Service:**
    *   **Technology:** Spring Boot 3.2.3 (Servlet / Tomcat, Java 17).
    *   **Port:** `8083` (internal).
    *   **Responsibilities:** Payment processing, transaction ledger management, database query executions, and HikariCP connection management.
    *   **Tracing & MDC:** Standardized with `TraceMDCFilter.java` and `@ControllerAdvice GlobalExceptionHandler.java` (`com.autosre.paymentservice.config`).
*   **Data & Middleware Layer:**
    *   **PostgreSQL 16:** Dedicated database container managing isolated schemas (`postgres`, `auth_db`, `order_db`, `payment_db`), schema-versioned via Flyway migrations (`V1__init.sql`).
    *   **Redis 7 (Alpine):** In-memory cache for user sessions and state tokens.
    *   **RabbitMQ 3 (Management Alpine):** Asynchronous message broker for cross-service events.
*   **Observability Stack:**
    *   **OpenTelemetry Collector (`otel-collector`):** Ingests OTLP traces (`4317` gRPC / `4318` HTTP) and logs, exporting traces to Jaeger and logs to Loki.
    *   **Grafana Loki:** High-performance log aggregation engine (`3100`).
    *   **Prometheus:** Metrics time-series scraper querying microservice `/actuator/prometheus` endpoints (`9090`).
    *   **Jaeger:** Distributed tracing query and visualization engine (`16686`).
    *   **Grafana:** Centralized dashboard UI (`3000`).

---

## 2. Complete File & Directory Inventory

### Root Configuration, Automation & Telemetry Scripts

| File / Directory | Status | Description |
| :--- | :--- | :--- |
| `docker-compose.yml` | Modified | Master compose specification defining 12 services, resource ceilings (16GB RAM constraints), restart policies, and `ara.topology.*` metadata labels. |
| `run.ps1` | Existing | Master PowerShell automation script for environment setup, Docker teardown/build, and daemon bootstrapping. |
| `requirements.txt` | Existing | Python dependencies including `aiodocker`, `drain3`, `pydantic>=2.0`, `pytest`, `fastapi`, and `requests`. |
| `load_generator.py` | Modified | Multi-target HTTP load and chaos traffic generator simulating concurrent user workflows and fault triggers. |
| `continuous_telemetry.py` | Modified | Asynchronous telemetry collector querying Docker stats, system metrics, and container logs with rolling $z$-score anomaly calculation and W3C/JSON trace parsing. |
| `frontend_data_sync.py` | Modified | Daemon aggregating service health scores, container dependency states, and time-series snapshots. |
| `chaos_orchestrator.py` | Modified | Core chaos engine executing 13+ fault types (CPU throttle, memory limit, network latency/loss, DB connection saturation, HTTP exceptions). |
| `chaos_scenarios.py` | Existing | Multi-fault chaos scenario runner with atomic state locking via `chaos_history.json`. |
| `phase1_processor.py` | **Hardened (v2)** | Drain3 clustering engine with 11 advanced masking regexes, stack trace multi-line stitching, dynamic priority scoring, main-thread startup log exclusion, and Redis/RabbitMQ lifecycle noise filtering. |
| `phase1_schema.py` | Existing | Pydantic v2 data contract defining the strict schema for the Unified Master Dataset. |
| `package_ml_dataset.py` | Existing | Top-level aggregator validating clustered incidents, dynamic topologies, time-series metrics, and chaos history into the master ML dataset. |
| `monitor_ram.py` | Existing | Host memory guard daemon enforcing memory safety on 16GB systems. |
| `validate.py` | **New** | Automated acceptance verification script validating the 5 SRE quality gates. |
| `validation_report.json` | **New** | Output report recording 10/10 acceptance gate metrics. |
| `PHASE1_VALIDATION.md` | **New** | Comprehensive Phase 1 final validation report and architectural audit. |
| `otel-collector-config.yaml`| Modified | OpenTelemetry Collector pipeline configuration. |
| `prometheus.yml` | Existing | Prometheus scraping configuration. |
| `loki/loki-config.yaml` | Existing | Grafana Loki storage and retention configuration. |
| `phase2expectations.txt` | Modified | Formal contract specifying the input requirements and expected output deliverables for Phase 2. |
| `tests/` (12 files) | **Verified (24/24)** | Comprehensive test suite testing atomic writes, regex masking, noise filtering, priority scoring, schema validation, stack trace stitching, timestamp parsing, and trace extraction. |

### Telemetry & Dataset Layer (`frontend_data/`)

| File | Purpose |
| :--- | :--- |
| `raw_telemetry.json` | Live container state, CPU/memory limits, exit codes, and anomaly scores. |
| `status.json` | Real-time system health score, active warnings, and dependency connectivity status. |
| `time_series.json` | Rolling historical window of CPU and memory utilization per container. |
| `events_and_incidents.json` | Normalized log event stream with timestamps, levels, container labels, and correlated trace/span IDs. |
| `processed_incidents.json` | Clustered incident templates with priority scores, log samples, metrics snapshots, and chaos metadata. |
| `unified_master_dataset.json`| **Master ML Deliverable:** The fully validated Pydantic dataset feeding Phase 2 vectorization and multi-agent RCA. |
| `drain3_state.bin` | Persisted Drain3 clustering state tree. |
| `drain3_version.meta` | Version migration header file (ensures cache invalidation on processor updates). |
| `chaos_history.json` | Audit trail of all injected chaos mutations, target containers, parameters, and time windows. |
| `analytics.json` | Historical health scores and degradation event records. |

---

## 3. Detailed Logic & Hardening Enhancements

### A. Trace Context Propagation (100% Correlation)
1. **Manual MDC Filters:** Created `TraceMDCFilter.java` for Servlet microservices (`auth-service`, `order-service`, `payment-service`) and `TraceMDCWebFilter.java` for WebFlux (`api-gateway`). Placed in proper Spring component-scan packages (`com.ecommerce.gateway.config`, `com.ecommerce.auth.config`, `com.autosre.orderservice.config`, `com.autosre.paymentservice.config`).
2. **Dual Context Extraction:** The filter attempts to resolve trace and span IDs first from Micrometer's `Tracer.currentSpan()` and falls back to OpenTelemetry's native `Span.current().getSpanContext()`, ensuring context is bound to SLF4J MDC as `trace_id` and `span_id`.
3. **App-Scope Exception Handlers:** Added `@ControllerAdvice GlobalExceptionHandler` and `WebExceptionHandler` beans to catch and log unhandled controller exceptions *before* the servlet/reactor request scope is unwound, guaranteeing 100% trace correlation on critical error logs.
4. **Logstash JSON Encoding:** Configured `logback-spring.xml` across all 4 microservices with `LogstashEncoder`, including `trace_id` and `span_id` as well as mapped keys `traceId=trace_id` and `spanId=span_id`.

### B. High-Precision Noise & Startup Filtering
1. **Main-Thread Startup Log Exclusion:** `phase1_processor.py` inspects inner JSON `thread_name`/`thread` properties; logs emitted on thread `main` (JVM bootstrap, Spring banner, Flyway schema validation, Hibernate dialect deprecations) are automatically classified as infrastructure noise and excluded from incident clusters.
2. **Redis Noise Suppression:** All non-error Redis lifecycle logs (e.g. `Warning: no config file specified`, `Ready to accept connections`) are suppressed while preserving genuine Redis errors and `WARNING` events.
3. **RabbitMQ Noise Suppression:** RabbitMQ startup banners, deprecation messages, and message store index builds are filtered using ANSI escape sequence stripping (`\x1b[0;38;5;87m...`) and error allowlisting (`connection.retry`, `out of memory`, `disk_alarm`).
4. **Drain3 Versioning:** Implemented `PROCESSOR_VERSION = 2` with `drain3_version.meta` to automatically reset persisted cluster state whenever template or masking rules are updated.

---

## 4. Phase 1 Validation & Acceptance Gates (10/10)

| Gate Metric | Condition | Target | Actual | Result |
| :--- | :--- | :--- | :--- | :--- |
| **Trace/Span ID Correlation** | `trace_ratio_errwarn` | $\ge 0.80$ | **$1.0$ (100%)** | 🟢 **PASS** |
| **Redis Med/High Severity Incidents** | `redis_med_high` | $== 0$ | **$0$** | 🟢 **PASS** |
| **RabbitMQ in Top 5 Incidents** | `rabbitmq_in_top5` | $== 0$ | **$0$** | 🟢 **PASS** |
| **Top 5 Stack Fragment Incidents** | `top5_at_star_only` | $== 0$ | **$0$** | 🟢 **PASS** |
| **Pydantic Schema Validation** | `schema_ok` | $== \text{True}$ | **`True`** | 🟢 **PASS** |
| **Pytest Test Suite** | All Unit/Contract Tests | 100% Pass | **24/24 Passed** | 🟢 **PASS** |

---

## 5. Machine Learning Dataset & Phase 2 Deliverables Specification

### A. Input Dataset Specification (`unified_master_dataset.json`)

The primary deliverable produced by Phase 1 for consumption by Phase 2 is `frontend_data/unified_master_dataset.json`. It adheres strictly to the Pydantic schema in `phase1_schema.py` and contains:

```json
{
  "generated_at": "2026-08-15T10:12:30Z",
  "dataset_version": "2.0",
  "total_incidents": 46,
  "system_summary": {
    "system_health_score": 94.5,
    "active_warnings": 0,
    "total_containers": 12,
    "unhealthy_containers": 0
  },
  "incidents": [
    {
      "system_context": {
        "objective": "Perform automated Multi-Agent Root Cause Analysis (RCA) and recommend corrective actions.",
        "environment": "Dockerized Microservices (Java/Spring Boot, PostgreSQL, Redis, RabbitMQ, OpenTelemetry)",
        "current_health_score": 94.5,
        "active_warnings": 0
      },
      "incident_event": {
        "incident_id": "payment-service_75",
        "target_service": "payment-service",
        "priority_score": 68.45,
        "severity": "HIGH",
        "occurrence_count": 24
      },
      "infrastructure_topology": {
        "role": "service",
        "downstream_dependencies": ["postgres-db", "rabbitmq"],
        "exposed_ports": ["8083:8083"]
      },
      "service_health_status": {
        "docker_status": "running",
        "health_check": "healthy",
        "dependency_states": {
          "database": "connected",
          "message_broker": "connected"
        }
      },
      "telemetry_evidence": {
        "log_cluster_template": "Unhandled exception: ResourceAccessException: <*> connection reset",
        "log_samples": [
          {
            "timestamp": "2026-08-15T10:12:23Z",
            "level": "ERROR",
            "content": "{\"@timestamp\":\"2026-08-15T10:12:23Z\",\"message\":\"Unhandled exception...\",\"trace_id\":\"7622efafd8d4a1dff7cc25347613fd3d\",\"span_id\":\"30fe12c4ed4aa947\"}",
            "trace_id": "7622efafd8d4a1dff7cc25347613fd3d",
            "span_id": "30fe12c4ed4aa947"
          }
        ],
        "metrics_snapshot": [
          {
            "timestamp": "2026-08-15T10:12:20Z",
            "cpu_percent": 12.4,
            "memory_usage_bytes": 314572800,
            "memory_usage_percent": 58.6
          }
        ]
      },
      "injected_chaos_context": {
        "active_infrastructure_mutations": "Infrastructure orchestrator triggered http_throw (type=connection-reset) on payment-service (duration: 87s)."
      }
    }
  ]
}
```

### B. Phase 2 Expected Deliverables & Architecture

Phase 2 builds directly upon the Phase 1 master dataset to deliver an Autonomous Multi-Agent Root Cause Analysis (RCA) and Self-Healing Engine:

1. **ChromaDB Vector Embeddings & Fingerprinting:**
   *   **Input:** `telemetry_evidence.log_cluster_template`, `incident_event.target_service`, `infrastructure_topology`, and historical chaos scenarios.
   *   **Mechanism:** Embed incident signatures using SentenceTransformers (`all-MiniLM-L6-v2`) into a local ChromaDB collection.
   *   **Deliverable:** Fast similarity search for rapid retrieval of historical incident archetypes and recurring failure patterns.
2. **Cross-Service Trace Correlation Engine:**
   *   **Input:** Correlated `trace_id` and `span_id` extracted from Phase 1 logs.
   *   **Mechanism:** Query Jaeger / Loki API using the incident trace IDs to reconstruct the distributed call graph and pinpoint the exact upstream or downstream root failure point across microservice boundaries.
   *   **Deliverable:** Causal dependency graphs mapping failure cascades (e.g. API Gateway 502 caused by Payment Service DB Connection Pool Exhaustion).
3. **Multi-Agent RCA Orchestration (LangGraph / CrewAI):**
   *   **Specialized Agent Roles:**
       *   *Telemetry & Metric Analyst Agent:* Analyzes CPU/memory utilization anomalies and log volume spikes.
       *   *Topology & Dependency Reasoner Agent:* Evaluates blast radius across downstream and upstream services.
       *   *Chaos & Anomaly Correlation Agent:* Correlates observed degradation with known chaos injection events.
       *   *Lead SRE Investigator Agent:* Synthesizes findings into a unified RCA narrative.
   *   **Deliverable:** Structured incident analysis reports containing:
       *   Root cause diagnosis with confidence scoring.
       *   Blast radius analysis.
       *   Cross-service trace call graph visualization.
4. **Remediation & Runbook Recommendation Engine:**
   *   **Deliverable:** Automated, actionable remediation strategies (e.g., automated pod restart commands, DB connection pool resizing recommendations, circuit breaker trip parameters, rollback procedures).

---

## 6. Verification Summary

*   **Branch:** `phase1-final-hardening` (Uncommitted changes maintained cleanly).
*   **Acceptance Gates:** 5/5 Green (`validation_report.json`).
*   **Pytest Suite:** 24/24 Passing across all 12 test files (`tests/`).
*   **Documentation:** `PROJECT_STATE.md` and `PHASE1_VALIDATION.md` fully synchronized and up to date.