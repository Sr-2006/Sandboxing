# Auto-SRE Platform: Project State & Architecture Registry

## 1. Metadata & Status Stamp
* **Project Name:** Smart Horizon Hackathon - V2 Microservices & Auto-SRE Engine
* **Last Modified Date:** August 5, 2026
* **Current Phase:** Backend Infrastructure Complete & Validated. Transitioning to Frontend (Command Center UI).
* **Repository State:** Initialized, Dockerized, and live-tested.

## 2. System Architecture Overview
The system is an event-driven, microservices-based architecture built with Java (Spring Boot), heavily instrumented for comprehensive observability and active Chaos Engineering.

* **Edge / Entry (API Gateway):** Acts as the single entry point. Handles JWT-based authentication validation and houses the primary `FailureInjectionFilter` to simulate network-level degradation (latency, HTTP 429 rate-limiting).
* **Core Microservices:** 
  * `auth-service`: Handles user registration, login, and JWT generation.
  * `order-service`: Core business logic for processing orders.
  * `payment-service`: Core business logic for financial transactions.
* **Data Layer:** A single consolidated PostgreSQL 16 container managing isolated logical databases (`auth_db`, `order_db`, `payment_db`). Caching via Redis 7. Message brokering via RabbitMQ 3.
* **Observability Pipeline:** 100% trace sampling. Telemetry data is exported via OTLP to the OpenTelemetry Collector, which distributes metrics to Prometheus and distributed traces to Jaeger. Grafana sits on top for visualization.

## 3. Complete File & Directory Inventory

### Root Configuration & Automation
* `docker-compose.yml`: Master infrastructure orchestrator defining all 9 containers, port mappings, and internal networking.
* `run.ps1`: Automated PowerShell execution script to cleanly tear down, build, and deploy the entire Dockerized cluster.
* `load_generator.py`: Python-based traffic bot designed to spam the microservices with normal and chaos-triggering HTTP requests to generate live telemetry.
* `otel-collector-config.yaml`: Defines how the OpenTelemetry Collector receives OTLP data and exports it to Prometheus/Jaeger.
* `prometheus.yml`: Scrape configuration instructing Prometheus to pull metrics from the microservices and OTel collector.
* `.gitignore`: Standard Git exclusions for Java/Node/Docker artifacts.
* `PROJECT_STATE.md`: This file. The master state registry and context-restore document.

### Database Initialization
* `postgres-init/init.sql`: Auto-executed script that creates the logical databases (`auth_db`, `order_db`, `payment_db`) when the Postgres container first boots.

### API Gateway (`api-gateway/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `ApiGatewayApplication.java`: Spring Boot main class for the Gateway.
* `config/GatewaySecurityConfig.java`: Configures edge security and defines which routes require authentication.
* `controller/FailureInjectionController.java`: Exposes REST endpoints to dynamically toggle chaos variables in the gateway.
* `filter/FailureInjectionFilter.java`: Intercepts traffic to inject artificial latency or trigger HTTP 429 Rate Limit errors based on volatile variables.
* `filter/JwtValidationFilter.java`: Intercepts incoming requests to validate JWT signatures before routing them to internal services.
* `application.yml`: Defines route predicates pointing to internal services and configures 100% OTLP trace sampling.

### Auth Service (`auth-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `AuthServiceApplication.java`: Spring Boot main class.
* `config/AuthSecurityConfig.java`: Internal security configurations for auth endpoints.
* `controller/AuthController.java`: Handles `/login` and `/register` HTTP requests.
* `controller/FailureInjectionController.java`: Localized chaos injection endpoints specific to the auth domain.
* `dto/AuthResponse.java`, `LoginRequest.java`, `RegisterRequest.java`: Data Transfer Objects for JSON serialization.
* `model/User.java`: Entity mapping to the PostgreSQL `auth_db`.
* `repository/UserRepository.java`: JPA repository interface for database operations.
* `util/JwtUtil.java`: Utility class for signing and verifying JSON Web Tokens.
* `application.yml`: Database connection strings and OTLP exporter configuration.

### Order Service (`order-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `OrderServiceApplication.java`: Spring Boot main class.
* `OrderController.java`: Exposes business logic endpoints for order creation and management.
* `application.yml`: Database connection strings (`order_db`) and OTLP exporter configuration.

### Payment Service (`payment-service/`)
* `pom.xml` & `Dockerfile`: Build and containerization configurations.
* `PaymentServiceApplication.java`: Spring Boot main class.
* `PaymentController.java`: Exposes business logic for transactions and localized chaos/failure endpoints (e.g., simulating card declines).
* `application.yml`: Database connection strings (`payment_db`) and OTLP exporter configuration.

## 4. Changelog & Historical Log
* **Pre-August 2026:** Designed microservice architecture and implemented Spring Boot core logic.
* **August 5, 2026:** 
  * Consolidated database architecture to a single shared Postgres container with isolated schemas.
  * Fully wired OpenTelemetry (OTLP) tracing across all services with 100% sampling probability.
  * Verified `FailureInjectionFilter` for dynamic latency and rate-limiting at the Gateway layer.
  * Resolved `.git/index.lock` file locking issues.
  * Resolved Docker Engine connection failures and network timeout (`unexpected EOF`, `TLS handshake timeout`) during base image pulls.
  * Validated full cluster spin-up via `docker-compose up -d --build`.

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

**Chaos Endpoints (Example):**
* Gateway Chaos: Toggle via Gateway API
* Order Chaos: `/api/v1/orders/chaos/error` (Routed via Gateway)
* Payment Chaos: `/api/v1/payments/chaos/latency`, `/api/v1/payments/chaos/decline` (Routed via Gateway)

## 6. Next Roadmap Steps
* **Phase 3 (Frontend):** Select a frontend framework (React/Next.js/Vue) and initialize the Command Center UI repository.
* **UI Integration:** Build the interactive topology map that visualizes the microservices.
* **Chaos Dashboard:** Wire frontend buttons directly to the `FailureInjectionController` endpoints to trigger live incidents.
* **Telemetry Embedding:** Embed Grafana panels or query Prometheus directly to show real-time metrics reacting to the injected chaos.