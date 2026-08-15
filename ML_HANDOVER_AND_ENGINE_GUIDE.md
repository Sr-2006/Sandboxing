# Auto-SRE Engine: Machine Learning Handover & Complete Technical Reference

This document is a complete, self-contained reference guide for the **Machine Learning, Vector Database (ChromaDB), and Multi-Agent Root Cause Analysis (RCA)** engineers. It details the initial contract, explains how the hardened engine fulfills and enhances downstream requirements, maps all extractable data files with inspection commands, and catalogs all simulated error and chaos scenarios across services.

---

## Table of Contents
1. [Contract Alignment: Initial Contract vs. Hardened Engine](#1-contract-alignment-initial-contract-vs-hardened-engine)
2. [Data Extraction Catalog & File Map](#2-data-extraction-catalog--file-map)
3. [Extra Advanced Data Feeds Available for ML & Agents](#3-extra-advanced-data-feeds-available-for-ml--agents)
4. [Service-by-Service Catalog of Simulated Faults & Errors](#4-service-by-service-catalog-of-simulated-faults--errors)
5. [ML Training, Vector Indexing & Phase 2 Integration Guide](#5-ml-training-vector-indexing--phase-2-integration-guide)

---

## 1. Contract Alignment: Initial Contract vs. Hardened Engine

The original Phase 1 contract (`phase2expectations.txt`) defined a strict payload structure required by Phase 2 (ChromaDB) and Phase 3 (LLM Agents). The hardened engine produces **100% schema-compliant output** while significantly improving data quality and signal fidelity.

### Side-by-Side Comparison

| Contract Requirement | Initial Baseline State | Hardened Engine Deliverable | Downstream Benefit for ML & Agents |
| :--- | :--- | :--- | :--- |
| **Output JSON Schema** | Ad-hoc unvalidated JSON | Strict Pydantic v2 validation (`phase1_schema.py`) | **Zero schema drift**; no unexpected null crashes in PyTorch/Transformers pipelines. |
| **Incident IDs** | Risk of UUIDs or unformatted strings | Deterministic composite string: `<service>_<cluster_id>` | Enables time-series velocity tracking of recurring clusters. |
| **Log Templates** | Fragmented `at <*>` single-line stack frames | Multi-line stitched exception classes with 11 regex maskers | **Clean, semantically rich text** for sentence embeddings (e.g., `all-MiniLM-L6-v2`). |
| **Trace Context** | Missing/null trace IDs (0% correlation) | **100% real 32-hex W3C `trace_id` + 16-hex `span_id`** | Direct correlation with Jaeger distributed call graphs. |
| **Infrastructure Noise** | Redis/RabbitMQ lifecycle startup noise in Top 5 | Suppressed non-error infra logs; 0 noise in Top 5 | Prevents ML models from training on irrelevant operational noise. |
| **Chaos Context** | Static or empty strings | Automated ground-truth correlation with `chaos_history.json` | **Labeled ground truth** for supervised classification and RCA evaluation. |
| **Priority Scoring** | Simple event count | Multi-variable mathematical model (velocity + state + anomaly - decay) | Pre-sorted priority queue for agent triage prompts. |

---

## 2. Data Extraction Catalog & File Map

All processed data and raw telemetry streams reside in the `frontend_data/` directory.

```
auto-sre-platform/
├── frontend_data/
│   ├── unified_master_dataset.json   <-- Primary ML/Agent Input (Validated Pydantic)
│   ├── processed_incidents.json      <-- Clustered incidents with metrics & samples
│   ├── events_and_incidents.json     <-- Raw ingested log stream with trace IDs
│   ├── raw_telemetry.json            <-- Live container stats & z-score anomaly scores
│   ├── status.json                   <-- Global system health score & dependency states
│   ├── time_series.json              <-- Rolling historical CPU/memory time-series
│   ├── chaos_history.json            <-- Ground-truth audit log of injected faults
│   ├── analytics.json                <-- System health degradation trends
│   ├── drain3_state.bin              <-- Binary tree state of log cluster templates
│   ├── drain3_version.meta           <-- Version header (v2 migration guard)
│   └── health_warnings.log           <-- Host machine memory safety logs
└── validation_report.json            <-- 5/5 Acceptance gates validation summary
```

---

### File Details & Extraction Commands

### 1. `frontend_data/unified_master_dataset.json`
*   **Purpose:** The primary, master dataset for Phase 2 vectorization and Phase 3 Agent RCA.
*   **Schema Enforcement:** Pydantic v2 model `UnifiedMasterDataset` in `phase1_schema.py`.
*   **Key Fields:** `generated_at`, `system_context` (`current_health_score`, `active_warnings`), `incidents[]` (`incident_id`, `target_service`, `priority_score`, `severity`, `infrastructure_topology`, `service_health_status`, `telemetry_evidence`, `injected_chaos_context`).
*   **Generation Command:**
    ```bash
    python package_ml_dataset.py
    ```
*   **Python Inspection Snippet:**
    ```python
    import json
    with open("frontend_data/unified_master_dataset.json") as f:
        data = json.load(f)
    print(f"Total Incidents: {len(data['incidents'])}")
    for inc in data['incidents'][:3]:
        print(inc['incident_event']['incident_id'], inc['incident_event']['severity'])
    ```

---

### 2. `frontend_data/processed_incidents.json`
*   **Purpose:** Output produced by the Drain3 clustering and prioritization engine.
*   **Key Fields:** Top-level incident list sorted by priority score, including Drain3 templates, top 5 raw log samples, and recent 3-point resource snapshots.
*   **Generation Command:**
    ```bash
    python phase1_processor.py --reset-drain
    ```
*   **Verification Command:**
    ```bash
    python validate.py
    ```

---

### 3. `frontend_data/events_and_incidents.json`
*   **Purpose:** Canonical raw log stream aggregated across all 12 containers.
*   **Key Fields:** `timestamp`, `container`, `level` (`ERROR`, `WARN`, `INFO`), `content` (Logstash JSON or unmasked string), `trace_id`, `span_id`.
*   **Extraction Command:**
    ```bash
    # Extract all error logs with trace IDs:
    python -c "import json; [print(x['container'], x['trace_id'], x['content'][:80]) for x in json.load(open('frontend_data/events_and_incidents.json')) if x.get('level')=='ERROR' and x.get('trace_id')]"
    ```

---

### 4. `frontend_data/raw_telemetry.json`
*   **Purpose:** Real-time container metrics, resource limits, and anomaly scores.
*   **Key Fields:** `containers[]` (`name`, `status`, `health`, `cpu_percent`, `memory_usage_bytes`, `memory_limit_bytes`, `memory_percent`, `anomaly_score`, `exit_code`).
*   **Extraction Command:**
    ```bash
    python -c "import json; [print(c['name'], 'CPU:', c['cpu_percent'], 'Mem%:', c['memory_percent'], 'AnomalyScore:', c['anomaly_score']) for c in json.load(open('frontend_data/raw_telemetry.json')).get('containers', [])]"
    ```

---

### 5. `frontend_data/status.json`
*   **Purpose:** Real-time system health summary and dependency health graph.
*   **Key Fields:** `system_health_score` (0–100), `active_warnings`, `services[]` (`name`, `docker_status`, `health_check`, `dependency_states`).
*   **Generation Command:** Continuously updated by `frontend_data_sync.py`.

---

### 6. `frontend_data/time_series.json`
*   **Purpose:** Capped rolling window of historical container utilization points.
*   **Key Fields:** Array of `{ "timestamp": "...", "container": "...", "cpu_percent": float, "memory_percent": float }`.
*   **Usage for ML:** Ideal for training sequential anomaly detection models (LSTM, GRU, Transformers) or plotting time-series degradation curves.

---

### 7. `frontend_data/chaos_history.json`
*   **Purpose:** Ground-truth audit log of all injected chaos mutations.
*   **Key Fields:** Array of `{ "scenario_id": "...", "timestamp": "...", "target": "...", "fault": "...", "params": {...}, "duration": int }`.
*   **Usage for ML:** Serves as **ground-truth target labels** for validating whether the Multi-Agent RCA deduced the correct root cause.

---

### 8. `frontend_data/health_warnings.log` & `monitor_ram.py`
*   **Purpose:** Host machine RAM guard. Monitors system-level memory every 10 seconds to ensure safe execution on 16GB RAM machines.
*   **Command to Run:**
    ```bash
    python monitor_ram.py
    ```

---

## 3. Extra Advanced Data Feeds Available for ML & Agents

Beyond the baseline contract, the hardened engine exposes several extra data streams:

1. **Statistical $Z$-Score Anomaly Scores (`raw_telemetry.json`):**
   * Dynamically tracks standard deviations of CPU and memory from a moving 20-sample window.
   * Values range from `0.0` (nominal) to `1.0` (extreme anomaly).
2. **Dynamic Topology Dependency Map (`infrastructure_topology`):**
   * Extracted at runtime from `docker-compose.yml` service definitions and `ara.topology.*` labels.
   * Provides real downstream dependency trees (`downstream_dependencies`) and exposed ports (`exposed_ports`).
3. **Multi-Factor Priority Breakdown:**
   * Includes occurrence velocity ($\log_{10}(\text{count} + 1)$), container death penalties ($+50$), and exponential time decay ($\le 20$) pre-calculated in `incident_event.priority_score`.
4. **Jaeger Distributed Trace Endpoints:**
   * Traces are queryable via Jaeger REST API on `http://localhost:16686/api/traces/<trace_id>` using the `trace_id` from `telemetry_evidence.log_samples`.

---

## 4. Service-by-Service Catalog of Simulated Faults & Errors

The platform includes an automated chaos simulation suite capable of generating 13+ distinct fault types across services and infrastructure.

```
                             [ API Gateway (8080) ]
                            /          |          \
                           /           |           \
                          ▼            ▼            ▼
             [ Auth Service ]  [ Order Service ]  [ Payment Service ]
                (Port 8081)       (Port 8082)         (Port 8083)
                     |                 |                   |
            +--------+--------+        |          +--------+--------+
            |                 |        |          |                 |
            ▼                 ▼        ▼          ▼                 ▼
      [ Redis (6379) ]  [ PostgreSQL (5432) ]  [ RabbitMQ (5672) ] [ OTel Collector ]
```

---

### A. API Gateway (`api-gateway`, Port `8080`)
*Technology: Spring Cloud Gateway / Spring WebFlux / Netty*

| Fault Name / Trigger | Error / Behavior Produced | Downstream Impact |
| :--- | :--- | :--- |
| `GET /chaos/slow?delayMs=5000` | Injects artificial 5-second latency delay. | Gateway request queue backup; HTTP client timeouts. |
| `GET /chaos/throw?type=null-pointer` | Throws `NullPointerException("Simulated NPE from ChaosController")`. | Returns HTTP 500; logs captured by `GlobalWebExceptionHandler`. |
| `GET /chaos/throw?type=sql-timeout` | Throws `DataAccessResourceFailureException("Simulated DB timeout")`. | Returns HTTP 500 with SQL error signature. |
| `GET /chaos/throw?type=connection-reset` | Throws `ResourceAccessException("Simulated connection reset")`. | Drops downstream HTTP connection. |
| `GET /chaos/memory-leak?mb=200` | Allocates 200MB byte arrays into a static list. | Triggers JVM heap exhaustion and `OutOfMemoryError`. |
| `GET /chaos/deadlock` | Launches 2 threads contending for inverted locks. | Thread exhaustion; frozen gateway worker threads. |
| `FailureInjectionFilter` | Injects simulated HTTP status codes (502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout). | Simulates downstream service route outages. |

---

### B. Auth Service (`auth-service`, Port `8081`)
*Technology: Spring Boot 3.2.5 / Tomcat / Spring Security / JWT*

| Fault Name / Trigger | Error / Behavior Produced | Downstream Impact |
| :--- | :--- | :--- |
| `GET /chaos/slow?delayMs=5000` | 5-second authentication processing delay. | Delays token validation; upstream gateway request timeout. |
| `GET /chaos/throw?type=null-pointer` | Throws `NullPointerException`. | Authentication endpoints fail with HTTP 500. |
| `GET /chaos/throw?type=sql-timeout` | Throws `DataAccessResourceFailureException`. | Simulates PostgreSQL user lookup timeout. |
| `GET /chaos/memory-leak?mb=200` | Allocates 200MB in heap memory. | Auth service performance degradation; potential OOM crash. |
| `GET /chaos/deadlock` | Locks 2 worker threads in circular dependency. | Depletes Tomcat thread pool (`http-nio-8081-exec-*`). |
| `GET /chaos/sql-lock` | Executes `SELECT pg_sleep(10)` against `auth_db`. | Locks PostgreSQL table/connections for 10 seconds. |
| `GET /chaos/exhaust-pool` | Acquires and holds all 10 HikariCP connections for 30s. | `HikariPool-1 - Connection is not available, request timed out after 30000ms`. |

---

### C. Order Service (`order-service`, Port `8082`)
*Technology: Spring Boot 3.2.3 / Tomcat / RabbitMQ Publisher / JPA*

| Fault Name / Trigger | Error / Behavior Produced | Downstream Impact |
| :--- | :--- | :--- |
| `GET /chaos/slow?delayMs=5000` | Injects 5000ms delay during order placement. | Upstream gateway timeout; degraded order checkout SLA. |
| `GET /chaos/throw?type=null-pointer` | Throws `NullPointerException`. | Order placement fails with HTTP 500. |
| `GET /chaos/throw?type=sql-timeout` | Throws `DataAccessResourceFailureException`. | Simulates `order_db` transaction timeout. |
| `GET /chaos/throw?type=connection-reset` | Throws `ResourceAccessException`. | Drops network socket mid-order processing. |
| `GET /chaos/memory-leak?mb=200` | Allocates 200MB into memory leak list. | Memory pressure on 16GB host; container throttled. |
| `GET /chaos/deadlock` | Mutex thread deadlock. | Locks order processing threads. |
| `GET /chaos/sql-lock` | Executes `SELECT pg_sleep(10)` on `order_db`. | Halts new order database writes. |
| `GET /chaos/exhaust-pool` | Exhausts HikariCP connection pool for 30s. | Database connection pool starvation. |

---

### D. Payment Service (`payment-service`, Port `8083`)
*Technology: Spring Boot 3.2.3 / Tomcat / JPA / PostgreSQL*

| Fault Name / Trigger | Error / Behavior Produced | Downstream Impact |
| :--- | :--- | :--- |
| `GET /chaos/slow?delayMs=5000` | Delays transaction processing by 5000ms. | Cascades latency upstream to Order Service & Gateway. |
| `GET /chaos/throw?type=null-pointer` | Throws `NullPointerException`. | Payment transaction failure. |
| `GET /chaos/throw?type=sql-timeout` | Throws `DataAccessResourceFailureException`. | Payment ledger transaction timeout. |
| `GET /chaos/throw?type=connection-reset` | Throws `ResourceAccessException`. | Simulates payment gateway socket drop. |
| `GET /chaos/memory-leak?mb=200` | Simulates payment transaction buffer memory leak. | Rapid JVM heap exhaustion. |
| `GET /chaos/deadlock` | Deadlocks 2 payment execution threads. | Depletes transaction executor pool. |
| `GET /chaos/sql-lock` | Executes `SELECT pg_sleep(10)` on `payment_db`. | Blocks payment ledger commits. |
| `GET /chaos/exhaust-pool` | Holds all 10 HikariCP connections for 30 seconds. | Complete payment processing outage. |

---

### E. Infrastructure & Middleware Layer
*Technology: Docker Engine / PostgreSQL / Redis / RabbitMQ / OTel Collector*

| Target Container | Fault Action | Command / Method | Observed Incident Signature |
| :--- | :--- | :--- | :--- |
| `postgres-db` | Container Pause / Kill | `docker pause postgres-db` / `docker kill` | Microservices throw `PSQLException: Connection refused` & `CannotCreateTransactionException`. |
| `redis` | Container Pause / Restart | `docker pause redis` / `docker restart` | Auth service throws `RedisConnectionException` & session caching errors. |
| `rabbitmq` | Message Backlog Injection | Injects 1,000 unconsumed messages via `pika` | RabbitMQ memory spike, queue backup, consumer lag. |
| `rabbitmq` | Container Kill | `docker kill rabbitMQ` | Order service throws `AmqpConnectException: Connection refused`. |
| `otel-collector` | Container Pause | `docker pause otel-collector` | Microservices log `Failed to export spans. Connection reset`. |
| Any Container | CPU Throttling | `docker update --cpu-period=100000 --cpu-quota=10000 <name>` | Severe CPU throttling ($0.1$ core limit), latency spikes, timeout cascades. |
| Any Container | Memory Limit Constraint | `docker update --memory=384m <name>` | Memory pressure, swap thrashing, potential OOM Kill (Exit code 137). |

---

## 5. ML Training, Vector Indexing & Phase 2 Integration Guide

This section provides ready-to-run code snippets for building Phase 2 ChromaDB vector embeddings and Phase 3 Multi-Agent prompts directly from `unified_master_dataset.json`.

### A. ChromaDB Vector Indexing Snippet

```python
import json
import chromadb
from sentence_transformers import SentenceTransformer

# 1. Initialize Vector Database & Embedding Model
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="incident_signatures")
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# 2. Load Master Dataset
with open("frontend_data/unified_master_dataset.json", "r") as f:
    master_data = json.load(f)

documents = []
metadatas = []
ids = []

# 3. Build Incident Vector Signatures
for inc in master_data.get("incidents", []):
    inc_id = inc["incident_event"]["incident_id"]
    service = inc["incident_event"]["target_service"]
    template = inc["telemetry_evidence"]["log_cluster_template"]
    severity = inc["incident_event"]["severity"]
    chaos = inc["injected_chaos_context"]["active_infrastructure_mutations"]
    
    # Extract first available trace_id (if present)
    trace_id = ""
    for sample in inc["telemetry_evidence"]["log_samples"]:
        if sample.get("trace_id"):
            trace_id = sample["trace_id"]
            break
            
    # Composite document text for semantic search
    doc_text = f"Service: {service} | Severity: {severity} | Template: {template}"
    
    documents.append(doc_text)
    ids.append(inc_id)
    metadatas.append({
        "incident_id": inc_id,
        "target_service": service,
        "severity": severity,
        "priority_score": inc["incident_event"]["priority_score"],
        "trace_id": trace_id,
        "ground_truth_chaos": chaos
    })

# 4. Upsert into ChromaDB
embeddings = embedder.encode(documents).tolist()
collection.upsert(
    ids=ids,
    embeddings=embeddings,
    documents=documents,
    metadatas=metadatas
)

print(f"Successfully indexed {len(ids)} incidents into ChromaDB collection 'incident_signatures'.")
```

---

### B. Querying for Root Cause Matching (Similarity Search)

```python
def query_similar_incidents(observed_error_text: str, top_k: int = 3):
    query_embedding = embedder.encode([observed_error_text]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )
    return results

# Example Query
matches = query_similar_incidents("ResourceAccessException connection reset in payment")
print(matches["documents"])
print(matches["metadatas"])
```

---

### C. Multi-Agent LLM Prompt Construction Example

```python
def build_agent_rca_prompt(incident_dict: dict) -> str:
    evt = incident_dict["incident_event"]
    topo = incident_dict["infrastructure_topology"]
    health = incident_dict["service_health_status"]
    evidence = incident_dict["telemetry_evidence"]
    chaos = incident_dict["injected_chaos_context"]
    
    return f"""
You are the Lead SRE AI Agent performing Root Cause Analysis (RCA).

[INCIDENT SUMMARY]
- Incident ID: {evt['incident_id']}
- Target Service: {evt['target_service']} (Severity: {evt['severity']}, Priority Score: {evt['priority_score']})
- Occurrence Count: {evt['occurrence_count']}

[TOPOLOGY & HEALTH]
- Role: {topo['role']}
- Downstream Dependencies: {', '.join(topo['downstream_dependencies'])}
- Container Status: {health['docker_status']} (Health: {health['health_check']})
- Dependency States: {json.dumps(health['dependency_states'])}

[TELEMETRY EVIDENCE]
- Mined Error Template: {evidence['log_cluster_template']}
- Representative Log Sample: {evidence['log_samples'][0]['content'] if evidence['log_samples'] else 'N/A'}
- Correlated Trace ID: {evidence['log_samples'][0].get('trace_id') if evidence['log_samples'] else 'N/A'}
- Recent Metrics Snapshot: {json.dumps(evidence['metrics_snapshot'])}

[GROUND TRUTH CHAOS CONTEXT]
- Active Injected Chaos: {chaos['active_infrastructure_mutations'] if chaos['active_infrastructure_mutations'] else 'None'}

TASK:
1. Identify the root cause of the incident.
2. Determine if the failure originated in {evt['target_service']} or cascaded from a downstream dependency.
3. Recommend specific remediation actions (e.g. database pool resizing, circuit breaker activation, container restart).
"""
```

---

### D. Automated Pipeline Orchestration Commands

For continuous telemetry collection, log processing, and dataset packaging, use these commands:

| Step | Action | Command |
| :--- | :--- | :--- |
| **1** | Run background telemetry daemons | `python continuous_telemetry.py &`<br>`python frontend_data_sync.py &`<br>`python monitor_ram.py &` |
| **2** | Inject automated chaos scenario suite | `python chaos_scenarios.py --once` |
| **3** | Generate simulated user traffic & error load | `python load_generator.py --duration 90` |
| **4** | Cluster log events & compute priority scores | `python phase1_processor.py --reset-drain` |
| **5** | Package unified ML master dataset | `python package_ml_dataset.py` |
| **6** | Verify acceptance gates & quality score | `python validate.py` |
| **7** | Execute complete 24-test verification suite | `pytest -v tests/` |

---
*Document generated on August 15, 2026 for the Auto-SRE Platform.*
