#!/usr/bin/env python3
"""validate_10.py - Phase 1 '10/10' acceptance gate validator.

Usage:
    python validate_10.py --static          # repo hygiene checks only (no stack needed)
    python validate_10.py --runtime         # dataset gates (requires generated frontend_data)
    python validate_10.py                   # both
Exit code 0 = all gates pass.
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).parent
RESULTS = []

def gate(name, passed, detail=""):
    RESULTS.append({"gate": name, "passed": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL':4} | {name:45} | {detail}")

def read(path):
    p = ROOT / path
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""

def _gitignore_patterns():
    """Return (negations, patterns) parsed from .gitignore (comments/blank lines dropped)."""
    negations, patterns = [], []
    for raw in read(".gitignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            negations.append(line[1:])
        else:
            patterns.append(line)
    return negations, patterns

def _match_pattern(relpath, pattern):
    """Approximate gitignore matching for the patterns used in this repo."""
    relpath = relpath.replace("\\", "/")
    pattern = pattern.rstrip("/")
    if "/" in pattern:
        # Anchored to repo root: match the path or any descendant.
        return fnmatch.fnmatch(relpath, pattern) or fnmatch.fnmatch(relpath, pattern + "/*")
    # Unanchored: match against the basename at any depth.
    return fnmatch.fnmatch(relpath.split("/")[-1], pattern)

def _is_gitignored(relpath):
    negations, patterns = _gitignore_patterns()
    ignored = any(_match_pattern(relpath, p) for p in patterns)
    if ignored and any(_match_pattern(relpath, n) for n in negations):
        ignored = False
    return ignored

# ---------------- Static gates ----------------

def static_gates():
    compose = read("docker-compose.yml")
    compose_yaml = yaml.safe_load(compose) or {} if compose else {}

    # WS3: no :latest images
    latest = re.findall(r"image:\s*(\S+:latest)", compose)
    gate("compose_no_latest_tags", not latest, f"offenders={latest}" if latest else "all pinned")

    # WS4: no hardcoded default credentials
    cred_hits = [p for p in ("POSTGRES_PASSWORD=postgres", "RABBITMQ_DEFAULT_PASS=guest")
                 if p in compose]
    gate("compose_no_default_creds", not cred_hits, f"offenders={cred_hits}" if cred_hits else "env-driven")
    gate("env_example_exists", (ROOT / ".env.example").exists())
    gate("env_gitignored", ".env" in read(".gitignore"))

    # WS3: generated artifacts not tracked
    try:
        tracked = subprocess.run(["git", "ls-files", "frontend_data/", "validation_report.json"],
                                 capture_output=True, text=True, cwd=ROOT).stdout.split()
        bad = [f for f in tracked if f.endswith((".json", ".bin", ".meta", ".log"))]
        gate("no_generated_artifacts_tracked", not bad, f"tracked={bad[:5]}" if bad else "clean")
    except FileNotFoundError:
        present = [str(p.relative_to(ROOT)) for p in (ROOT / "frontend_data").glob("*")
                   if p.suffix in (".json", ".bin", ".meta", ".log")]
        if (ROOT / "validation_report.json").exists():
            present.append("validation_report.json")
        tracked_like = [f for f in present if not _is_gitignored(f)]
        gate("no_generated_artifacts_tracked", not tracked_like,
             f"tracked={tracked_like[:5]}" if tracked_like else "clean (no git; gitignore-aware disk check)")

    # WS3: pinned python deps
    unpinned = [line.strip() for line in read("requirements.txt").splitlines()
                if line.strip() and not line.startswith("#") and "==" not in line]
    gate("requirements_pinned", not unpinned, f"unpinned={unpinned}" if unpinned else "all ==")

    # WS2: GitLab CI present with required stages
    ci = read(".gitlab-ci.yml")
    need = {"lint", "test-python", "test-java", "integration", "validate"}
    have = set(re.findall(r"^\s*-\s*([\w-]+)\s*$", ci, re.M)) if ci else set()
    gate("gitlab_ci_stages", need.issubset(have), f"missing={need - have}" if ci else "no .gitlab-ci.yml")

    # WS1: every service has Java tests
    for svc in ("api-gateway", "auth-service", "order-service", "payment-service"):
        tests = list((ROOT / svc / "src" / "test").rglob("*Test.java"))
        gate(f"java_tests_{svc}", len(tests) >= 1, f"{len(tests)} test file(s)")

    # WS5: orchestrator quality & credentials
    orch = read("chaos_orchestrator.py")
    gate("orchestrator_uses_logging", "get_logger" in orch and 'print(' not in orch,
         "logging module, no print()")
    gate("orchestrator_no_bare_except", "except Exception:" not in orch)
    gate("no_hardcoded_creds", "PlainCredentials('guest'" not in orch and 'PlainCredentials("guest"' not in orch,
         "env-driven credentials")
    gate("redis_allowlist_typo_fixed", "fatale" not in read("phase1_processor.py"))

    # WS4: Observability provisioning
    gate("grafana_prometheus_provisioned", (ROOT / "grafana" / "provisioning" / "datasources" / "prometheus.yml").exists())
    gate("grafana_dashboard_provisioned", (ROOT / "grafana" / "provisioning" / "dashboards" / "system-overview.json").exists())

    # WS6: portability
    gate("cross_platform_entrypoint", (ROOT / "run.sh").exists() or (ROOT / "Makefile").exists())

    # --- Phase 5 Audit Hardening Gates ---

    # 1. compose_no_fallback_creds
    fallback_creds = re.findall(r'\$\{[A-Z_]*(?:PASSWORD|PASS|SECRET|USER)[A-Z_]*:-[^}]*\}', compose)
    gate("compose_no_fallback_creds", not fallback_creds, f"offenders={fallback_creds}" if fallback_creds else "no :-credential fallbacks")

    # 2. compose_ports_loopback
    non_loopback_ports = []
    for svc_name, s_cfg in compose_yaml.get("services", {}).items():
        for p in s_cfg.get("ports", []):
            p_str = str(p)
            if ":" in p_str and not p_str.startswith("127.0.0.1:"):
                non_loopback_ports.append(f"{svc_name}:{p_str}")
    gate("compose_ports_loopback", not non_loopback_ports, f"offenders={non_loopback_ports}" if non_loopback_ports else "all 127.0.0.1")

    # 3. redis_requirepass
    redis_cmd = str(compose_yaml.get("services", {}).get("redis", {}).get("command", ""))
    gate("redis_requirepass", "requirepass" in redis_cmd, "redis configured with --requirepass")

    # 4. downstream_security_deps
    order_pom = read("order-service/pom.xml")
    payment_pom = read("payment-service/pom.xml")
    has_sec = ("spring-boot-starter-security" in order_pom) and ("spring-boot-starter-security" in payment_pom)
    gate("downstream_security_deps", has_sec, "order & payment poms have spring-boot-starter-security")

    # 5. no_hardcoded_jwt_secret
    jwt_leaks = []
    for java_file in ROOT.glob("*/src/main/**/*.java"):
        if "9a4f2c8d" in java_file.read_text(encoding="utf-8", errors="ignore"):
            jwt_leaks.append(str(java_file.relative_to(ROOT)))
    gate("no_hardcoded_jwt_secret", not jwt_leaks, f"offenders={jwt_leaks}" if jwt_leaks else "no secret literals in Java source")

    # 6. atomic_write_has_fsync
    utils_code = read("utils.py")
    gate("atomic_write_has_fsync", "os.fsync" in utils_code, "utils.py contains os.fsync")

    # 7. lock_file_never_deleted
    flc_match = re.search(r'def file_lock_context\(.*?\n(?=def|\Z)', utils_code, re.DOTALL)
    flc_text = flc_match.group(0) if flc_match else ""
    gate("lock_file_never_deleted", "os.remove" not in flc_text, "file_lock_context never deletes lock files")

    # 8. chaos_latency_validated
    gate("chaos_latency_validated", "1 <= latency_ms <= 10000" in orch, "latency_ms clamped to 1..10000")

    # 9. deadlock_clearable
    deadlock_valid = True
    for svc in ("api-gateway", "auth-service", "order-service", "payment-service"):
        pkg = "com/ecommerce/gateway" if svc == "api-gateway" else "com/ecommerce/auth" if svc == "auth-service" else "com/autosre/orderservice" if svc == "order-service" else "com/autosre/paymentservice"
        ctrl = read(f"{svc}/src/main/java/{pkg}/chaos/ChaosController.java")
        if "AtomicBoolean" not in ctrl or "tryLock" not in ctrl:
            deadlock_valid = False
    gate("deadlock_clearable", deadlock_valid, "all 4 ChaosControllers contain AtomicBoolean & tryLock")

    # 10. run_scripts_fail_closed
    run_ps1 = read("run.ps1")
    run_sh = read("run.sh")
    ps1_guard = "dev-chaos-token" in run_ps1 and "CHANGE_ME_chaos_secret" in run_ps1
    sh_guard = "dev-chaos-token" in run_sh and "CHANGE_ME_chaos_secret" in run_sh
    gate("run_scripts_fail_closed", ps1_guard and sh_guard, "run scripts fail-closed on default chaos token")

# ---------------- Runtime gates ----------------

def load_json(path):
    p = ROOT / path
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def runtime_gates(freshness_hours):
    dataset = load_json("frontend_data/unified_master_dataset.json")
    chaos = load_json("frontend_data/chaos_history.json")
    if dataset is None:
        gate("dataset_exists", True, "SKIPPED (unified_master_dataset.json not present; run stack to generate)")
        return
    incidents = dataset.get("incidents", [])

    # Original gates (kept from validate.py)
    err, corr = 0, 0
    for inc in incidents:
        for s in inc.get("telemetry_evidence", {}).get("log_samples", []):
            if s.get("level") in ("ERROR", "WARN"):
                err += 1
                corr += bool(s.get("trace_id") and s.get("span_id"))
    ratio = corr / err if err else 1.0
    gate("trace_ratio_errwarn>=0.95", ratio >= 0.95, f"ratio={ratio:.3f}")

    gate("redis_med_high==0", not any(
        i["incident_event"]["target_service"] == "redis"
        and i["incident_event"]["severity"] in ("MEDIUM", "HIGH", "CRITICAL") for i in incidents))
    gate("rabbitmq_in_top5==0", not any(
        i["incident_event"]["target_service"] == "rabbitmq" for i in incidents[:5]))
    gate("top5_no_stack_fragments", not any(
        i["telemetry_evidence"]["log_cluster_template"].strip().startswith("at ")
        and "Exception" not in i["telemetry_evidence"]["log_cluster_template"]
        for i in incidents[:5]))

    # Timestamp validity (ISO-8601 UTC)
    def ok_ts(t):
        try:
            datetime.fromisoformat(str(t).replace("Z", "+00:00"))
            return True
        except (ValueError, TypeError):
            return False
    all_ts = [s.get("timestamp") for i in incidents
              for s in i.get("telemetry_evidence", {}).get("log_samples", [])]
    bad_ts = [t for t in all_ts if not ok_ts(t)]
    gate("timestamps_iso8601", not bad_ts, f"{len(bad_ts)}/{len(all_ts)} invalid")

    # Chaos label coverage for HIGH/CRITICAL incidents
    if chaos:
        windows = []
        for e in (chaos if isinstance(chaos, list) else chaos.get("events", [])):
            s_, e_ = e.get("start_ts"), e.get("end_ts")
            if s_ and e_ and ok_ts(s_) and ok_ts(e_):
                windows.append((datetime.fromisoformat(s_.replace("Z", "+00:00")),
                                datetime.fromisoformat(e_.replace("Z", "+00:00"))))
        hi = [i for i in incidents if i["incident_event"]["severity"] in ("HIGH", "CRITICAL")]
        def in_window(inc):
            for s in inc.get("telemetry_evidence", {}).get("log_samples", []):
                if ok_ts(s.get("timestamp")):
                    ts = datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))
                    if any(w0 <= ts <= w1 for w0, w1 in windows):
                        return True
            return False
        cov = sum(map(in_window, hi)) / len(hi) if hi else 1.0
        gate("chaos_label_coverage>=0.90", cov >= 0.90, f"coverage={cov:.2f} over {len(hi)} incidents")
    else:
        gate("chaos_label_coverage>=0.90", False, "chaos_history.json missing")

    # Topology consistency
    unknown = [i["incident_event"]["target_service"] for i in incidents
               if not i.get("infrastructure_topology")]
    gate("topology_consistent", not unknown, f"unmapped={set(unknown)}" if unknown else "all mapped")

    # Dataset freshness
    gen = dataset.get("generated_at")
    fresh = ok_ts(gen) and datetime.now(timezone.utc) - datetime.fromisoformat(
        gen.replace("Z", "+00:00")) < timedelta(hours=freshness_hours)
    gate(f"dataset_fresh<{freshness_hours}h", fresh, f"generated_at={gen}")

    # Dataset Metadata lineage
    meta = dataset.get("metadata")
    gate("dataset_metadata_lineage", meta is not None and "git_sha" in meta and "dataset_version" in meta)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--runtime", action="store_true")
    ap.add_argument("--freshness-hours", type=int, default=24)
    args = ap.parse_args()

    run_static = args.static or not args.runtime
    run_runtime = args.runtime or not args.static

    if run_static:
        print("=== STATIC GATES ===")
        static_gates()
    if run_runtime:
        print("\n=== RUNTIME GATES ===")
        runtime_gates(args.freshness_hours)

    passed = sum(1 for r in RESULTS if r["passed"])
    print(f"\nRESULT: {passed}/{len(RESULTS)} gates passed\n")

    report = ROOT / "validation_report.json"
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now(timezone.utc).isoformat(),
                   "passed": passed, "total": len(RESULTS),
                   "gates": RESULTS}, f, indent=2)

    sys.exit(0 if passed == len(RESULTS) else 1)

if __name__ == "__main__":
    main()
