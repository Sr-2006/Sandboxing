# Auto-SRE Platform: Project State & Architecture Registry

## Metadata & Status Stamp

| Attribute | Details |
| :--- | :--- |
| **Project Name** | Smart Horizon Hackathon - V2 Microservices & Auto-SRE Engine |
| **Last Modified Date** | August 7, 2026 |
| **Current Phase** | Phase 1 (Log Clustering & Priority Engine) Complete. Ready for Phase 2. |
| **Repository State** | Initialized, Dockerized, telemetry extraction active, frontline noise-reduction deployed. |

---

## System Architecture Overview

The system is an event-driven, microservices-based architecture built with Java (Spring Boot), heavily instrumented for comprehensive observability and active Chaos Engineering.

*   **Edge / Entry (API Gateway):** Acts as the single entry point. Handles JWT-based authentication validation and houses the primary `FailureInjectionFilter` to simulate network-level degradation (latency, HTTP 429 rate-limiting).
*   **Auth Service:** Handles user registration, login, and JWT generation.
*   **Order Service:** Core business logic for processing orders.
*   **Payment Service:** Core business logic for financial transactions.
*   **Data Layer:** A single consolidated PostgreSQL 16 container managing isolated logical databases (`auth_db`, `order_db`, `payment_db`). Caching via Redis 7. Message brokering via RabbitMQ 3.
*   **Observability Pipeline:** 100% trace sampling via OpenTelemetry Collector exporting metrics to Prometheus and traces to Jaeger. Real-time telemetry is continuously extracted and synchronized into JSON schemas.
*   **Auto-SRE Engine:** A multi-phase pipeline that clusters noisy logs, mathematically prioritizes them, and prepares them for LLM-based Root Cause Analysis (RCA).

---

## Complete File & Directory Inventory

### Root Configuration, Automation & Telemetry Scripts

| File | Description |
| :--- | :--- |
| `docker-compose.yml` | Master infrastructure orchestrator defining containers and `ara.topology.group` labels. |
| `run.ps1` | Automated PowerShell execution script to cleanly tear down, build, and deploy the cluster. |
| `load_generator.py` | Python traffic generator simulating user flows and chaos endpoint triggers. |
| `continuous_telemetry.py` | Data extractor daemon querying Docker container state and resource metrics. |
| `frontend_data_sync.py` | Formatter daemon that transforms raw telemetry dumps into structured JSON files. |
| `chaos_orchestrator.py` | Automated chaos injection tool using Docker SDK to manipulate container states. |
| `phase1_processor.py` | **[NEW]** Drain3-powered log clustering and dynamic priority scoring engine. |
| `otel-collector-config.yaml` | Defines OpenTelemetry Collector receivers, processors, and exporters. |
| `prometheus.yml` | Scrape configuration instructing Prometheus to pull metrics. |

### Telemetry Output Layer (`frontend_data/`)

| File | Description |
| :--- | :--- |
| `status.json` | Real-time operational status and health metrics of active microservices. |
| `time_series.json` | Historical CPU/Memory usage metrics across container lifecycles. |
| `events_and_incidents.json` | Raw incident logs recording chaos triggers and stack traces. |
| `processed_incidents.json` | **[NEW]** Clean, deduplicated, and prioritized incident templates outputted by Phase 1. |
| `analytics.json` (etc.) | Operational analysis datasets including causality and cost ROI mapping. |

### Microservices Source Directories

| Directory | Description |
| :--- | :--- |
| `api-gateway/` | Contains `FailureInjectionFilter.java` and edge security configurations. |
| `auth-service/` | Contains user domain logic, JWT generation, and `auth_db` connections. |
| `order-service/` | Contains order processing logic and `order_db` connections. |
| `payment-service/` | Contains financial transaction logic and `payment_db` connections. |
| `postgres-init/` | Contains `init.sql` for auto-provisioning isolated databases. |

---

## Changelog & Historical Log

*   **Pre-August 2026:** Designed microservices architecture and implemented Spring Boot core logic.
*   **August 5, 2026:** Consolidated databases, wired OTLP tracing, and validated Python telemetry extraction.
*   **August 7, 2026:** Designed and deployed `phase1_processor.py` to act as the frontline noise filter.
*   **August 7, 2026:** Implemented Drain3 unsupervised machine learning to dynamically cluster unknown Java stack traces.
*   **August 7, 2026:** Built composite key generation (`container_clusterID`) to accurately isolate errors to specific microservices.
*   **August 7, 2026:** Engineered a mathematical priority scoring system prioritizing errors based on velocity, blast radius, and physical container health.
*   **August 7, 2026:** Validated the `processed_incidents.json` payload contract for Phase 2 handoff.

---

## Active Configuration & Endpoints

### Infrastructure Ports

| Service | Endpoint / Port | Credentials (If Applicable) |
| :--- | :--- | :--- |
| **API Gateway** | `http://localhost:8080` | N/A |
| **Auth / Order / Payment** | `8081`, `8082`, `8083` (Internal) | N/A |
| **PostgreSQL** | `localhost:5432` | `postgres` / `postgres` |
| **Redis** | `localhost:6379` | N/A |
| **RabbitMQ** | `localhost:5672` (UI: `15672`) | `guest` / `guest` |

### Observability UIs

| Dashboard | URL | Credentials |
| :--- | :--- | :--- |
| **Jaeger UI** | `http://localhost:16686` | N/A |
| **Prometheus UI** | `http://localhost:9090` | N/A |
| **Grafana UI** | `http://localhost:3000` | `admin` / `admin` |

---