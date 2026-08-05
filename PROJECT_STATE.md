# Auto-SRE Platform: Project State & Architecture Registry

## 1. Metadata & Status Stamp
* **Project Name:** Smart Horizon Hackathon - V2 Microservices & Auto-SRE Engine
* **Last Modified Date:** August 5, 2026
* **Current Phase:** Backend Infrastructure & Telemetry Data Pipeline Validated. Ready for Command Center UI Integration.
* **Repository State:** Initialized, Dockerized, live-tested with active chaos injection and telemetry extraction.

## 2. System Architecture Overview
The system is an event-driven, microservices-based architecture built with Java (Spring Boot), heavily instrumented for comprehensive observability and active Chaos Engineering.

* **Edge / Entry (API Gateway):** Acts as the single entry point. Handles JWT-based authentication validation and houses the primary `FailureInjectionFilter` to simulate network-level degradation (latency, HTTP 429 rate-limiting).
* **Core Microservices:** 
  * `auth-service`: Handles user registration, login, and JWT generation.
  * `order-service`: Core business logic for processing orders.
  * `payment-service`: Core business logic for financial transactions.
* **Data Layer:** A single consolidated PostgreSQL 16 container managing isolated logical databases (`auth_db`, `order_db`, `payment_db`). Caching via Redis 7. Message brokering via RabbitMQ 3.
* **Observability Pipeline:** 100% trace sampling via OpenTelemetry Collector exporting metrics to Prometheus and traces to Jaeger. Real-time telemetry is continuously extracted and synchronized into JSON schemas for consumption by the UI engine.

## 3. Complete File & Directory Inventory

### Root Configuration, Automation & Telemetry Scripts
* `docker-compose.yml`: Master infrastructure orchestrator defining all 11 containers, port mappings, network definitions, and `ara.topology.group=backend` labels.
* `run.ps1`: Automated PowerShell execution script to cleanly tear down, build, and deploy the entire Dockerized cluster.
* `load_generator.py`: Python traffic generator simulating user flows and chaos endpoint triggers.
* `continuous_telemetry.py`: Data extractor daemon querying Docker container state and resource metrics for labeled backend containers.
* `frontend_data_sync.py`: Formatter daemon that transforms raw telemetry dumps into structured JSON files for the frontend.
* `chaos_orchestrator.py`: Automated chaos injection tool using Docker SDK to pause target containers (e.g., `postgres-db`) and validate system recovery.
* `otel-collector-config.yaml`: Defines OpenTelemetry Collector receivers, processors, and exporters.
* `prometheus.yml`: Scrape configuration instructing Prometheus to pull metrics from microservices and OTel collector.
* `.gitignore`: Standard Git exclusions for Java/Python/Node/Docker artifacts.
* `PROJECT_STATE.md`: Master state registry and context-restore document.

### Telemetry Output Layer (`frontend_data/`)
* `status.json`: Real-time operational status and health metrics of active microservices.
* `time_series.json`: Historical CPU/Memory usage metrics across container lifecycles.
* `events_and_incidents.json`: Incident log recording chaos triggers, error states, and resolution events.
* `analytics.json`, `causality.json`, `cost_and_roi.json`: Operational analysis datasets for system impact assessment.

### Database Initialization
* `postgres-init/init.sql`: Auto-executed script that creates logical databases (`auth_db`, `order_db`, `payment_db`) on PostgreSQL container boot.

### API Gateway (`api-gateway/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `ApiGatewayApplication.java`: Spring Boot main entry point.
* `config/GatewaySecurityConfig.java`: Configures edge security and authentication routes.
* `controller/FailureInjectionController.java`: REST endpoints for dynamic gateway chaos configuration.
* `filter/FailureInjectionFilter.java`: Traffic filter injecting artificial latency and rate limiting.
* `filter/JwtValidationFilter.java`: JWT signature verification filter.
* `application.yml`: Route predicate definitions and OTLP exporter settings.

### Auth Service (`auth-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `AuthServiceApplication.java`: Spring Boot main entry point.
* `config/AuthSecurityConfig.java`: Internal domain security configurations.
* `controller/AuthController.java`: Handles `/login` and `/register` endpoints.
* `controller/FailureInjectionController.java`: Localized chaos injection endpoints.
* `dto/AuthResponse.java`, `LoginRequest.java`, `RegisterRequest.java`: DTOs for authentication.
* `model/User.java`: Entity mapping for `auth_db`.
* `repository/UserRepository.java`: JPA repository interface.
* `util/JwtUtil.java`: Utility class for signing and verifying JWTs.
* `application.yml`: Datasource connection and OTLP settings.

### Order Service (`order-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `OrderServiceApplication.java`: Spring Boot main entry point.
* `OrderController.java`: Endpoints for order processing.
* `application.yml`: Datasource connection (`order_db`) and OTLP settings.

### Payment Service (`payment-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `PaymentServiceApplication.java`: Spring Boot main entry point.
* `PaymentController.java`: Financial transaction logic and failure simulation endpoints.
* `application.yml`: Datasource connection (`payment_db`) and OTLP settings.

## 4. Changelog & Historical Log
* **Pre-August 2026:** Designed microservices architecture and implemented Spring Boot core logic.
* **August 5, 2026:** 
  * Consolidated database architecture to a single shared Postgres container with isolated schemas.
  * Fully wired OpenTelemetry (OTLP) tracing across all services with 100% sampling probability.
  * Resolved OTLP port binding conflicts between Jaeger and OpenTelemetry Collector.
  * Added topology classification labels (`ara.topology.group=backend`) across all microservices in `docker-compose.yml`.
  * Built and validated Python telemetry extraction (`continuous_telemetry.py`) and JSON synchronization (`frontend_data_sync.py`).
  * Created `chaos_orchestrator.py` and validated database pause/unpause chaos injection cycles.
  * Verified end-to-end data flow: traffic generation -> container crash -> telemetry capture -> live JSON dataset generation.

## 5. Active Configuration & Endpoints
**Infrastructure Ports:**
* API Gateway: `http://localhost:8080`
* Auth Service: `http://localhost:8081` (Internal)
* Order Service: `http://localhost:8082` (Internal)
* Payment Service: `http://localhost:8083` (Internal)
* PostgreSQL: `localhost:5432` (Credentials: postgres/postgres)
* Redis: `localhost:6379`
* RabbitMQ: `localhost:5672` (Management UI: `http://localhost:15672`, guest/guest)

**Observability UIs:**
* Jaeger UI (Traces): `http://localhost:16686`
* Prometheus UI (Metrics): `http://localhost:9090`
* Grafana UI (Dashboards): `http://localhost:3000` (admin/admin)

## 6. Next Roadmap Steps
* Initialize Command Center UI directory and install dependencies.
* Render 3D system topology map consuming `frontend_data/status.json` and `frontend_data/time_series.json`.
* Wire interactive chaos control triggers directly to microservice failure endpoints.