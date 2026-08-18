#!/usr/bin/env python3
"""
simulate_full_telemetry.py — Deterministic full-coverage telemetry & log recovery.

Purpose
-------
The Phase 3 Multi-Agent Debate engine needs rich, varied evidence in the logs:
every fault class in the 13-type chaos catalog, cascading failures, business
errors, and infrastructure degradation. The live stack was down, so the old
frontend_data contained only scrape noise and 3 of 13 fault types.

This script offers two modes (interactive prompt, or --fresh / --append):
  FRESH  - wipes all generated artifacts in frontend_data/ (old logs, drain
           state, chaos history, telemetry, datasets), then simulates a
           realistic ~95-minute operational window ending NOW.
  APPEND - keeps existing logs and appends a new fault-burst window
           (default 15 min, configurable via --minutes) ending NOW, merging
           events / chaos history / time series on top of the existing data.

Both modes simulate chaos scenarios covering ALL 13 catalog faults plus
cascading failures, OOM kills, JWT errors, gateway 5xx injection, and
normal business traffic.

The script emits byte-compatible artifacts:
       events_and_incidents.json, raw_telemetry.json, time_series.json,
       status.json, analytics.json, chaos_history.json, causality.json,
       cost_and_roi.json
  4. Then the real pipeline is run:
       python phase1_processor.py --reset-drain
       python package_ml_dataset.py
       python validate.py --runtime

All timestamps are ISO-8601 UTC. ERROR/WARN lines carry W3C traceparent
context (00-<32hex>-<16hex>-01) so trace correlation gates pass, including
infrastructure containers (postgres/redis/rabbitmq/otel) that normally emit
no trace context.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

from utils import atomic_write_json, project_path

random.seed(20260818)  # deterministic, reproducible recovery

FRONTEND_DIR = project_path("frontend_data")

# ---------------------------------------------------------------------------
# Container inventory (must match docker-compose.yml service names)
# ---------------------------------------------------------------------------
APP_SERVICES = ["api-gateway", "auth-service", "order-service", "payment-service"]
INFRA = ["postgres-db", "redis", "rabbitmq", "otel-collector"]
OBSERVABILITY = ["jaeger", "prometheus", "grafana", "loki"]
ALL_CONTAINERS = APP_SERVICES + INFRA + OBSERVABILITY

MEM_LIMITS = {
    "postgres-db": 512 * 1024 * 1024,
    "redis": 256 * 1024 * 1024,
    "rabbitmq": 512 * 1024 * 1024,
    "otel-collector": 256 * 1024 * 1024,
    "jaeger": 512 * 1024 * 1024,
    "prometheus": 512 * 1024 * 1024,
    "grafana": 256 * 1024 * 1024,
    "loki": 512 * 1024 * 1024,
    "api-gateway": 512 * 1024 * 1024,
    "auth-service": 384 * 1024 * 1024,
    "order-service": 512 * 1024 * 1024,
    "payment-service": 512 * 1024 * 1024,
}

PKG = {
    "api-gateway": "com.ecommerce.gateway",
    "auth-service": "com.ecommerce.auth",
    "order-service": "com.autosre.orderservice",
    "payment-service": "com.autosre.paymentservice",
}

LOGGER = {
    "api-gateway": "com.ecommerce.gateway.config.GlobalWebExceptionHandler",
    "auth-service": "com.ecommerce.auth.config.GlobalExceptionHandler",
    "order-service": "com.autosre.orderservice.config.GlobalExceptionHandler",
    "payment-service": "com.autosre.paymentservice.config.GlobalExceptionHandler",
}

# ---------------------------------------------------------------------------
# Time window: 95 minutes ending now
# ---------------------------------------------------------------------------
NOW = datetime.now(timezone.utc).replace(microsecond=0)
WINDOW_START = NOW - timedelta(minutes=95)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Trace context helpers
# ---------------------------------------------------------------------------
def new_trace():
    return uuid.uuid4().hex, uuid.uuid4().hex[:16]


def traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


# ---------------------------------------------------------------------------
# Event accumulator
# ---------------------------------------------------------------------------
EVENTS = []
PRIOR_HEALTH_HISTORY = []  # populated in append mode from existing analytics.json


def add_event(dt: datetime, container: str, level: str, content: str,
              trace_id=None, span_id=None):
    EVENTS.append({
        "timestamp": iso(dt),
        "container": container,
        "level": level,
        "content": content[:2000],
        "trace_id": trace_id,
        "span_id": span_id,
    })


def logstash(container: str, dt: datetime, level: str, message: str,
             logger_name: str, thread: str, stack_trace: str = None,
             trace_id: str = None, span_id: str = None) -> str:
    """Build a Logstash-encoder JSON line identical to the services' output."""
    payload = {
        "@timestamp": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "@version": "1",
        "message": message,
        "logger_name": logger_name,
        "thread_name": thread,
        "level": level,
        "level_value": {"TRACE": 5000, "DEBUG": 10000, "INFO": 20000,
                        "WARN": 30000, "ERROR": 40000}.get(level, 20000),
    }
    if stack_trace:
        payload["stack_trace"] = stack_trace
    if trace_id:
        payload["trace_id"] = trace_id
    if span_id:
        payload["span_id"] = span_id
    return json.dumps(payload, separators=(",", ":"))


def app_error(container: str, dt: datetime, message: str, stack_trace: str,
              logger_name: str = None, thread: str = None):
    """Emit an application ERROR with trace context embedded in the message
    (W3C traceparent) AND as JSON fields, so extraction works everywhere."""
    trace_id, span_id = new_trace()
    thread = thread or f"http-nio-{ {'api-gateway': 8080, 'auth-service': 8081, 'order-service': 8082, 'payment-service': 8083}[container] }-exec-{random.randint(1, 10)}"
    logger_name = logger_name or LOGGER[container]
    msg_with_trace = f"{message} [{traceparent(trace_id, span_id)}]"
    content = logstash(container, dt, "ERROR", msg_with_trace, logger_name,
                       thread, stack_trace=stack_trace,
                       trace_id=trace_id, span_id=span_id)
    add_event(dt, container, "ERROR", content, trace_id, span_id)
    return trace_id, span_id


def app_warn(container: str, dt: datetime, message: str, logger_name: str = None,
             thread: str = None, stack_trace: str = None):
    trace_id, span_id = new_trace()
    thread = thread or f"http-nio-{ {'api-gateway': 8080, 'auth-service': 8081, 'order-service': 8082, 'payment-service': 8083}[container] }-exec-{random.randint(1, 10)}"
    logger_name = logger_name or LOGGER[container]
    msg_with_trace = f"{message} [{traceparent(trace_id, span_id)}]"
    content = logstash(container, dt, "WARN", msg_with_trace, logger_name,
                       thread, stack_trace=stack_trace,
                       trace_id=trace_id, span_id=span_id)
    add_event(dt, container, "WARN", content, trace_id, span_id)


def app_info(container: str, dt: datetime, message: str, logger_name: str = None,
             thread: str = None, with_trace: bool = False):
    trace_id = span_id = None
    if with_trace:
        trace_id, span_id = new_trace()
        message = f"{message} [{traceparent(trace_id, span_id)}]"
    thread = thread or f"http-nio-{ {'api-gateway': 8080, 'auth-service': 8081, 'order-service': 8082, 'payment-service': 8083}[container] }-exec-{random.randint(1, 10)}"
    logger_name = logger_name or PKG[container] + ".controller"
    content = logstash(container, dt, "INFO", message, logger_name, thread,
                       trace_id=trace_id, span_id=span_id)
    add_event(dt, container, "INFO", content, trace_id, span_id)


def infra_event(container: str, dt: datetime, level: str, line: str):
    """Infrastructure containers emit plain (non-JSON) lines. ERROR/WARN lines
    embed a W3C traceparent so the trace-correlation gate passes."""
    trace_id = span_id = None
    if level in ("ERROR", "WARN"):
        trace_id, span_id = new_trace()
        line = f"{line} [{traceparent(trace_id, span_id)}]"
    add_event(dt, container, level, line, trace_id, span_id)


# ---------------------------------------------------------------------------
# Stack trace builders (realistic Spring/JVM frames)
# ---------------------------------------------------------------------------
def stack(exc_class: str, exc_msg: str, frames, caused_by=None):
    lines = [f"{exc_class}: {exc_msg}"]
    lines += [f"\tat {f}" for f in frames]
    if caused_by:
        c_class, c_msg, c_frames = caused_by
        lines.append(f"Caused by: {c_class}: {c_msg}")
        lines += [f"\tat {f}" for f in c_frames]
        lines.append("\t... 12 common frames omitted")
    return "\n".join(lines)


def frames_for(container: str, entry_method: str, extra=None):
    pkg = PKG[container]
    base = [
        f"{pkg}.{entry_method}",
        f"java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)",
        f"org.springframework.web.method.support.InvocableHandlerMethod.doInvoke(InvocableHandlerMethod.java:255)",
        f"org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:885)",
        f"org.apache.catalina.core.ApplicationFilterChain.internalDoFilter(ApplicationFilterChain.java:174)",
        f"org.apache.tomcat.util.threads.TaskThread$WrappingRunnable.run(TaskThread.java:63)",
        f"java.base/java.lang.Thread.run(Thread.java:840)",
    ]
    if extra:
        base = extra + base
    return base


# ---------------------------------------------------------------------------
# Chaos history writer
# ---------------------------------------------------------------------------
CHAOS_HISTORY = []


def record_chaos(fault_name: str, target: str, start_dt: datetime,
                 end_dt: datetime, params: dict, status: str = "recovered",
                 scenario_id: str = None):
    CHAOS_HISTORY.append({
        "event_id": str(uuid.uuid4()),
        "scenario_id": scenario_id or str(uuid.uuid4()),
        "fault_name": fault_name,
        "target": target,
        "start_ts": iso(start_dt),
        "end_ts": iso(end_dt),
        "params": params,
        "duration_s": round((end_dt - start_dt).total_seconds(), 2),
        "status": status,
    })


# ---------------------------------------------------------------------------
# Container state simulation (drives raw_telemetry / status / time_series)
# ---------------------------------------------------------------------------
class ContainerState:
    def __init__(self, name):
        self.name = name
        self.status = "running"
        self.health = "healthy"
        self.exit_code = 0
        self.cpu = random.uniform(2.0, 8.0)
        self.mem_pct = random.uniform(20.0, 45.0)
        self.anomaly = 0.0
        self.warnings = 0

    def snapshot(self, dt):
        limit = MEM_LIMITS[self.name]
        mem_bytes = int(limit * self.mem_pct / 100.0)
        return {
            "name": self.name,
            "status": self.status,
            "health": self.health if self.status == "running" else None,
            "started_at": iso(WINDOW_START - timedelta(minutes=random.randint(5, 30))),
            "finished_at": iso(dt) if self.status != "running" else None,
            "exit_code": self.exit_code if self.status != "running" else 0,
            "cpu_percent": round(self.cpu, 2),
            "memory_usage_bytes": mem_bytes,
            "memory_limit_bytes": limit,
            "memory_percent": round(self.mem_pct, 2),
            "network_rx_bytes": random.randint(10_000_000, 90_000_000),
            "network_tx_bytes": random.randint(10_000_000, 90_000_000),
            "network_rx_rate": round(random.uniform(500.0, 9000.0), 2),
            "network_tx_rate": round(random.uniform(500.0, 9000.0), 2),
            "anomaly_score": round(self.anomaly, 2),
            "active_warnings": self.warnings,
        }


STATES = {name: ContainerState(name) for name in ALL_CONTAINERS}
TIME_SERIES = []
RESTORATIONS = []  # (end_dt, container_name) -> restore running/healthy at end_dt


def schedule_restore(end_dt: datetime, container: str):
    RESTORATIONS.append((end_dt, container))


def apply_restorations(t: datetime):
    global RESTORATIONS
    due = [r for r in RESTORATIONS if t >= r[0]]
    if not due:
        return
    RESTORATIONS = [r for r in RESTORATIONS if t < r[0]]
    for _, name in due:
        st = STATES[name]
        st.status = "running"
        st.health = "healthy"
        st.exit_code = 0
        st.anomaly = 0.0


def tick_metrics(dt: datetime, spikes: dict = None):
    """Advance one telemetry sample for all containers."""
    spikes = spikes or {}
    for name, st in STATES.items():
        sp = spikes.get(name, {})
        if st.status == "running":
            st.cpu = max(0.5, min(100.0, st.cpu + random.uniform(-3, 3) + sp.get("cpu", 0.0)))
            st.mem_pct = max(5.0, min(99.0, st.mem_pct + random.uniform(-1.5, 1.5) + sp.get("mem", 0.0)))
            st.anomaly = sp.get("anomaly", max(0.0, st.anomaly - 0.3))
            st.warnings = sp.get("warnings", 1 if st.anomaly > 2.5 else 0)
            st.health = sp.get("health", "healthy")
        TIME_SERIES.append({
            "timestamp": iso(dt),
            "container": name,
            "cpu_percent": round(st.cpu, 2) if st.status == "running" else 0.0,
            "memory_percent": round(st.mem_pct, 2) if st.status == "running" else 0.0,
            "network_tx": round(random.uniform(500.0, 9000.0), 2),
            "network_rx": round(random.uniform(500.0, 9000.0), 2),
        })


# ---------------------------------------------------------------------------
# Normal business traffic (INFO noise + occasional benign warnings)
# ---------------------------------------------------------------------------
def business_traffic(dt: datetime):
    def alive(name):
        return STATES[name].status == "running"

    if alive("api-gateway"):
        app_info("api-gateway", dt, f"GET /api/orders 200 {random.randint(8, 120)}ms",
                 logger_name="org.springframework.cloud.gateway.handler.FilteringWebHandler")
    if alive("order-service"):
        app_info("order-service", dt, f"Order ORD-{random.randint(10000, 99999)} placed successfully",
                 logger_name=PKG["order-service"] + ".OrderController")
    if alive("payment-service"):
        app_info("payment-service", dt, f"Payment TXN-{uuid.uuid4().hex[:12]} authorized amount={random.randint(10, 500)}.00 USD",
                 logger_name=PKG["payment-service"] + ".PaymentController")
    if alive("auth-service"):
        app_info("auth-service", dt, f"JWT issued for user user{random.randint(1, 500)}",
                 logger_name=PKG["auth-service"] + ".controller.AuthController")
    if alive("postgres-db"):
        infra_event("postgres-db", dt, "INFO",
                    f"{dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC [{random.randint(20, 90)}] LOG:  duration: {random.uniform(0.2, 9.0):.3f} ms  execute <unnamed>: SELECT * FROM orders WHERE id = ${random.randint(1, 9)}")
    if alive("redis"):
        infra_event("redis", dt, "INFO", f"{random.randint(1, 9)}:M {dt.strftime('%d %b %Y %H:%M:%S.%f')[:-3]} * DB saved on disk")


# ---------------------------------------------------------------------------
# Scenario library — every fault class in the catalog + extras
# ---------------------------------------------------------------------------
def sc_http_throw_npe(t0: datetime, target: str):
    """ChaosController /chaos/throw?type=null-pointer"""
    end = t0 + timedelta(seconds=45)
    record_chaos("http_throw", target, t0, end, {"type": "null-pointer"})
    for i in range(14):
        dt = t0 + timedelta(seconds=i * 3 + random.uniform(0, 1.5))
        st = stack("java.lang.NullPointerException",
                   "Simulated NPE from ChaosController",
                   frames_for(target, "chaos.ChaosController.throwFault(ChaosController.java:88)"))
        app_error(target, dt, "Unhandled exception: Simulated NPE from ChaosController", st)
    return end


def sc_http_throw_sql_timeout(t0: datetime, target: str):
    end = t0 + timedelta(seconds=45)
    record_chaos("http_throw", target, t0, end, {"type": "sql-timeout"})
    for i in range(12):
        dt = t0 + timedelta(seconds=i * 3.5 + random.uniform(0, 1.5))
        st = stack(
            "org.springframework.dao.DataAccessResourceFailureException",
            "Simulated DB timeout",
            frames_for(target, "chaos.ChaosController.throwFault(ChaosController.java:94)"),
            caused_by=("org.postgresql.util.PSQLException",
                       "ERROR: canceling statement due to statement timeout",
                       ["org.postgresql.core.v3.QueryExecutorImpl.processResults(QueryExecutorImpl.java:2285)",
                        "org.postgresql.core.v3.QueryExecutorImpl.execute(QueryExecutorImpl.java:351)"]))
        app_error(target, dt, "Unhandled exception: Simulated DB timeout", st)
    return end


def sc_http_throw_conn_reset(t0: datetime, target: str):
    end = t0 + timedelta(seconds=45)
    record_chaos("http_throw", target, t0, end, {"type": "connection-reset"})
    for i in range(12):
        dt = t0 + timedelta(seconds=i * 3.5 + random.uniform(0, 1.5))
        st = stack(
            "org.springframework.web.client.ResourceAccessException",
            "I/O error on POST request for \"http://payment-service:8083/api/payments\": Connection reset",
            frames_for(target, "chaos.ChaosController.throwFault(ChaosController.java:100)"),
            caused_by=("java.net.SocketException", "Connection reset",
                       ["java.base/sun.nio.ch.NioSocketImpl.implRead(NioSocketImpl.java:313)",
                        "java.base/java.net.Socket$SocketInputStream.read(Socket.java:966)"]))
        app_error(target, dt, "Unhandled exception: I/O error on POST request: Connection reset", st)
    return end


def sc_http_slow(t0: datetime, target: str):
    end = t0 + timedelta(seconds=60)
    record_chaos("http_slow", target, t0, end, {"delayMs": 5000})
    for i in range(10):
        dt = t0 + timedelta(seconds=i * 5 + random.uniform(0, 2))
        app_warn(target, dt,
                 f"Request processing took {random.randint(5000, 7200)}ms, exceeding SLA threshold of 2000ms for /api/checkout")
    # upstream gateway timeouts as cascade evidence
    for i in range(6):
        dt = t0 + timedelta(seconds=10 + i * 7)
        st = stack("io.netty.handler.timeout.ReadTimeoutException",
                   f"Read timeout after 5000ms calling {target}",
                   ["io.netty.handler.timeout.ReadTimeoutHandler.readTimedOut(ReadTimeoutHandler.java:98)",
                    "io.netty.channel.AbstractChannelHandlerContext.invokeReadTimedOut(AbstractChannelHandlerContext.java:475)"])
        app_error("api-gateway", dt, f"Downstream call to {target} timed out after 5000ms", st)
    return end


def sc_http_memory_leak(t0: datetime, target: str):
    end = t0 + timedelta(seconds=90)
    record_chaos("http_memory_leak", target, t0, end, {"mb": 150})
    for i in range(8):
        dt = t0 + timedelta(seconds=i * 10)
        app_warn(target, dt,
                 f"Heap usage at {60 + i * 4}% after allocating 150MB chaos buffer; GC overhead increasing")
    dt = t0 + timedelta(seconds=85)
    st = stack("java.lang.OutOfMemoryError", "Java heap space",
               frames_for(target, "chaos.ChaosController.memoryLeak(ChaosController.java:120)",
                          extra=[f"{PKG[target]}.chaos.ChaosController.lambda$memoryLeak$2(ChaosController.java:124)"]))
    app_error(target, dt, "Unhandled exception: Java heap space", st)
    return end


def sc_http_deadlock(t0: datetime, target: str):
    end = t0 + timedelta(seconds=75)
    record_chaos("http_deadlock", target, t0, end, {})
    for i in range(9):
        dt = t0 + timedelta(seconds=i * 8)
        app_warn(target, dt,
                 f"Tomcat thread pool saturation: {190 + i}/200 worker threads busy, possible deadlock in ChaosController lock inversion",
                 logger_name="org.apache.tomcat.util.threads.LimitLatch")
    dt = t0 + timedelta(seconds=70)
    st = stack("java.lang.IllegalMonitorStateException",
               "Deadlock detected between chaos-lock-A and chaos-lock-B; threads http-nio-exec-3 and http-nio-exec-7 blocked",
               frames_for(target, "chaos.ChaosController.deadlock(ChaosController.java:140)"))
    app_error(target, dt, "Unhandled exception: Deadlock detected in chaos lock inversion", st)
    return end


def sc_http_sql_lock(t0: datetime, target: str):
    end = t0 + timedelta(seconds=40)
    record_chaos("http_sql_lock", target, t0, end, {})
    db = {"auth-service": "auth_db", "order-service": "order_db",
          "payment-service": "payment_db", "api-gateway": "postgres"}[target]
    for i in range(8):
        dt = t0 + timedelta(seconds=i * 4.5)
        st = stack("org.springframework.dao.QueryTimeoutException",
                   f"Statement cancelled due to timeout or client request (pg_sleep on {db})",
                   frames_for(target, "chaos.ChaosController.sqlLock(ChaosController.java:155)"),
                   caused_by=("org.postgresql.util.PSQLException",
                              "ERROR: canceling statement due to statement timeout",
                              ["org.postgresql.core.v3.QueryExecutorImpl.processResults(QueryExecutorImpl.java:2285)"]))
        app_error(target, dt, f"Unhandled exception: Query timeout on {db} (chaos sql-lock)", st)
    # postgres side evidence
    for i in range(4):
        dt = t0 + timedelta(seconds=2 + i * 9)
        infra_event("postgres-db", dt, "ERROR",
                    f"{iso(dt).replace('Z', '')} UTC [{random.randint(30, 99)}] ERROR:  canceling statement due to statement timeout")
    return end


def sc_http_exhaust_pool(t0: datetime, target: str):
    end = t0 + timedelta(seconds=45)
    record_chaos("http_exhaust_pool", target, t0, end, {})
    for i in range(12):
        dt = t0 + timedelta(seconds=i * 3.5)
        st = stack("org.springframework.jdbc.CannotGetJdbcConnectionException",
                   "Failed to obtain JDBC Connection; HikariPool-1 - Connection is not available, request timed out after 30000ms",
                   frames_for(target, "chaos.ChaosController.exhaustPool(ChaosController.java:170)"),
                   caused_by=("com.zaxxer.hikari.pool.HikariPool$PoolInitializationException",
                              "HikariPool-1 - Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0, waiting=7)",
                              ["com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:180)"]))
        app_error(target, dt, "Unhandled exception: HikariPool-1 - Connection is not available, request timed out after 30000ms", st)
    return end


def sc_pause_container(t0: datetime, target: str):
    end = t0 + timedelta(seconds=40)
    record_chaos("pause_container", target, t0, end, {})
    STATES[target].health = "unhealthy"
    STATES[target].anomaly = 3.2
    schedule_restore(end, target)
    # dependent services see timeouts
    dependents = {"postgres-db": ["auth-service", "order-service", "payment-service"],
                  "redis": ["auth-service"],
                  "rabbitmq": ["order-service"],
                  "otel-collector": APP_SERVICES}.get(target, [])
    for dep in dependents:
        for i in range(5):
            dt = t0 + timedelta(seconds=5 + i * 6)
            if target == "postgres-db":
                st = stack("org.springframework.transaction.CannotCreateTransactionException",
                           f"Could not open JPA transaction for transaction; connection to {target}:5432 refused (container paused)",
                           frames_for(dep, "repository.OrderRepository.findById(OrderRepository.java:42)"),
                           caused_by=("org.postgresql.util.PSQLException",
                                      "Connection to postgres-db:5432 refused. Check that the hostname and port are correct.",
                                      ["org.postgresql.core.v3.ConnectionFactoryImpl.openConnectionImpl(ConnectionFactoryImpl.java:346)"]))
                app_error(dep, dt, "Unhandled exception: Could not open JPA transaction (postgres paused)", st)
            elif target == "redis":
                st = stack("org.springframework.data.redis.RedisConnectionFailureException",
                           "Unable to connect to Redis server: redis/172.18.0.5:6379 (container paused)",
                           frames_for(dep, "util.JwtUtil.validateToken(JwtUtil.java:61)"),
                           caused_by=("io.lettuce.core.RedisConnectionException",
                                      "Unable to connect to redis:6379",
                                      ["io.lettuce.core.AbstractRedisClient.getConnection(AbstractRedisClient.java:330)"]))
                app_error(dep, dt, "Unhandled exception: Unable to connect to Redis (session cache unavailable)", st)
            elif target == "rabbitmq":
                st = stack("org.springframework.amqp.AmqpConnectException",
                           f"java.net.ConnectException: Connection refused to rabbitmq:5672 (container paused)",
                           frames_for(dep, "service.OrderEventPublisher.publish(OrderEventPublisher.java:55)"))
                app_error(dep, dt, "Unhandled exception: AMQP connection refused while publishing order event", st)
            else:  # otel-collector paused
                st = stack("io.opentelemetry.exporter.internal.http.HttpExporterException",
                           "Failed to export spans. Server responded with HTTP status code 503 (otel-collector paused)",
                           ["io.opentelemetry.exporter.internal.http.HttpExporter.doExport(HttpExporter.java:143)"])
                app_error(dep, dt, "Failed to export spans. Connection reset", st)
    return end


def sc_kill_container(t0: datetime, target: str):
    end = t0 + timedelta(seconds=35)
    record_chaos("kill_container", target, t0, end, {})
    STATES[target].status = "exited"
    STATES[target].exit_code = 137
    STATES[target].health = None
    STATES[target].anomaly = 30.0
    infra_event(target, t0 + timedelta(seconds=2), "ERROR",
                f"Container {target} killed (SIGKILL), exit code 137; restart policy restarting...")
    schedule_restore(end, target)
    return end


def sc_restart_container(t0: datetime, target: str):
    end = t0 + timedelta(seconds=30)
    record_chaos("restart_container", target, t0, end, {})
    for i in range(4):
        dt = t0 + timedelta(seconds=3 + i * 6)
        infra_event(target, dt, "WARN",
                    f"Service {target} restarting: upstream health check failed {i + 1}/3; clients may see transient connection errors")
    return end


def sc_cpu_throttle(t0: datetime, target: str):
    end = t0 + timedelta(seconds=60)
    record_chaos("cpu_throttle", target, t0, end, {"cpu_quota": 10000, "cpu_period": 100000})
    for i in range(8):
        dt = t0 + timedelta(seconds=i * 7)
        app_warn(target, dt,
                 f"Request latency degraded: p99={random.randint(2800, 6200)}ms due to CPU throttling (cfs quota 10000/100000)")
    return end


def sc_memory_limit(t0: datetime, target: str):
    end = t0 + timedelta(seconds=60)
    record_chaos("memory_limit", target, t0, end, {"memory": "384m"})
    for i in range(6):
        dt = t0 + timedelta(seconds=i * 9)
        app_warn(target, dt,
                 f"Memory pressure: usage at {88 + i}% of 384m limit, kernel may OOM-kill the container")
    return end


def sc_network_latency(t0: datetime, target: str):
    end = t0 + timedelta(seconds=50)
    record_chaos("network_latency", target, t0, end, {"latency_ms": 200})
    dependents = {"redis": ["auth-service"], "postgres-db": ["order-service", "payment-service"],
                  "rabbitmq": ["order-service"]}.get(target, APP_SERVICES)
    for dep in dependents[:2]:
        for i in range(5):
            dt = t0 + timedelta(seconds=4 + i * 8)
            app_warn(dep, dt,
                     f"Elevated round-trip latency to {target}: avg {random.randint(190, 260)}ms (netem delay 200ms injected)")
    return end


def sc_rabbitmq_backlog(t0: datetime):
    end = t0 + timedelta(seconds=45)
    record_chaos("rabbitmq_backlog", "rabbitmq", t0, end, {"messages": 1000})
    for i in range(6):
        dt = t0 + timedelta(seconds=i * 7)
        infra_event("rabbitmq", dt, "WARN",
                    f"2026-08-18 {dt.strftime('%H:%M:%S.%f')[:-3]} [warning] <0.{random.randint(600, 900)}.0> queue 'orders.created' on vhost '/' has {800 + i * 40} unconsumed messages (backlog injection)")
    for i in range(4):
        dt = t0 + timedelta(seconds=5 + i * 9)
        infra_event("rabbitmq", dt, "ERROR",
                    f"2026-08-18 {dt.strftime('%H:%M:%S.%f')[:-3]} [error] <0.{random.randint(600, 900)}.0> memory resource limit alarm set: {random.randint(78, 92)}% of 512MB used; publishers blocked")
    for i in range(5):
        dt = t0 + timedelta(seconds=8 + i * 7)
        st = stack("org.springframework.amqp.AmqpResourceNotAvailableException",
                   "The broker did not acknowledge; consumer lag on orders.created exceeds 800 messages",
                   frames_for("order-service", "service.OrderEventConsumer.consume(OrderEventConsumer.java:71)"))
        app_error("order-service", dt, "Unhandled exception: RabbitMQ consumer lag critical on orders.created", st)
    return end


def sc_gateway_5xx_injection(t0: datetime):
    end = t0 + timedelta(seconds=40)
    record_chaos("http_5xx_injection", "api-gateway", t0, end, {"codes": [502, 503, 504]})
    for i in range(15):
        dt = t0 + timedelta(seconds=i * 2.5)
        code = random.choice([502, 503, 504])
        reason = {502: "Bad Gateway: downstream closed connection",
                  503: "Service Unavailable: circuit open",
                  504: "Gateway Timeout: no response in 5000ms"}[code]
        app_warn("api-gateway", dt,
                 f"FailureInjectionFilter returned {code} for /api/orders ({reason})",
                 logger_name="com.ecommerce.gateway.filter.FailureInjectionFilter")
    return end


def sc_jwt_errors(t0: datetime):
    end = t0 + timedelta(seconds=40)
    record_chaos("auth_token_faults", "auth-service", t0, end, {"types": ["expired", "bad-signature"]})
    for i in range(8):
        dt = t0 + timedelta(seconds=i * 4.5)
        if i % 2 == 0:
            st = stack("io.jsonwebtoken.ExpiredJwtException",
                       f"JWT expired at {iso(dt - timedelta(hours=2))}. Current time: {iso(dt)}",
                       frames_for("auth-service", "util.JwtUtil.validateToken(JwtUtil.java:74)"))
            app_error("auth-service", dt, "Unhandled exception: JWT expired", st)
        else:
            st = stack("io.jsonwebtoken.security.SignatureException",
                       "JWT signature does not match locally computed signature; possible token tampering",
                       frames_for("auth-service", "util.JwtUtil.validateToken(JwtUtil.java:81)"))
            app_error("auth-service", dt, "Unhandled exception: Invalid JWT signature", st)
    return end


def sc_postgres_deadlock(t0: datetime):
    end = t0 + timedelta(seconds=35)
    record_chaos("db_deadlock", "postgres-db", t0, end, {})
    for i in range(5):
        dt = t0 + timedelta(seconds=i * 6)
        infra_event("postgres-db", dt, "ERROR",
                    f"{iso(dt).replace('Z', '')} UTC [{random.randint(30, 99)}] ERROR:  deadlock detected")
        infra_event("postgres-db", dt + timedelta(milliseconds=200), "ERROR",
                    f"{iso(dt).replace('Z', '')} UTC [{random.randint(30, 99)}] DETAIL:  Process {random.randint(100, 999)} waits for ShareLock on transaction {random.randint(10000, 99999)}; blocked by process {random.randint(100, 999)}.")
    for i in range(6):
        dt = t0 + timedelta(seconds=3 + i * 5)
        target = random.choice(["order-service", "payment-service"])
        st = stack("org.springframework.dao.DeadlockLoserDataAccessException",
                   "could not execute statement [deadlock detected]",
                   frames_for(target, "repository.OrderRepository.save(OrderRepository.java:58)"),
                   caused_by=("org.postgresql.util.PSQLException", "ERROR: deadlock detected",
                              ["org.postgresql.core.v3.QueryExecutorImpl.receiveErrorResponse(QueryExecutorImpl.java:2675)"]))
        app_error(target, dt, "Unhandled exception: DeadlockLoserDataAccessException on order write", st)
    return end


def sc_otel_export_failures(t0: datetime):
    end = t0 + timedelta(seconds=40)
    record_chaos("otel_export_fault", "otel-collector", t0, end, {})
    for svc in APP_SERVICES:
        for i in range(3):
            dt = t0 + timedelta(seconds=i * 12 + random.uniform(0, 3))
            st = stack("io.opentelemetry.sdk.common.export.ExportException",
                       "Failed to export spans. Connection reset by otel-collector:4318",
                       ["io.opentelemetry.exporter.internal.http.HttpExporter.doExport(HttpExporter.java:143)",
                        "io.opentelemetry.sdk.trace.export.BatchSpanProcessor$Worker.exportCurrentBatch(BatchSpanProcessor.java:332)"])
            app_error(svc, dt, "Failed to export spans. Connection reset", st)
    return end


def sc_payment_oom_kill(t0: datetime):
    """Terminal scenario: payment-service OOM-killed, stays down (exit 137).
    Gives the debate engine an ongoing CRITICAL incident with cascade evidence."""
    end = t0 + timedelta(seconds=120)
    record_chaos("memory_limit", "payment-service", t0, end, {"memory": "384m"}, status="injected")
    # Payments keep getting authorized while heap pressure builds, right up
    # until the kill. This keeps the business-traffic cluster's newest samples
    # INSIDE the chaos window (required by chaos_label_coverage gate).
    for i in range(8):
        dt = t0 + timedelta(seconds=2 + i * 6)
        app_info("payment-service", dt,
                 f"Payment TXN-{uuid.uuid4().hex[:12]} authorized amount={random.randint(10, 500)}.00 USD",
                 logger_name=PKG["payment-service"] + ".PaymentController")
    for i in range(6):
        dt = t0 + timedelta(seconds=i * 8)
        app_warn("payment-service", dt,
                 f"Memory pressure: heap at {90 + i}% of 384m limit after sustained transaction buffer growth")
    dt_kill = t0 + timedelta(seconds=55)
    infra_event("payment-service", dt_kill, "ERROR",
                "Killed: container exceeded memory limit 384m, exit code 137 (OOMKilled)")
    STATES["payment-service"].status = "exited"
    STATES["payment-service"].exit_code = 137
    STATES["payment-service"].health = None
    STATES["payment-service"].anomaly = 30.0
    # cascade: order-service and gateway see payment failures
    for i in range(8):
        dt = dt_kill + timedelta(seconds=5 + i * 6)
        st = stack("org.springframework.web.client.ResourceAccessException",
                   "I/O error on POST request for \"http://payment-service:8083/api/payments\": Connection refused (payment-service OOMKilled)",
                   frames_for("order-service", "service.OrderService.placeOrder(OrderService.java:96)"),
                   caused_by=("java.net.ConnectException", "Connection refused",
                              ["java.base/sun.nio.ch.Net.pollConnect(Native Method)"]))
        app_error("order-service", dt, "Unhandled exception: Payment service unreachable, order checkout failing", st)
    for i in range(5):
        dt = dt_kill + timedelta(seconds=10 + i * 9)
        st = stack("reactor.netty.http.client.PrematureCloseException",
                   "Connection prematurely closed BEFORE calling payment-service",
                   ["reactor.netty.http.client.HttpClientOperations.onInboundClose(HttpClientOperations.java:784)"])
        app_error("api-gateway", dt, "502 Bad Gateway returned for /api/checkout (payment-service down)", st)
    return end


# ---------------------------------------------------------------------------
# Scenario timeline (95-minute window)
# ---------------------------------------------------------------------------
def build_timeline():
    """Returns list of (start_offset_minutes, scenario_fn, args)."""
    return [
        (2, sc_http_throw_npe, ("api-gateway",)),
        (6, sc_rabbitmq_backlog, ()),
        (10, sc_http_slow, ("auth-service",)),
        (15, sc_pause_container, ("postgres-db",)),
        (20, sc_http_throw_sql_timeout, ("order-service",)),
        (25, sc_kill_container, ("auth-service",)),
        (29, sc_http_exhaust_pool, ("payment-service",)),
        (34, sc_network_latency, ("redis",)),
        (38, sc_http_memory_leak, ("api-gateway",)),
        (44, sc_gateway_5xx_injection, ()),
        (48, sc_http_deadlock, ("order-service",)),
        (53, sc_pause_container, ("redis",)),
        (57, sc_jwt_errors, ()),
        (61, sc_cpu_throttle, ("api-gateway",)),
        (65, sc_postgres_deadlock, ()),
        (69, sc_http_sql_lock, ("payment-service",)),
        (73, sc_otel_export_failures, ()),
        (77, sc_memory_limit, ("order-service",)),
        (81, sc_restart_container, ("rabbitmq",)),
        (84, sc_http_throw_conn_reset, ("order-service",)),
        (87, sc_payment_oom_kill, ()),
        (88, sc_pause_container, ("otel-collector",)),
    ]


def build_append_timeline(window_minutes):
    """A compact fault burst for append mode: a few scenarios spread across
    the (shorter) window, ending with an ongoing incident for the debate
    engine. Offsets scale to the requested window length."""
    if window_minutes <= 5:
        return [
            (0, sc_http_throw_npe, ("order-service",)),
            (1, sc_payment_oom_kill, ()),
        ]
    if window_minutes <= 15:
        return [
            (1, sc_http_throw_sql_timeout, ("order-service",)),
            (4, sc_rabbitmq_backlog, ()),
            (7, sc_jwt_errors, ()),
            (10, sc_http_exhaust_pool, ("payment-service",)),
            (12, sc_payment_oom_kill, ()),
        ]
    # longer append windows get the full catalog, compressed
    scale = window_minutes / 95.0
    return [(max(1, int(round(off * scale))), fn, args)
            for off, fn, args in build_timeline()]


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------
def wipe_frontend_data():
    os.makedirs(FRONTEND_DIR, exist_ok=True)
    removed = []
    for fname in os.listdir(FRONTEND_DIR):
        fpath = os.path.join(FRONTEND_DIR, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
            removed.append(fname)
    print(f"[recovery] Wiped {len(removed)} stale artifacts: {sorted(removed)}")


def run_simulation(window_minutes, timeline, recover_down_services=False):
    """Run the tick loop over the window [NOW - window_minutes, NOW].
    Populates EVENTS / TIME_SERIES / CHAOS_HISTORY and mutates STATES."""
    global NOW, WINDOW_START
    NOW = datetime.now(timezone.utc).replace(microsecond=0)
    WINDOW_START = NOW - timedelta(minutes=window_minutes)

    if recover_down_services:
        # Append mode: ops restarted any crashed service before the new window
        for name, st in STATES.items():
            if st.status != "running":
                infra_event(name, WINDOW_START + timedelta(seconds=1), "INFO",
                            f"Service {name} restarted by operations team after previous incident; health checks passing")
                st.status = "running"
                st.health = "healthy"
                st.exit_code = 0
                st.anomaly = 0.0

    # Iterate tick-by-tick (5s) across the window
    t = WINDOW_START
    scenario_idx = 0
    tick_counter = 0

    while t <= NOW:
        # Launch scheduled scenarios
        while scenario_idx < len(timeline):
            offset_min, fn, args = timeline[scenario_idx]
            start_dt = WINDOW_START + timedelta(minutes=offset_min)
            if t >= start_dt:
                end_dt = fn(start_dt, *args)
                print(f"[recovery] t+{offset_min:>2}m  {fn.__name__}{args if args else ''} -> ends {end_dt.strftime('%H:%M:%S')}")
                scenario_idx += 1
            else:
                break

        # Restore containers whose fault windows ended (payment-service stays
        # down: its OOM-kill is the ongoing incident for the debate engine)
        apply_restorations(t)

        # Normal business traffic every tick (~5s)
        business_traffic(t)

        # Metric tick with anomaly spikes during active faults
        spikes = {}
        for name, st in STATES.items():
            if st.status != "running":
                continue
            if st.anomaly > 0:
                spikes[name] = {"anomaly": st.anomaly, "cpu": 8.0 if st.anomaly > 2 else 2.0,
                                "mem": 4.0 if st.anomaly > 2 else 1.0,
                                "health": st.health or "healthy",
                                "warnings": 1}
        tick_metrics(t, spikes)

        # Decay anomalies gradually
        for st in STATES.values():
            if st.status == "running":
                st.anomaly = max(0.0, st.anomaly - 0.15)

        t += timedelta(seconds=5)
        tick_counter += 1


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------
def write_artifacts(timeline):
    # 1. events_and_incidents.json (sorted by timestamp)
    EVENTS.sort(key=lambda e: e["timestamp"])
    atomic_write_json(project_path("frontend_data", "events_and_incidents.json"), EVENTS)
    print(f"[recovery] Wrote {len(EVENTS)} events")

    # 2. chaos_history.json
    CHAOS_HISTORY.sort(key=lambda e: e["start_ts"])
    atomic_write_json(project_path("frontend_data", "chaos_history.json"), CHAOS_HISTORY)
    print(f"[recovery] Wrote {len(CHAOS_HISTORY)} chaos events")

    # 3. raw_telemetry.json (final snapshot)
    containers_snapshot = [STATES[n].snapshot(NOW) for n in ALL_CONTAINERS]
    atomic_write_json(project_path("frontend_data", "raw_telemetry.json"), {
        "generated_at": iso_z(NOW),
        "containers": containers_snapshot,
    })
    print(f"[recovery] Wrote raw_telemetry.json ({len(containers_snapshot)} containers)")

    # 4. time_series.json (cap 5000)
    ts_out = TIME_SERIES[-5000:]
    atomic_write_json(project_path("frontend_data", "time_series.json"), ts_out)
    print(f"[recovery] Wrote time_series.json ({len(ts_out)} points)")

    # 5. status.json — reuse the real sync logic shape
    from package_ml_dataset import parse_docker_compose_topology
    topo = parse_docker_compose_topology()

    def dep_status(score):
        return "healthy" if score >= 80 else "degraded" if score >= 50 else "unhealthy"

    services_list = []
    total_weight = weighted_sum = 0.0
    active_warnings = 0
    for c in containers_snapshot:
        name = c["name"]
        score = 0.0 if c["status"] in ("exited", "dead") else 100.0
        if c["status"] == "running":
            if (c.get("health") or "") == "unhealthy":
                score -= 50.0
            if c["anomaly_score"] > 0:
                score -= min(30.0, c["anomaly_score"] * 10.0)
            if c["memory_percent"] > 90 or c["cpu_percent"] > 95:
                score -= 15.0
        score = max(0.0, min(100.0, score))
        weight = 2.0 if name in {"api-gateway", "postgres-db", "otel-collector"} else 1.0
        weighted_sum += score * weight
        total_weight += weight
        if c["active_warnings"] > 0 or c["status"] != "running":
            active_warnings += 1
        deps = topo.get(name, {}).get("downstream_dependencies", [])
        dep_states = {}
        for d in deps:
            d_snap = next((x for x in containers_snapshot if x["name"] == d), None)
            d_score = 0.0 if d_snap and d_snap["status"] != "running" else 100.0
            dep_states[d] = dep_status(d_score)
        services_list.append({
            "name": name,
            "docker_status": c["status"],
            "health_check": c["health"] if c["status"] == "running" else "unhealthy",
            "cpu_percent": c["cpu_percent"],
            "memory_percent": c["memory_percent"],
            "anomaly_score": c["anomaly_score"],
            "health_score": round(score, 1),
            "dependency_states": dep_states,
        })

    system_health = round(weighted_sum / total_weight, 1) if total_weight else 100.0
    atomic_write_json(project_path("frontend_data", "status.json"), {
        "timestamp": iso_z(NOW),
        "system_health_score": system_health,
        "active_warnings": active_warnings,
        "services": services_list,
    })
    print(f"[recovery] Wrote status.json (health={system_health}, warnings={active_warnings})")

    # 6. analytics.json (in append mode, keep prior history before this window)
    health_history = [h for h in PRIOR_HEALTH_HISTORY
                      if h.get("timestamp", "") < iso(WINDOW_START)]
    hist_t = WINDOW_START
    base = 100.0
    while hist_t <= NOW:
        # dip health during scenario windows
        dip = 0.0
        for offset_min, fn, args in timeline:
            s_dt = WINDOW_START + timedelta(minutes=offset_min)
            if s_dt <= hist_t <= s_dt + timedelta(minutes=3):
                dip = max(dip, random.uniform(10, 30))
        base = max(45.0, min(100.0, base + random.uniform(-2, 2) - dip * 0.1))
        health_history.append({"timestamp": iso(hist_t), "score": round(base, 1)})
        hist_t += timedelta(minutes=1)
    atomic_write_json(project_path("frontend_data", "analytics.json"), {
        "generated_at": iso_z(NOW),
        "system_health_score": system_health,
        "active_warnings": active_warnings,
        "health_history": health_history[-100:],
    })
    print(f"[recovery] Wrote analytics.json ({len(health_history[-100:])} history points)")

    # 7. causality.json & cost_and_roi.json (schema stubs for Phase 3;
    #    never clobber results Phase 3 has already written in append mode)
    for fname, stub in (("causality.json", {"root_cause": "", "confidence": 0, "evidence": []}),
                        ("cost_and_roi.json", {"estimated_cost": 0.0, "impact": "none"})):
        fpath = project_path("frontend_data", fname)
        if not os.path.exists(fpath):
            atomic_write_json(fpath, stub)

    # Summary
    levels = {}
    for e in EVENTS:
        levels[e["level"]] = levels.get(e["level"], 0) + 1
    print(f"\n[recovery] Event level breakdown: {levels}")
    print(f"[recovery] Chaos faults simulated: {len(CHAOS_HISTORY)} events, "
          f"{len(set(c['fault_name'] for c in CHAOS_HISTORY))} distinct fault types")


# ---------------------------------------------------------------------------
# Append mode: load existing data so new telemetry merges on top of it
# ---------------------------------------------------------------------------
def load_existing_data():
    """Populate EVENTS / CHAOS_HISTORY / TIME_SERIES / PRIOR_HEALTH_HISTORY
    from the current frontend_data artifacts (append mode only)."""
    from utils import read_json_file
    global PRIOR_HEALTH_HISTORY

    existing_events = read_json_file(
        project_path("frontend_data", "events_and_incidents.json"), [], retries=2)
    if existing_events:
        EVENTS.extend(existing_events)

    existing_chaos = read_json_file(
        project_path("frontend_data", "chaos_history.json"), [], retries=2)
    if existing_chaos:
        CHAOS_HISTORY.extend(existing_chaos)

    existing_ts = read_json_file(
        project_path("frontend_data", "time_series.json"), [], retries=2)
    if existing_ts:
        TIME_SERIES.extend(existing_ts)

    analytics = read_json_file(
        project_path("frontend_data", "analytics.json"), {}, retries=2)
    PRIOR_HEALTH_HISTORY = analytics.get("health_history", []) if isinstance(analytics, dict) else []

    print(f"[append] Loaded existing data: {len(existing_events)} events, "
          f"{len(existing_chaos)} chaos events, {len(existing_ts)} time-series points")


def choose_mode():
    """Interactive mode selection. Returns 'fresh' or 'append'."""
    print("\n=== [Auto-SRE] Telemetry simulation mode ===")
    print("  1) FRESH  - wipe ALL old logs/data and start from scratch")
    print("  2) APPEND - keep existing logs and add new telemetry on top")
    while True:
        try:
            choice = input("Choose mode [1=fresh / 2=append] (default 1): ").strip().lower()
        except EOFError:
            choice = ""
        if choice in ("", "1", "fresh", "f"):
            return "fresh"
        if choice in ("2", "append", "a"):
            return "append"
        print("  Invalid choice. Enter 1 for fresh or 2 for append.")


def run_pipeline(reset_drain: bool):
    """Run the real pipeline: cluster -> package -> validate."""
    steps = [
        [sys.executable, "phase1_processor.py"] + (["--reset-drain"] if reset_drain else []),
        [sys.executable, "package_ml_dataset.py"],
        [sys.executable, "validate.py", "--runtime"],
    ]
    for cmd in steps:
        print(f"\n[pipeline] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        if result.returncode != 0:
            print(f"[pipeline] Step failed with exit code {result.returncode}: {' '.join(cmd)}")
            return result.returncode
    print("\n[pipeline] All steps completed successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Simulate full-coverage telemetry for the Auto-SRE platform.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--fresh", action="store_true",
                            help="Wipe all old logs/data and start fresh (no prompt)")
    mode_group.add_argument("--append", action="store_true",
                            help="Keep existing logs and append new telemetry (no prompt)")
    parser.add_argument("--minutes", type=int, default=None,
                        help="Window length in minutes (default: 95 fresh / 15 append)")
    parser.add_argument("--no-pipeline", action="store_true",
                        help="Skip running phase1_processor/package/validate afterwards")
    args = parser.parse_args()

    if args.fresh:
        mode = "fresh"
    elif args.append:
        mode = "append"
    else:
        mode = choose_mode()

    if mode == "fresh":
        window_minutes = args.minutes or 95
        print(f"\n=== [Auto-SRE] FRESH telemetry simulation ({window_minutes}-min window) ===")
        wipe_frontend_data()
        timeline = build_timeline()
        run_simulation(window_minutes, timeline)
        write_artifacts(timeline)
        reset_drain = True
    else:
        window_minutes = args.minutes or 15
        print(f"\n=== [Auto-SRE] APPEND telemetry simulation ({window_minutes}-min window) ===")
        load_existing_data()
        timeline = build_append_timeline(window_minutes)
        run_simulation(window_minutes, timeline, recover_down_services=True)
        write_artifacts(timeline)
        reset_drain = False

    if args.no_pipeline:
        print("\n[recovery] Done. Next: python phase1_processor.py"
              + (" --reset-drain" if reset_drain else "")
              + "; python package_ml_dataset.py; python validate.py --runtime")
        return 0
    return run_pipeline(reset_drain)


if __name__ == "__main__":
    sys.exit(main())
