"""Verify this laptop can reach the host's Phase 1 tunnel endpoint.

Stdlib only — no dependencies. Reads the live URL from federation/.env.federation
(falls back to the known host URL), then checks /health and /dataset.

Usage:
    python federation/test_phase1_url.py
    python federation/test_phase1_url.py --url https://custom.trycloudflare.com
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

FEDERATION_ENV = Path(__file__).resolve().parent / ".env.federation"
FALLBACK_URL = "https://making-defines-handled-melbourne.trycloudflare.com"


def read_phase1_url() -> str:
    """Prefer PHASE1_DATASET_URL from .env.federation, else the fallback."""
    if FEDERATION_ENV.exists():
        for line in FEDERATION_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PHASE1_DATASET_URL="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return FALLBACK_URL


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "autosre-federation-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Phase 1 tunnel reachability")
    parser.add_argument("--url", help="Override the Phase 1 base URL")
    args = parser.parse_args()

    base = (args.url or read_phase1_url()).rstrip("/")
    print(f"Checking Phase 1 endpoint: {base}\n")

    failures = 0

    # /health
    try:
        status, body = fetch(f"{base}/health")
        data = json.loads(body)
        print(
            f"[ok] health  -> status={data.get('status')} "
            f"dataset_present={data.get('dataset_present')}"
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[FAIL] health  -> {exc}")
        failures += 1

    # /dataset
    try:
        status, body = fetch(f"{base}/dataset")
        data = json.loads(body)
        print(
            f"[ok] dataset -> {len(body)} bytes, "
            f"generated_at={data.get('generated_at')}, "
            f"incidents={len(data.get('incidents', []))}"
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[FAIL] dataset -> {exc}")
        failures += 1

    print()
    if failures:
        print(f"PHASE 1 ENDPOINT NOT REACHABLE ❌ ({failures} check(s) failed)")
        print("Ask the host to re-run: .\\federation\\start-tunnel.ps1 -Phase phase1")
        return 1

    print("PHASE 1 ENDPOINT REACHABLE ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
