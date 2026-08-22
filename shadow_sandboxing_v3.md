# SHADOW SANDBOXING & DYNAMIC ACTION EXECUTION — IMPLEMENTATION PLAN v3.0
## Repository: https://github.com/Sr-2006/Sandboxing (Branch: final_cf)
## Context: Auto-SRE Platform — Phase 4 (Sandbox & BIPS Engine)

> **Purpose of this document:** This is a context/reference document for an AI coding
> tool. It is not meant to be executed top-to-bottom in one pass. Break it into the
> numbered phases below and hand each phase to the coding tool separately, one at a
> time, with its own Prerequisites/Deliverables/Acceptance Criteria as the complete
> context for that unit of work. Do not paste the whole document into one coding
> session — large contexts cause AI tools to hallucinate or skip steps.
>
> **Relationship to prior versions:** This supersedes `shadow_sandboxing_v2_1.md`.
> Phases 1–7 below are the corrected v2.1 content (shadow infra, chaos namespace
> isolation, service shadow endpoints, traffic mirroring, sandboxed dataset paths,
> the severity-weighted validation gate, integration tests). **Phase 8 is new**: it
> wires the Tri-Debate RCA engine's output into the shadow sandbox so proposed fixes
> are actually executed and validated in a contained, cloned environment instead of
> only being scored for severity-prediction accuracy.

---

## 0. WHY PHASE 8 EXISTS (read this before touching Phase 8)

The Tri-Debate engine (Optimist / Critic / Fact-Checker / Orchestrator) produces a
JSON object per incident (see `debate` repo, branch `final_v1`, folder `output3b`)
containing a `technical_solution` with:

- `consensus_rc`, `primary_component`, `consensus_quality`
- `final_triage`, `final_stab`, `final_rca`
- `action_commands`: a list of **free-text, semi-structured strings** — not a fixed
  command grammar. Some look like shell commands, some look like Kubernetes verbs
  (`kubectl drain ...`), some are prose ("Perform data scrub on affected volumes").
  This will vary run to run because it is LLM-generated.
- `confidence`, `safety_violation`, `scoring_metadata` (includes `veto_reason`,
  `semantic_similarity`, `component_agreement`, `telemetry_hazard_detected`, etc.)
- An execution tier is derived per incident: `TIER_1_AUTONOMOUS_EXECUTION` or
  `TIER_2_SHADOW_SANDBOX` (see `full_22_case_validation_report.md` for the mapping
  already produced against the 12 sample cases).

**The problem:** the actual sandbox environment is Docker Compose (services named
`shadow-api-gateway`, `shadow-postgres-db`, etc. — see Phase 1), not Kubernetes.
`action_commands` cannot be run verbatim. They must be interpreted, mapped to a
small controlled set of real operations against `shadow-*` containers only, executed,
and the outcome measured — because these commands are dynamic/non-deterministic per
incident, the mapping layer must be a generic intent classifier + adapter, not a
per-case if/else.

**What Phase 8 delivers:** a dynamic harness that (a) ingests any Tri-Debate incident
JSON, (b) classifies `action_commands` into a bounded action vocabulary, (c) gates
execution on tier/confidence/`safety_violation`, (d) executes only inside
`shadow-net` reusing the namespace-safety code from Phase 2, (e) re-measures the
target container/service to see if the fault actually cleared, (f) extends the
Phase 6 validator to score remediation success (not just severity-prediction
accuracy), and (g) writes the verified outcome back into the Phase 2 ChromaDB
memory so future retrieval knows which fixes actually worked.

---

---

# PHASE 1: SHADOW INFRASTRUCTURE
## Goal: Deploy an isolated shadow stack with physical network separation and unified observability.

### Prerequisites
- Docker Compose v2+ installed
- `.env` file exists with all required variables
- Production stack is healthy

### Deliverables

#### 1.1 MODIFY: `docker-compose.yml` (Production Base)
Add dedicated networks and attach all production services. Also add the
**Prometheus service** (if missing) attached to both networks for unified scraping.

```yaml
version: "3.9"

networks:
  prod-net:
    driver: bridge
    internal: false

services:
  # ... existing services (postgres-db, redis, rabbitmq, api-gateway, auth-service,
  #     order-service, payment-service, jaeger, otel-collector) ...
  # ALL of the above must have:
  #   networks:
  #     - prod-net

  prometheus:
    image: prom/prometheus:v2.50.0
    container_name: prometheus
    networks:
      - prod-net
      - shadow-net   # CRITICAL: Prometheus must be on both networks to resolve shadow container names
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    mem_limit: 512M
    restart: "on-failure:3"

  jaeger:
    image: jaegertracing/all-in-one:1.57.0
    container_name: jaeger
    networks:
      - prod-net
      - shadow-net   # CRITICAL: Jaeger must be on both networks so shadow-otel-collector can resolve it
    ports:
      - "127.0.0.1:16686:16686"
      - "127.0.0.1:4317:4317"
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    mem_limit: 512M
    restart: "on-failure:3"
```

**Key insight:** By putting `jaeger` and `prometheus` on both `prod-net` and
`shadow-net`, they act as DNS-resolvable bridges without exposing either network's
other containers to each other. Static configs with container names only work when
the scraper/exporter is on the same network as its target.

#### 1.2 CREATE: `docker-compose.shadow.yml`
```yaml
version: "3.9"

networks:
  shadow-net:
    driver: bridge
    internal: false
  prod-net:
    external: true   # Reference the existing prod-net from docker-compose.yml

x-shadow-env: &shadow-env
  CHAOS_ENABLED: "true"
  CHAOS_SECRET: "${CHAOS_SECRET:?CHAOS_SECRET must be set}"
  SPRING_PROFILES_ACTIVE: "dev,shadow"
  JWT_SECRET: "${JWT_SECRET:?JWT_SECRET must be set}"
  INTERNAL_SERVICE_TOKEN: "${INTERNAL_SERVICE_TOKEN:?INTERNAL_SERVICE_TOKEN must be set}"
  JAVA_TOOL_OPTIONS: "-XX:MaxRAMPercentage=75"
  SHADOW_MODE: "true"
  PAYMENT_MOCK_ENABLED: "true"
  NOTIFICATION_MOCK_ENABLED: "true"
  SMTP_MOCK: "true"

services:
  shadow-postgres-db:
    image: postgres:16.2-alpine
    container_name: shadow-postgres-db
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=relational-database"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:15432:5432"]
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
    mem_limit: 512M
    cpus: "1.0"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 10s
      timeout: 5s
      retries: 5
    volumes:
      - ./postgres-init:/docker-entrypoint-initdb.d
    restart: "on-failure:3"

  shadow-redis:
    image: redis:7.2.4-alpine
    container_name: shadow-redis
    networks: [shadow-net]
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}"]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=cache"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:16379:6379"]
    environment:
      - REDIS_PASSWORD=${REDIS_PASSWORD}
    mem_limit: 256M
    cpus: "0.5"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "$$REDIS_PASSWORD", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    volumes:
      - shadow_redis_data:/data

  shadow-rabbitmq:
    image: rabbitmq:3.13.0-management-alpine
    container_name: shadow-rabbitmq
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=message-broker"
      - "ara.topology.sandbox=shadow"
    ports:
      - "127.0.0.1:15672:15672"
      - "127.0.0.1:25672:5672"
    environment:
      - RABBITMQ_DEFAULT_USER=${RABBITMQ_DEFAULT_USER}
      - RABBITMQ_DEFAULT_PASS=${RABBITMQ_DEFAULT_PASS}
    mem_limit: 512M
    cpus: "0.5"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    volumes:
      - shadow_rabbitmq_data:/var/lib/rabbitmq

  shadow-api-gateway:
    build: ./api-gateway
    container_name: shadow-api-gateway
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=gateway"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:9080:8080"]
    environment:
      <<: *shadow-env
      AUTH_SERVICE_URL: "http://shadow-auth-service:8081"
      ORDER_SERVICE_URL: "http://shadow-order-service:8082"
      PAYMENT_SERVICE_URL: "http://shadow-payment-service:8083"
    depends_on:
      shadow-auth-service: {condition: service_healthy}
      shadow-order-service: {condition: service_healthy}
      shadow-payment-service: {condition: service_healthy}
    mem_limit: 512M
    cpus: "1.0"
    restart: "on-failure:3"

  shadow-auth-service:
    build: ./auth-service
    container_name: shadow-auth-service
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=auth"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:9081:8081"]
    environment:
      <<: *shadow-env
      SPRING_DATASOURCE_URL: "jdbc:postgresql://shadow-postgres-db:5432/${POSTGRES_DB}"
    depends_on:
      shadow-postgres-db: {condition: service_healthy}
    mem_limit: 512M
    cpus: "1.0"
    restart: "on-failure:3"

  shadow-order-service:
    build: ./order-service
    container_name: shadow-order-service
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=order"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:9082:8082"]
    environment:
      <<: *shadow-env
    depends_on:
      shadow-auth-service: {condition: service_healthy}
    mem_limit: 512M
    cpus: "1.0"
    restart: "on-failure:3"

  shadow-payment-service:
    build: ./payment-service
    container_name: shadow-payment-service
    networks: [shadow-net]
    labels:
      - "ara.topology.group=shadow"
      - "ara.topology.role=payment"
      - "ara.topology.sandbox=shadow"
    ports: ["127.0.0.1:9083:8083"]
    environment:
      <<: *shadow-env
      PAYMENT_MOCK_ENABLED: "true"
      STRIPE_API_KEY: "sk_test_mock"
      PAYMENT_WEBHOOK_URL: "http://shadow-payment-service:8083/webhook/mock"
    depends_on:
      shadow-auth-service: {condition: service_healthy}
    mem_limit: 512M
    cpus: "1.0"
    restart: "on-failure:3"

  shadow-otel-collector:
    image: otel/opentelemetry-collector-contrib:0.96.0
    container_name: shadow-otel-collector
    networks: [shadow-net]
    labels:
      - "ara.topology.role=observability-collector"
      - "ara.topology.sandbox=shadow"
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./shadow/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    ports:
      - "127.0.0.1:24317:4317"
      - "127.0.0.1:24318:4318"
    depends_on: [jaeger]
    mem_limit: 256M
    cpus: "0.5"
    restart: "on-failure:3"

volumes:
  shadow_redis_data:
  shadow_rabbitmq_data:
```

#### 1.3 CREATE: `shadow/otel-collector-config.yaml`
```yaml
receivers:
  otlp:
    protocols:
      grpc: {endpoint: 0.0.0.0:4317}
      http: {endpoint: 0.0.0.0:4318}

processors:
  resource/shadow:
    attributes:
      - {key: sandbox.environment, value: shadow, action: upsert}
      - {key: service.namespace, value: shadow, action: upsert}
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317    # resolvable because jaeger is on shadow-net
    tls: {insecure: true}
  prometheus:
    endpoint: 0.0.0.0:8889

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [resource/shadow, batch]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      processors: [resource/shadow, batch]
      exporters: [prometheus]
```

#### 1.4 MODIFY: `prometheus.yml` (Unified Config)
Because Prometheus is now on both networks, static targets with container names
resolve correctly. No `docker_sd_configs` needed.

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'production-services'
    static_configs:
      - targets:
          - 'api-gateway:8080'
          - 'auth-service:8081'
          - 'order-service:8082'
          - 'payment-service:8083'
        labels: {sandbox: 'production'}

  - job_name: 'shadow-services'
    static_configs:
      - targets:
          - 'shadow-api-gateway:8080'
          - 'shadow-auth-service:8081'
          - 'shadow-order-service:8082'
          - 'shadow-payment-service:8083'
        labels: {sandbox: 'shadow'}

  - job_name: 'otel-collectors'
    static_configs:
      - targets: ['otel-collector:8889']
        labels: {sandbox: 'production'}
      - targets: ['shadow-otel-collector:8889']
        labels: {sandbox: 'shadow'}
```

#### 1.5 MODIFY: `utils.py`
Add helper functions at the bottom:
```python
def is_shadow_container(container_name: str) -> bool:
    return container_name.startswith("shadow-")

def get_sandbox_label(container_name: str) -> str:
    return "shadow" if is_shadow_container(container_name) else "production"
```

#### 1.6 CREATE: `run-shadow.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

export CHAOS_TARGET_NAMESPACE=shadow

UP_REQUIRED=(
  "shadow-postgres-db" "shadow-redis" "shadow-rabbitmq"
  "shadow-api-gateway" "shadow-auth-service" "shadow-order-service"
  "shadow-payment-service" "shadow-otel-collector"
)

cmd_up() {
  echo "[shadow] Starting shadow stack..."
  docker compose -f docker-compose.yml -f docker-compose.shadow.yml up -d --build
  echo "[shadow] Waiting 15s for health checks..."
  sleep 15

  printf "%-30s %-12s %-20s %-10s\n" "CONTAINER" "STATUS" "EXTERNAL_PORT" "HEALTH"
  for name in "${UP_REQUIRED[@]}"; do
    status=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
    port=$(docker inspect -f '{{range $p, $conf := .NetworkSettings.Ports}}{{if $conf}}{{printf "%s->%s " $p (index $conf 0).HostPort}}{{end}}{{end}}' "$name" 2>/dev/null || echo "none")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}N/A{{end}}' "$name" 2>/dev/null || echo "unknown")
    printf "%-30s %-12s %-20s %-10s\n" "$name" "$status" "$port" "$health"
  done

  for name in "${UP_REQUIRED[@]}"; do
    if [[ "$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)" != "running" ]]; then
      echo "[shadow] ERROR: $name is not running."
      exit 1
    fi
  done
  echo "[shadow] All required shadow containers are healthy."
}

cmd_down() {
  echo "[shadow] Tearing down shadow stack and ephemeral volumes..."
  docker compose -f docker-compose.yml -f docker-compose.shadow.yml down -v
  echo "[shadow] Shadow stack removed."
}

case "${1:-up}" in
  up) cmd_up ;;
  down) cmd_down ;;
  *) echo "Usage: $0 {up|down}"; exit 1 ;;
esac
```

### Acceptance Criteria
- [ ] `docker network ls` shows `prod-net` and `shadow-net`.
- [ ] `docker inspect jaeger | jq '.NetworkSettings.Networks | keys'` shows `["prod-net", "shadow-net"]`.
- [ ] `docker inspect prometheus | jq '.NetworkSettings.Networks | keys'` shows `["prod-net", "shadow-net"]`.
- [ ] `docker inspect shadow-api-gateway | jq '.NetworkSettings.Networks | keys'` shows `["shadow-net"]` ONLY.
- [ ] `docker inspect api-gateway | jq '.NetworkSettings.Networks | keys'` shows `["prod-net"]` ONLY.
- [ ] `docker compose -f docker-compose.yml -f docker-compose.shadow.yml config` parses without errors.
- [ ] `./run-shadow.sh up` starts all 8 shadow containers.
- [ ] `./run-shadow.sh down` removes all shadow containers and volumes.
- [ ] Shadow traces appear in Jaeger with `sandbox.environment=shadow` tag.
- [ ] Prometheus `/targets` shows both production and shadow scrape targets as UP.

---

---

# PHASE 2: CHAOS NAMESPACE ISOLATION & AUDIT
## Goal: Chaos injection can target `shadow` or `production` namespaces, never cross-contaminate, and every switch is audited.

### Prerequisites
- Phase 1 complete. Shadow stack is running.

### Deliverables

#### 2.1 MODIFY: `chaos_orchestrator.py`

**A. Namespace config + audit logging** (after existing imports):
```python
import getpass
TARGET_NAMESPACE = os.environ.get("CHAOS_TARGET_NAMESPACE", "production")
if TARGET_NAMESPACE not in ("production", "shadow"):
    raise ValueError(f"Invalid CHAOS_TARGET_NAMESPACE: {TARGET_NAMESPACE}. Must be 'production' or 'shadow'.")

AUDIT_LOG_PATH = project_path("frontend_data", "sandbox_audit.log")

def _append_audit_record(action: str, previous_ns: str = "", new_ns: str = "") -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target_namespace": TARGET_NAMESPACE,
        "previous_namespace": previous_ns,
        "new_namespace": new_ns,
        "user": getpass.getuser(),
        "pid": os.getpid(),
        "hostname": socket.gethostname()
    }
    with file_lock_context(AUDIT_LOG_PATH):
        history = read_json_file(AUDIT_LOG_PATH, [])
        if not isinstance(history, list):
            history = []
        history.append(entry)
        atomic_write_json(AUDIT_LOG_PATH, history)

_append_audit_record("orchestrator_startup")
```

**B. Hardened `get_container()`:**
```python
def get_container(target: str):
    if not client:
        raise docker.errors.DockerException("Docker client is not initialized")

    resolved_target = target
    if TARGET_NAMESPACE == "shadow" and not target.startswith("shadow-"):
        resolved_target = f"shadow-{target}"
    elif TARGET_NAMESPACE == "production" and target.startswith("shadow-"):
        raise ValueError(f"Production namespace cannot target shadow container: {target}")

    try:
        return client.containers.get(resolved_target)
    except docker.errors.NotFound:
        for c in client.containers.list(all=True):
            if resolved_target in c.name:
                if TARGET_NAMESPACE == "shadow" and not c.name.startswith("shadow-"):
                    continue
                if TARGET_NAMESPACE == "production" and c.name.startswith("shadow-"):
                    continue
                return c
        raise docker.errors.NotFound(f"Container '{resolved_target}' not found in namespace '{TARGET_NAMESPACE}'")
```

**C. Hardened `validate_namespace_safety()`:**
```python
def validate_namespace_safety(container) -> None:
    labels = container.labels or {}
    sandbox_label = labels.get("ara.topology.sandbox", "production")

    if TARGET_NAMESPACE == "shadow" and not container.name.startswith("shadow-"):
        raise RuntimeError(
            f"NAMESPACE CONTAMINATION BLOCKED: Container '{container.name}' "
            f"does not have 'shadow-' prefix but orchestrator is in shadow mode."
        )
    if TARGET_NAMESPACE == "production" and container.name.startswith("shadow-"):
        raise RuntimeError(
            f"NAMESPACE CONTAMINATION BLOCKED: Container '{container.name}' "
            f"has 'shadow-' prefix but orchestrator is in production mode."
        )
    if sandbox_label != TARGET_NAMESPACE:
        raise RuntimeError(
            f"NAMESPACE CONTAMINATION BLOCKED: Target container '{container.name}' "
            f"has sandbox label '{sandbox_label}' but orchestrator is in '{TARGET_NAMESPACE}' mode. "
            f"This fault has been aborted."
        )
```

**D. Modify `get_service_url()`:**
```python
def get_service_url(service_name: str) -> str:
    port = SERVICE_PORTS.get(service_name)
    if not port:
        for k, v in SERVICE_PORTS.items():
            if k in service_name:
                port = v
                break
    if not port:
        raise ValueError(f"Unknown service: {service_name}")

    if TARGET_NAMESPACE == "shadow":
        return f"http://shadow-{service_name}:{port}"

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect((TARGET_HOST, port))
        return f"http://{TARGET_HOST}:{port}"
    except (socket.error, OSError):
        return f"http://{service_name}:{port}"
    finally:
        try:
            s.close()
        except (socket.error, OSError):
            pass
```

**E.** Call `validate_namespace_safety()` after every `get_container()` in `apply_fault()` and `recover_fault()`.

**F. Add `network_partition` fault** — in `apply_fault`:
```python
elif fault_name == "network_partition":
    c = get_container(target)
    validate_namespace_safety(c)
    duration = int(params.get("duration_s", 30))
    if not (1 <= duration <= 300):
        raise ValueError(f"duration_s must be 1..300, got {duration}")
    c.exec_run(["tc", "qdisc", "add", "dev", "eth0", "root", "netem", "loss", "100%"])
    logger.info(f"Container {c.name} network partitioned for {duration}s")
```
— in `recover_fault`:
```python
elif fault_name == "network_partition":
    c = get_container(target)
    validate_namespace_safety(c)
    c.exec_run(["tc", "qdisc", "del", "dev", "eth0", "root"])
    logger.info(f"Container {c.name} network partition removed")
```

#### 2.2 MODIFY: `chaos_scenarios.py`

**A. CLI argument:**
```python
parser.add_argument("--sandbox", choices=["production", "shadow"], default="production",
                    help="Target sandbox namespace for chaos experiments")
```

**B. Pre-flight + audit log:**
```python
os.environ["CHAOS_TARGET_NAMESPACE"] = args.sandbox

if args.sandbox != "production":
    from chaos_orchestrator import _append_audit_record
    _append_audit_record("namespace_switch", previous_ns="production", new_ns=args.sandbox)

if args.sandbox == "shadow":
    required_shadow = ["shadow-api-gateway", "shadow-auth-service", "shadow-order-service", "shadow-payment-service"]
    running = [c.name for c in client.containers.list()]
    missing = [c for c in required_shadow if c not in running]
    if missing:
        logger.error(f"Shadow sandbox not ready. Missing containers: {missing}")
        sys.exit(1)
    logger.info("Shadow pre-flight check passed. All required shadow containers are running.")
```

**C. Dynamic service lists:**
```python
if args.sandbox == "shadow":
    CONTAINERS = [f"shadow-{s}" for s in ["api-gateway", "auth-service", "order-service", "payment-service", "postgres-db", "redis", "rabbitmq"]]
    HTTP_SERVICES = [f"shadow-{s}" for s in ["api-gateway", "auth-service", "order-service", "payment-service"]]
else:
    CONTAINERS = ["api-gateway", "auth-service", "order-service", "payment-service", "postgres-db", "redis", "rabbitmq"]
    HTTP_SERVICES = ["api-gateway", "auth-service", "order-service", "payment-service"]
```

**D. Add to catalog:**
```python
("network_partition", "container", lambda: {"duration_s": 30}),
```

#### 2.3 CREATE: `tests/test_shadow_namespace_safety.py`
```python
import pytest
import os
from unittest.mock import MagicMock

os.environ["CHAOS_TARGET_NAMESPACE"] = "shadow"
from chaos_orchestrator import get_container, validate_namespace_safety, TARGET_NAMESPACE

class MockContainer:
    def __init__(self, name, labels=None):
        self.name = name
        self.labels = labels or {}

class TestNamespaceIsolation:
    def test_shadow_prefixes_target(self, monkeypatch):
        mock_c = MagicMock()
        mock_c.name = "shadow-api-gateway"
        mock_c.labels = {"ara.topology.sandbox": "shadow"}
        monkeypatch.setattr("chaos_orchestrator.client.containers.get", lambda x: mock_c if x == "shadow-api-gateway" else (_ for _ in ()).throw(Exception))
        c = get_container("api-gateway")
        assert c.name == "shadow-api-gateway"

    def test_production_blocks_shadow_target(self, monkeypatch):
        monkeypatch.setenv("CHAOS_TARGET_NAMESPACE", "production")
        with pytest.raises(ValueError, match="Production namespace cannot target shadow"):
            get_container("shadow-api-gateway")

    def test_label_mismatch_blocks_fault(self):
        os.environ["CHAOS_TARGET_NAMESPACE"] = "shadow"
        bad = MockContainer("shadow-api-gateway", {"ara.topology.sandbox": "production"})
        with pytest.raises(RuntimeError, match="NAMESPACE CONTAMINATION BLOCKED"):
            validate_namespace_safety(bad)

    def test_audit_log_written(self):
        from chaos_orchestrator import AUDIT_LOG_PATH, read_json_file
        log = read_json_file(AUDIT_LOG_PATH, [])
        assert any(e["action"] == "orchestrator_startup" for e in log)
```

### Acceptance Criteria
- [ ] `CHAOS_TARGET_NAMESPACE=shadow python -c "from chaos_orchestrator import get_container; print(get_container('api-gateway').name)"` prints `shadow-api-gateway`.
- [ ] `CHAOS_TARGET_NAMESPACE=production python -c "from chaos_orchestrator import get_container; get_container('shadow-api-gateway')"` raises `ValueError`.
- [ ] `python chaos_scenarios.py --sandbox shadow --once` passes pre-flight when shadow stack is up.
- [ ] `python chaos_scenarios.py --sandbox shadow --once` fails pre-flight when shadow stack is down.
- [ ] `frontend_data/sandbox_audit.log` exists and contains entries with `action`, `user`, `pid`, `timestamp`.
- [ ] `pytest tests/test_shadow_namespace_safety.py` passes.

---

---

# PHASE 3: SERVICE SHADOW ENDPOINTS + AUTH BYPASS
## Goal: Shadow services expose status endpoints and bypass auth to eliminate 401 noise.

### Prerequisites
- Phase 1 complete. Phase 2 complete.

### Deliverables

#### 3.1 MODIFY: `api-gateway/src/main/resources/application.yml`
```yaml
---
spring:
  config:
    activate:
      on-profile: shadow
shadow:
  gateway:
    url: "${SHADOW_GATEWAY_URL:}"
    enabled: "${SHADOW_MIRROR_ENABLED:false}"
  auth-bypass: true
```

#### 3.2 MODIFY: `api-gateway/src/main/java/com/ecommerce/gateway/filter/JwtValidationFilter.java`
Add shadow bypass logic at the top of `filter()`:
```java
@Value("${shadow.auth-bypass:false}")
private boolean shadowAuthBypass;

@Override
public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
    if (shadowAuthBypass) {
        ServerHttpRequest request = exchange.getRequest();
        String correlationId = request.getHeaders().getFirst("X-Correlation-ID");
        if (correlationId == null || correlationId.isEmpty()) {
            correlationId = UUID.randomUUID().toString();
        }
        ServerHttpRequest modified = request.mutate()
            .header("X-Correlation-ID", correlationId)
            .header("X-Shadow-Auth-Bypassed", "true")
            .header("X-User-Id", "shadow-user")
            .build();
        return chain.filter(exchange.mutate().request(modified).build());
    }
    // ... existing JWT validation logic ...
}
```

#### 3.3 MODIFY: `api-gateway/src/main/java/com/ecommerce/gateway/config/GatewaySecurityConfig.java`
```java
.authorizeExchange(exchanges -> exchanges
    .pathMatchers("/chaos/shadow-status").permitAll()
    .pathMatchers("/chaos/**").denyAll()
    .anyExchange().permitAll()
)
```

#### 3.4 MODIFY: `api-gateway/src/main/java/com/ecommerce/gateway/chaos/ChaosController.java`
```java
@GetMapping("/shadow-status")
public ResponseEntity<Map<String, Object>> shadowStatus() {
    Map<String, Object> response = new HashMap<>();
    response.put("sandbox", true);
    response.put("chaos_enabled", true);
    response.put("service", "api-gateway");
    response.put("namespace", "shadow");
    return ResponseEntity.ok(response);
}
```

#### 3.5 MODIFY: `auth-service/src/main/java/com/ecommerce/auth/chaos/ChaosController.java`
Add identical `shadowStatus()` (change `service` to `"auth-service"`).

#### 3.6 MODIFY: `order-service/src/main/java/com/autosre/orderservice/chaos/ChaosController.java`
Add identical `shadowStatus()` (change `service` to `"order-service"`).

#### 3.7 MODIFY: `payment-service/src/main/java/com/autosre/paymentservice/chaos/ChaosController.java`
Add identical `shadowStatus()` (change `service` to `"payment-service"`).

#### 3.8 MODIFY: `payment-service/src/main/java/com/autosre/paymentservice/PaymentController.java`
```java
@Value("${PAYMENT_MOCK_ENABLED:false}")
private boolean paymentMockEnabled;

@PostMapping("/process")
public ResponseEntity<?> processPayment(@RequestHeader(value = "X-User-Id", required = false) String userId) {
    if (userId == null || userId.trim().isEmpty()) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Unauthorized: Missing X-User-Id header");
    }
    if (paymentMockEnabled) {
        Map<String, Object> mockResponse = new HashMap<>();
        mockResponse.put("status", "mock_success");
        mockResponse.put("transaction_id", "shadow-mock-" + UUID.randomUUID().toString());
        mockResponse.put("sandbox", true);
        mockResponse.put("user_id", userId);
        return ResponseEntity.ok(mockResponse);
    }
    return ResponseEntity.ok("Payment processed successfully");
}

@GetMapping("/shadow-status")
public ResponseEntity<Map<String, Object>> paymentShadowStatus() {
    Map<String, Object> status = new HashMap<>();
    status.put("sandbox", true);
    status.put("payment_mock", paymentMockEnabled);
    status.put("external_calls_blocked", paymentMockEnabled);
    status.put("service", "payment-service");
    return ResponseEntity.ok(status);
}
```

#### 3.9 MODIFY: `order-service/src/main/java/com/autosre/orderservice/config/InternalAuthFilter.java`
```java
@Value("${shadow.auth-bypass:false}")
private boolean shadowAuthBypass;

// In doFilterInternal():
if (shadowAuthBypass) {
    filterChain.doFilter(request, response);
    return;
}
```

#### 3.10 MODIFY: `payment-service/src/main/java/com/autosre/paymentservice/config/InternalAuthFilter.java`
Add identical shadow bypass logic.

### Acceptance Criteria
- [ ] `curl http://localhost:9082/chaos/shadow-status` returns `sandbox: true`.
- [ ] `curl http://localhost:9083/api/payments/shadow-status` returns `payment_mock: true`.
- [ ] `curl -X POST http://localhost:9083/api/payments/process -H "X-User-Id: test"` returns `mock_success`.
- [ ] Shadow gateway logs show `X-Shadow-Auth-Bypassed: true` header on mirrored requests.
- [ ] Shadow services do NOT emit 401 errors under mirrored traffic.
- [ ] `curl http://localhost:8082/chaos/shadow-status` (production) returns 200 without chaos token.

---

---

# PHASE 4: TRAFFIC MIRRORING + AUTO-FAILOVER
## Goal: Async fire-and-forget mirroring with 1MB body cap, GC-safe buffering, and automatic disable on shadow outage.

### Prerequisites
- Phase 1 (shadow stack runs). Phase 3 (shadow auth bypass works, no 401 noise).

### Deliverables

#### 4.1 CREATE: `api-gateway/src/main/java/com/ecommerce/gateway/filter/ShadowTrafficMirrorFilter.java`

Uses `DataBufferUtils.join()` instead of `collectList()` to fuse buffers into a
single `DataBuffer`, checks size, reads bytes, then **releases** immediately. This
avoids keeping a `List<DataBuffer>` in heap during the entire mirror operation.

```java
package com.ecommerce.gateway.filter;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Shadow Traffic Mirror Filter
 *
 * Asynchronously mirrors incoming production HTTP requests to the shadow gateway.
 *
 * DESIGN TRADE-OFFS (read before modifying):
 * - Body mirroring uses DataBufferUtils.join() which still buffers the FULL body
 *   into a single contiguous byte array. For true streaming (chunked transfer),
 *   use a sidecar proxy (Envoy/Linkerd) instead of in-app mirroring.
 * - The 1MB cap prevents OOM on large uploads but means large payloads are
 *   mirrored as headers-only.
 * - Fire-and-forget means shadow request failures are logged but never block production.
 * - AutoFailover: after N consecutive shadow failures within a rolling window, mirroring
 *   auto-disables until a manual reset or a successful health probe.
 */
@Component
public class ShadowTrafficMirrorFilter implements GlobalFilter, Ordered {

    @Value("${shadow.gateway.url:}")
    private String shadowGatewayUrl;

    @Value("${shadow.gateway.enabled:false}")
    private boolean mirrorEnabled;

    private static final int MAX_MIRROR_BODY_BYTES = 1_048_576; // 1MB
    private static final int FAILURE_THRESHOLD = 5;
    private static final Duration FAILURE_WINDOW = Duration.ofSeconds(60);

    private final AtomicBoolean autoDisabled = new AtomicBoolean(false);
    // consecutiveFailures / windowStart tracked with simple volatile counters or
    // an AtomicInteger + AtomicReference<Instant> pair — implementation detail,
    // not prescribed here; test must exercise the failure-threshold trip and reset.

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        if (!mirrorEnabled || shadowGatewayUrl.isBlank() || autoDisabled.get()) {
            return chain.filter(exchange);
        }

        ServerHttpRequest request = exchange.getRequest();

        return DataBufferUtils.join(request.getBody())
            .defaultIfEmpty(exchange.getResponse().bufferFactory().wrap(new byte[0]))
            .flatMap(dataBuffer -> {
                byte[] bodyBytes;
                try {
                    int readableByteCount = dataBuffer.readableByteCount();
                    if (readableByteCount > MAX_MIRROR_BODY_BYTES) {
                        // Mirror headers-only for oversized payloads
                        bodyBytes = new byte[0];
                    } else {
                        bodyBytes = new byte[readableByteCount];
                        dataBuffer.read(bodyBytes);
                    }
                } finally {
                    DataBufferUtils.release(dataBuffer);
                }

                mirrorToShadowAsync(request, bodyBytes);

                // Re-decorate request so downstream chain can still read the body
                ServerHttpRequest mutatedRequest = new ServerHttpRequestDecorator(request) {
                    @Override
                    public reactor.core.publisher.Flux<DataBuffer> getBody() {
                        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bodyBytes);
                        return reactor.core.publisher.Flux.just(buffer);
                    }
                };
                return chain.filter(exchange.mutate().request(mutatedRequest).build());
            });
    }

    private void mirrorToShadowAsync(ServerHttpRequest request, byte[] bodyBytes) {
        String path = request.getURI().getPath();
        String query = request.getURI().getQuery();
        String targetUri = shadowGatewayUrl + path + (query != null ? "?" + query : "");

        WebClient.create()
            .method(request.getMethod())
            .uri(targetUri)
            .headers(headers -> headers.addAll(request.getHeaders()))
            .header("X-Mirrored-From", "production")
            .bodyValue(bodyBytes)
            .retrieve()
            .toBodilessEntity()
            .timeout(Duration.ofSeconds(5))
            .doOnError(err -> handleMirrorFailure(err))
            .doOnSuccess(resp -> handleMirrorSuccess())
            .subscribe(
                resp -> {},
                err -> {} // already logged in handleMirrorFailure; never propagate to caller
            );
    }

    private void handleMirrorFailure(Throwable err) {
        // increment consecutiveFailures; if >= FAILURE_THRESHOLD within FAILURE_WINDOW,
        // autoDisabled.set(true) and log a WARN with reason "shadow mirror auto-disabled"
    }

    private void handleMirrorSuccess() {
        // reset consecutiveFailures counter
    }

    @Override
    public int getOrder() {
        return -1; // run early, before auth filters mutate the request further
    }
}
```

### Acceptance Criteria
- [ ] Requests to production gateway are mirrored to `shadow-api-gateway` when `SHADOW_MIRROR_ENABLED=true`.
- [ ] Production request latency is not measurably increased by mirroring (fire-and-forget).
- [ ] Payloads over 1MB are mirrored headers-only, not full body.
- [ ] `DataBuffer` is released in all code paths (no leak warnings in logs under `-Dio.netty.leakDetection.level=paranoid`).
- [ ] After `FAILURE_THRESHOLD` consecutive shadow failures within `FAILURE_WINDOW`, mirroring auto-disables and logs a warning.
- [ ] Shadow gateway logs incoming requests with `X-Mirrored-From: production` header.

---

---

# PHASE 5: SANDBOX-AWARE DATASET PATHS
## Goal: Shadow telemetry, Drain3 state, and the master dataset never collide with production files, and support concurrent shadow runs.

### Prerequisites
- Phase 1–4 complete.

### Deliverables

#### 5.1 MODIFY: `phase1_processor.py`

**A. Run-ID-scoped output paths:**
```python
import uuid
SHADOW_RUN_ID = os.environ.get("SHADOW_RUN_ID", str(uuid.uuid4())[:8])

def get_output_path(filename: str, sandbox: bool = False) -> str:
    prefix = f"shadow_{SHADOW_RUN_ID}_" if sandbox else ""
    return project_path("frontend_data", f"{prefix}{filename}")
```

**B. `--sandbox` CLI argument:**
```python
parser.add_argument("--sandbox", action="store_true", default=False,
                    help="Process shadow telemetry instead of production")
```

**C. Update all file paths to use `get_output_path()`:**
- `DRAIN3_STATE_FILE = get_output_path("drain3_state.bin", args.sandbox)`
- `VERSION_HEADER_FILE = get_output_path("drain3_version.meta", args.sandbox)`
- Chaos history read path: `get_output_path("chaos_history.json", args.sandbox)`
- Unified dataset write path: `get_output_path("unified_master_dataset.json", args.sandbox)`
- Raw telemetry read path: `get_output_path("raw_telemetry.json", args.sandbox)`

**D. Log the run ID:**
```python
logger.info(f"Phase 1 processor starting. Sandbox={args.sandbox}, RunID={SHADOW_RUN_ID}")
```

#### 5.2 MODIFY: `phase2_vector_memory.py`

```python
import os

def get_collection_name(sandbox: bool = False) -> str:
    return "sre_incident_memory_shadow" if sandbox else "sre_incident_memory"

def get_chroma_collection(sandbox: bool = False):
    name = get_collection_name(sandbox)
    return chroma_client.get_or_create_collection(name=name)

def index_unified_dataset(sandbox: bool = False):
    collection = get_chroma_collection(sandbox)
    dataset_path = os.path.join("frontend_data",
        f"shadow_{os.environ.get('SHADOW_RUN_ID', 'default')}_unified_master_dataset.json" if sandbox
        else "unified_master_dataset.json")
    # ... rest of function uses collection and dataset_path

def query_similar_incident(new_log_template, top_k=2, sandbox: bool = False):
    collection = get_chroma_collection(sandbox)
    query_vector = embedding_model.encode(new_log_template).tolist()
    results = collection.query(query_embeddings=[query_vector], n_results=top_k)
    return results
```

#### 5.3 MODIFY: `fastmcp_server.py`
```python
@mcp.tool()
def search_historical_incidents(error_log: str, top_k: int = 2, sandbox: str = "production") -> str:
    collection_name = get_collection_name(sandbox == "shadow")
    print(f"[MCP] Querying collection: {collection_name}")
    target_collection = chroma_client.get_collection(name=collection_name)
    query_vector = embedding_model.encode(error_log).tolist()
    results = target_collection.query(query_embeddings=[query_vector], n_results=top_k)
    # ... format results
```

### Acceptance Criteria
- [ ] `SHADOW_RUN_ID=abc123 python phase1_processor.py --sandbox` writes to `frontend_data/shadow_abc123_unified_master_dataset.json`.
- [ ] `python phase1_processor.py` (no sandbox) writes to `frontend_data/unified_master_dataset.json`.
- [ ] `python phase2_vector_memory.py` with `sandbox=True` creates collection `sre_incident_memory_shadow`.
- [ ] `python fastmcp_server.py` → `search_historical_incidents(..., sandbox="shadow")` queries the shadow collection.
- [ ] Multiple concurrent shadow runs use different state files (no collision).

---

---

# PHASE 6: VALIDATION GATE (SEVERITY-WEIGHTED)
## Goal: Compare predictions against shadow ground-truth with weighted accuracy, temporal scoring, and delta tracking.

### Prerequisites
- Phase 5 complete (shadow ML pipeline produces incidents).
- Phase 2 complete (chaos writes `shadow_chaos_history.json`).

### Deliverables

#### 6.1 CREATE: `shadow_ml_validator.py`
```python
#!/usr/bin/env python3
import os
import json
import sys
from datetime import datetime, timezone, timedelta
from utils import get_logger, project_path, atomic_write_json, read_json_file
from phase1_processor import process_telemetry_batch
from phase2_vector_memory import query_similar_incident

logger = get_logger("shadow_ml_validator")

SHADOW_TELEMETRY_PATH = project_path("frontend_data",
    f"shadow_{os.environ.get('SHADOW_RUN_ID', 'default')}_raw_telemetry.json")
SHADOW_CHAOS_HISTORY_PATH = project_path("frontend_data", "shadow_chaos_history.json")
VALIDATION_REPORT_PATH = project_path("frontend_data", "shadow_ml_validation_report.json")
HISTORY_SCORES_PATH = project_path("frontend_data", "shadow_validation_history.json")

SEVERITY_THRESHOLDS = {
    "CRITICAL": 1.00,
    "HIGH":     0.95,
    "MEDIUM":   0.85,
    "LOW":      0.70,
}

def load_shadow_ground_truth(scenario_id: str) -> dict:
    history = read_json_file(SHADOW_CHAOS_HISTORY_PATH, [])
    for ev in history:
        if ev.get("scenario_id") == scenario_id:
            return {
                "service_restarted": ev.get("target") in [c.name for c in client.containers.list()] if 'client' in globals() else False,
                "cascade_failures": 0,
                "slo_violated": ev.get("duration_s", 0) > 5.0,
                "recovery_time_ms": float(ev.get("duration_s", 0)) * 1000,
                "status": "ok"
            }
    return {"status": "no_ground_truth"}

def derive_ground_truth_severity(gt: dict) -> str:
    if gt.get("slo_violated") or gt.get("service_restarted"):
        return "CRITICAL"
    if gt.get("cascade_failures", 0) > 0:
        return "HIGH"
    return "LOW"

def validate_prediction(incident: dict, ground_truth: dict) -> dict:
    if ground_truth.get("status") == "no_ground_truth":
        return {"status": "no_ground_truth", "safe": False, "drift": 1.0}

    predicted = incident.get("severity", "LOW")
    gt_sev = derive_ground_truth_severity(ground_truth)
    recovery_ms = ground_truth.get("recovery_time_ms", 999999)
    self_healed = not ground_truth.get("slo_violated") and recovery_ms < 5000

    severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    pred_idx = severity_order.get(predicted, 0)
    gt_idx = severity_order.get(gt_sev, 0)
    diff = abs(pred_idx - gt_idx)

    if diff == 0:
        return {"status": "validated", "safe": True, "drift": 0.1}
    elif diff == 1 and self_healed:
        return {"status": "validated_partial", "safe": True, "drift": 0.3}
    elif predicted == "CRITICAL" and gt_sev in ("LOW", "MEDIUM"):
        return {"status": "over_prediction", "safe": False, "drift": 0.8}
    elif predicted == "LOW" and gt_sev in ("HIGH", "CRITICAL"):
        return {"status": "under_prediction", "safe": False, "drift": 0.9}
    else:
        return {"status": "mismatch", "safe": False, "drift": 0.5}

def run_shadow_validation() -> bool:
    if not os.path.exists(SHADOW_TELEMETRY_PATH) or os.path.getsize(SHADOW_TELEMETRY_PATH) == 0:
        logger.error(f"Shadow telemetry not found: {SHADOW_TELEMETRY_PATH}")
        return False

    incidents = process_telemetry_batch(SHADOW_TELEMETRY_PATH, sandbox_mode=True)
    if not incidents:
        logger.warning("No incidents generated from shadow telemetry.")
        return False

    results = []
    severity_counts = {"CRITICAL": {"safe": 0, "total": 0}, "HIGH": {"safe": 0, "total": 0},
                       "MEDIUM": {"safe": 0, "total": 0}, "LOW": {"safe": 0, "total": 0}}

    for inc in incidents:
        gt = load_shadow_ground_truth(inc.get("scenario_id", ""))
        v = validate_prediction(inc, gt)
        results.append({
            "incident_id": inc.get("incident_id"),
            "predicted": inc.get("severity"),
            "ground_truth": derive_ground_truth_severity(gt),
            "validation": v
        })
        sev = inc.get("severity", "LOW")
        severity_counts[sev]["total"] += 1
        if v["safe"]:
            severity_counts[sev]["safe"] += 1

    per_severity = {}
    gate_passed = True
    for sev, counts in severity_counts.items():
        if counts["total"] > 0:
            ratio = counts["safe"] / counts["total"]
            threshold = SEVERITY_THRESHOLDS[sev]
            passed = ratio >= threshold
            per_severity[sev] = {"ratio": ratio, "threshold": threshold, "passed": passed}
            if not passed:
                gate_passed = False

    overall_safe = sum(1 for r in results if r["validation"]["safe"]) / len(results)

    history = read_json_file(HISTORY_SCORES_PATH, [])
    delta = None
    if history:
        last = history[-1]
        delta = overall_safe - last.get("overall_safe", 0)
        if delta < -0.05:
            logger.warning(f"Regression detected: score dropped by {abs(delta):.1%} from last run.")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_safe": overall_safe,
        "per_severity": per_severity,
        "promotion_gate": gate_passed,
        "total_incidents": len(results),
        "delta_from_last": delta,
        "details": results
    }

    atomic_write_json(VALIDATION_REPORT_PATH, report)

    history.append({"timestamp": report["timestamp"], "overall_safe": overall_safe, "gate_passed": gate_passed})
    if len(history) > 30:
        history = history[-30:]
    atomic_write_json(HISTORY_SCORES_PATH, history)

    logger.info(f"Shadow validation: overall={overall_safe:.2%}, gate={gate_passed}")
    for sev, stats in per_severity.items():
        logger.info(f"  {sev}: {stats['ratio']:.2%} (threshold: {stats['threshold']:.0%}, passed={stats['passed']})")

    return gate_passed

if __name__ == "__main__":
    gate_passed = run_shadow_validation()
    sys.exit(0 if gate_passed else 1)
```

### Acceptance Criteria
- [ ] `python shadow_ml_validator.py` exits `0` when mock data has 100% CRITICAL accuracy.
- [ ] Exits `1` when CRITICAL accuracy <100% even if overall is >95%.
- [ ] Report contains `per_severity` with `ratio`, `threshold`, `passed` for each bucket.
- [ ] `delta_from_last` populated when history exists.
- [ ] `frontend_data/shadow_validation_history.json` retains last 30 runs.
- [ ] Uses `atomic_write_json()` for all file writes.

---

---

# PHASE 7: INTEGRATION TESTS & DASHBOARDS
## Goal: End-to-end validation and unified observability UI.

### Prerequisites
- Phases 1–6 complete and individually passing.

### Deliverables

#### 7.1 CREATE: `tests/test_shadow_sandboxing.py`
```python
import pytest
import subprocess
import time
import requests
import os
import json

SHADOW_BASE = "http://localhost:9080"
PROD_BASE = "http://localhost:8080"

class TestShadowSandboxing:
    @classmethod
    def setup_class(cls):
        subprocess.run(["./run-shadow.sh", "up"], check=True)
        time.sleep(5)

    @classmethod
    def teardown_class(cls):
        subprocess.run(["./run-shadow.sh", "down"], check=True)

    def test_shadow_stack_deploys(self):
        r = requests.get(f"{SHADOW_BASE}/chaos/shadow-status", timeout=5)
        assert r.status_code == 200
        assert r.json()["sandbox"] is True

    def test_shadow_payment_mock(self):
        r = requests.post(f"http://localhost:9083/api/payments/process",
                         headers={"X-User-Id": "test"}, timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "mock_success"

    def test_chaos_namespace_isolation(self):
        os.environ["CHAOS_TARGET_NAMESPACE"] = "shadow"
        from chaos_orchestrator import get_container
        c = get_container("api-gateway")
        assert c.name == "shadow-api-gateway"

    def test_traffic_mirror_reaches_shadow(self):
        pytest.skip("Requires manual mirror enablement")

    def test_shadow_ml_validator_gate(self):
        from shadow_ml_validator import run_shadow_validation
        result = run_shadow_validation()
        assert isinstance(result, bool)

    def test_jaeger_tagging(self):
        requests.get(f"{SHADOW_BASE}/chaos/shadow-status", timeout=5)
        time.sleep(2)
        jaeger_url = "http://localhost:16686/api/traces?service=shadow-api-gateway&limit=1"
        r = requests.get(jaeger_url, timeout=5)
        assert r.status_code == 200
        traces = r.json().get("data", [])
        if traces:
            tags = {t["key"]: t["value"] for t in traces[0]["spans"][0]["tags"]}
            assert tags.get("sandbox.environment") == "shadow"
```

#### 7.2 MODIFY: `grafana/provisioning/dashboards/system-overview.json`
Add a `sandbox` custom variable:
```json
{
  "name": "sandbox",
  "type": "custom",
  "query": "production,shadow",
  "current": {"text": "production", "value": "production"},
  "hide": 0,
  "includeAll": false,
  "multi": false
}
```
Update all PromQL queries to include `sandbox="$sandbox"`. Add shadow-specific row
panels that are hidden by default when `sandbox=production`.

### Acceptance Criteria
- [ ] `pytest tests/test_shadow_sandboxing.py -v` passes (skip mirror test if not configured).
- [ ] `./run-shadow.sh up && ./run-shadow.sh down` works without manual intervention.
- [ ] Grafana dashboard variable `sandbox` switches between production and shadow metrics.
- [ ] Jaeger shows traces with `sandbox.environment=shadow` tag.

---

---

# PHASE 8 (NEW): DYNAMIC ACTION EXECUTION & VALIDATION HARNESS
## Goal: Ingest Tri-Debate RCA output, translate its free-text `action_commands` into a
## bounded set of real operations, execute them ONLY against `shadow-*` containers
## under existing namespace-safety controls, measure whether the fault actually
## cleared, and feed the verified outcome back into ChromaDB memory.

### Prerequisites
- Phases 1–7 complete (shadow stack, namespace isolation, sandbox dataset paths,
  and the severity validation gate all exist and pass).
- Tri-Debate engine output available (JSON files matching the schema in
  `debate` repo, branch `final_v1`, folder `output3b` — see §0 above for schema notes).

### Design Constraints (do not violate)
1. **Never execute against non-`shadow-*` containers.** Reuse
   `chaos_orchestrator.get_container()` and `validate_namespace_safety()` from
   Phase 2 verbatim — do not re-implement container resolution.
2. **`action_commands` are not a fixed grammar.** Build a classifier/adapter, not
   per-case string matching. New incident types must not require new code, only
   new vocabulary/pattern entries in a data file.
3. **Respect the tier & safety flags already computed by the debate engine:**
   - `safety_violation: true` → never execute. Log and route to
     `TIER_2_SHADOW_SANDBOX` / human-review queue regardless of tier.
   - `TIER_1_AUTONOMOUS_EXECUTION` + no violation + `confidence >= 85` → eligible
     for automatic execution in shadow.
   - `TIER_2_SHADOW_SANDBOX` (the majority of cases per the sample validation
     report) → execute in shadow, but flag output as "simulated, pending review"
     rather than promotable to production automatically.
4. **Fail closed.** If the adapter cannot confidently classify an `action_command`
   into the known vocabulary, do not guess — log it as `UNMAPPED_ACTION` and skip
   execution for that command, continuing with any commands that were mapped.

### Deliverables

#### 8.1 CREATE: `frontend_data/action_vocabulary.json`
A data file (not code) mapping intent → Docker-level operation. This is the
"controlled vocabulary" the adapter classifies free text into. Include at minimum:
```json
{
  "restart_service": {"docker_op": "restart", "keywords": ["restart", "reboot service", "cycle the"]},
  "reset_config_param": {"docker_op": "exec_config_patch", "keywords": ["set max_connections", "adjust", "reduce", "reset connection pool", "reset limit"]},
  "clear_cache": {"docker_op": "exec_flush", "keywords": ["clear cache", "flush", "evict"]},
  "network_isolate": {"docker_op": "network_partition", "keywords": ["drain", "cordon", "isolate", "quarantine"]},
  "scale_resource": {"docker_op": "update_resources", "keywords": ["scale", "increase memory", "increase cpu"]},
  "rotate_cert": {"docker_op": "exec_cert_rotate", "keywords": ["renew cert", "rotate tls", "reissue certificate"]},
  "noop_monitor": {"docker_op": "noop", "keywords": ["monitor", "review logs", "verify", "check"]}
}
```
This file is intentionally editable without touching Python — new intents can be
added by appending entries.

#### 8.2 CREATE: `action_adapter.py`
Translates a Tri-Debate incident JSON's `action_commands` (list of free-text
strings) into a list of `(intent, target_service, params)` tuples using the
vocabulary in `action_vocabulary.json`. Responsibilities:
- Load vocabulary once at import.
- For each command string, do keyword/intent matching (simple containment
  matching is acceptable for v1; leave a documented TODO for swapping in an
  embedding-similarity classifier later using the same sentence-embedding model
  already used in `phase2_vector_memory.py`, for consistency).
- Extract `target_service` from the incident's `problem` field (it already
  contains `Target Service: \`postgres-db\`` etc. — parse this, don't re-derive).
- Return `UNMAPPED_ACTION` for anything below a confidence threshold instead of
  forcing a match.
- Pure function, unit-testable without Docker running.

8.2 CREATE: action_adapter.py

Translates a Tri-Debate incident JSON's action_commands (list of free-text strings) into a list of (intent, target_service, params) tuples using the vocabulary in action_vocabulary.json. Responsibilities:

Load vocabulary once at import.
Use simple keyword containment matching against action_vocabulary.json for v1. Do NOT implement embeddings/similarity search yet. Add a # TODO: Upgrade to embedding similarity using phase2_vector_memory.embedding_model comment instead. Keyword matching is sufficient for the current 12-case sample set and keeps the adapter deterministic/testable.
Matching must be deterministic: iterate intents in the order they appear in action_vocabulary.json and take the first intent whose keyword list contains a match; do not score/rank multiple candidate matches.
Extract target_service from the incident's problem field (it already contains Target Service: \postgres-db`` etc. — parse this, don't re-derive).
Return UNMAPPED_ACTION when no keyword matches, instead of forcing a match.
Pure function, unit-testable without Docker running.

#### 8.4 Outcome Record Schema
Every execution run appends one record like this to
`frontend_data/dynamic_execution_outcomes.json`:
```json
{
  "incident_id": "case_11_pg_connection_exhaustion",
  "timestamp": "2026-08-22T10:00:00Z",
  "tier": "TIER_2_SHADOW_SANDBOX",
  "gate_decision": "EXECUTED | BLOCKED_SAFETY_VIOLATION | BLOCKED_UNMAPPED",
  "mapped_actions": [
    {"raw_command": "...", "intent": "reset_config_param", "target": "shadow-postgres-db", "mapped": true}
  ],
  "unmapped_actions": ["..."],
  "execution_results": [
    {"intent": "reset_config_param", "success": true, "docker_error": null}
  ],
  "pre_state": {"active_connections": 100, "container_status": "running"},
  "post_state": {"active_connections": 42, "container_status": "running"},
  "fault_cleared": true,
  "notes": "confidence 63%, consensus_quality HIGH, tier 2 => flagged for human review before prod promotion"
}
```

#### 8.5 MODIFY: `phase2_vector_memory.py`
Add a feedback-write function so verified outcomes strengthen future retrieval:
```python
def record_remediation_outcome(incident_fingerprint: str, outcome: dict, sandbox: bool = True) -> None:
    """
    Store whether a proposed fix actually cleared the fault, keyed to the same
    (target_service, log_cluster_template) fingerprint used for indexing.
    Called by dynamic_execution_harness.py after each shadow execution.
    """
    collection = get_chroma_collection(sandbox)
    collection.update(
        ids=[incident_fingerprint],
        metadatas=[{"last_remediation_verified": outcome["fault_cleared"],
                    "last_remediation_timestamp": outcome["timestamp"]}]
    )
```

#### 8.6 EXTEND: `shadow_ml_validator.py`
Add a second gate function alongside the existing severity-accuracy gate — do not
replace the existing function, add a new one:
```python
def run_remediation_validation(outcomes_path: str = None) -> bool:
    """
    Reads frontend_data/dynamic_execution_outcomes.json and computes what fraction
    of EXECUTED (non-blocked) incidents had fault_cleared == true.
    Applies the same SEVERITY_THRESHOLDS gate logic, keyed by incident severity
    (pulled from the original incident's `problem` field), not by prediction
    accuracy. This is remediation-success rate, a distinct metric from the
    existing severity-prediction accuracy in run_shadow_validation().
    """
```

#### 8.7 CREATE: `tests/test_action_adapter.py`
Unit tests using the actual sample files from `debate/output3b` (vendor a copy or
fixture subset into `tests/fixtures/tri_debate_samples/`):
- Test that `case_11_pg_connection_exhaustion.json`'s action commands map to
  `reset_config_param` targeting `postgres-db`.
- Test that `case_22_storage_corruption_nuclear.json` (which has
  `safety_violation: true` in the sample data) never reaches the adapter — the
  harness gate stops it first.
- Test that a deliberately nonsense action string returns `UNMAPPED_ACTION` rather
  than a false-positive match.

#### 8.8 CREATE: `tests/test_dynamic_execution_harness.py`
- Test the full gate flow with `safety_violation: true` → outcome record shows
  `gate_decision: BLOCKED_SAFETY_VIOLATION`, no Docker calls made (mock the Docker
  client).
- Test that `dynamic_execution_harness.py` never calls `get_container()` without
  `CHAOS_TARGET_NAMESPACE=shadow` set first.
- Test that a single mapped-action Docker exception doesn't abort a batch run over
  multiple incidents.

### Acceptance Criteria
- [ ] `python dynamic_execution_harness.py --input debate_output/case_11_pg_connection_exhaustion.json` produces an outcome record in `frontend_data/dynamic_execution_outcomes.json`.
- [ ] `python dynamic_execution_harness.py --input-dir debate_output/` batch-processes all 12 sample cases without one failure aborting the run.
- [ ] The `case_22_storage_corruption_nuclear.json` sample (has `safety_violation: true`) always produces `gate_decision: BLOCKED_SAFETY_VIOLATION` and triggers zero Docker SDK calls.
- [ ] Every executed action targets a container whose name starts with `shadow-` — verified by asserting on `validate_namespace_safety()` being called before every Docker mutation.
- [ ] `pytest tests/test_action_adapter.py tests/test_dynamic_execution_harness.py -v` passes.
- [ ] `python shadow_ml_validator.py --remediation` (or equivalent CLI flag) runs `run_remediation_validation()` and exits 0/1 on the remediation-success gate.
- [ ] ChromaDB shadow collection entries show updated `last_remediation_verified` metadata after a harness run.
- [ ] An `UNMAPPED_ACTION` command never causes an unhandled exception — it's logged and skipped.

---

---

## APPENDIX: QUICK REFERENCE

```bash
# Phase 1
./run-shadow.sh up
./run-shadow.sh down

# Phase 2
CHAOS_TARGET_NAMESPACE=shadow python chaos_scenarios.py --sandbox shadow --once

# Phase 4
# Set SHADOW_MIRROR_ENABLED=true SHADOW_GATEWAY_URL=http://localhost:9080
curl http://localhost:8080/api/v1/orders          # production
curl http://localhost:9080/api/v1/orders          # shadow (mirrored)

# Phase 5
SHADOW_RUN_ID=run42 python phase1_processor.py --sandbox

# Phase 6
python shadow_ml_validator.py                     # exit 0 = promote, 1 = block
cat frontend_data/shadow_ml_validation_report.json

# Phase 7
pytest tests/test_shadow_sandboxing.py -v

# Phase 8
python dynamic_execution_harness.py --input-dir debate_output/
cat frontend_data/dynamic_execution_outcomes.json
python shadow_ml_validator.py --remediation
```

---

## FILE STRUCTURE (Final v3.0)

```
Sandboxing/
├── docker-compose.yml                  # MODIFIED: prod-net + prometheus service + jaeger dual-net
├── docker-compose.shadow.yml           # NEW: shadow-net, references prod-net as external
├── run.sh                              # existing
├── run-shadow.sh                       # NEW
│
├── chaos_orchestrator.py               # MODIFIED: namespace safety + audit
├── chaos_scenarios.py                  # MODIFIED: --sandbox CLI
├── chaos_watchdog.py                   # untouched
│
├── phase1_processor.py                 # MODIFIED: UUID state dirs, --sandbox
├── phase2_vector_memory.py             # MODIFIED: collection factory + remediation feedback (8.5)
├── fastmcp_server.py                   # MODIFIED: sandbox param
├── shadow_ml_validator.py              # NEW: weighted validation gate + remediation gate (8.6)
│
├── action_vocabulary.json              # NEW (Phase 8): intent classification data
├── action_adapter.py                   # NEW (Phase 8): free-text → intent translator
├── dynamic_execution_harness.py        # NEW (Phase 8): orchestration entrypoint
│
├── continuous_telemetry.py             # untouched
├── simulate_full_telemetry.py          # untouched
├── utils.py                            # MODIFIED: helper functions
│
├── shadow/                             # NEW
│   ├── otel-collector-config.yaml      # NEW: exports to jaeger:4317 (resolvable via shadow-net)
│   └── README.md                       # NEW
│
├── prometheus.yml                      # MODIFIED: unified static targets (prometheus on both nets)
│
├── api-gateway/                        # MODIFIED: mirror filter (DataBufferUtils), auth bypass
├── auth-service/                       # MODIFIED: shadow endpoints
├── order-service/                      # MODIFIED: shadow endpoints
├── payment-service/                    # MODIFIED: shadow endpoints + mock
│
├── tests/
│   ├── test_shadow_namespace_safety.py # NEW
│   ├── test_shadow_sandboxing.py       # NEW
│   ├── test_action_adapter.py          # NEW (Phase 8)
│   ├── test_dynamic_execution_harness.py # NEW (Phase 8)
│   └── fixtures/tri_debate_samples/    # NEW (Phase 8): vendored sample debate JSONs
│
├── frontend_data/
│   ├── sandbox_audit.log               # NEW (generated)
│   ├── shadow_chaos_history.json       # NEW (generated)
│   ├── shadow_ml_validation_report.json# NEW (generated)
│   ├── shadow_validation_history.json  # NEW (generated)
│   ├── dynamic_execution_outcomes.json # NEW (generated, Phase 8)
│   └── shadow_{RUNID}_*                # NEW (generated)
│
├── grafana/provisioning/dashboards/    # MODIFIED: sandbox variable
├── loki/                               # untouched
├── federation/                         # untouched
└── postgres-init/                      # untouched
```

---

END OF V3.0
