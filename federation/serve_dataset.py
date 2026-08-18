"""Serve the Phase 1 master dataset to other laptops over a tunnel.

Zero-dependency (stdlib only) read-only HTTP server over ``frontend_data/``.

Usage:
    python federation/serve_dataset.py --port 8090

Endpoints:
    GET /health    -> server status + dataset freshness
    GET /dataset   -> frontend_data/unified_master_dataset.json
    GET /files     -> list of available JSON artifacts
    GET /<name>    -> any *.json file inside frontend_data/ (e.g. /status.json)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend_data"
MASTER_DATASET = "unified_master_dataset.json"


class DatasetHandler(BaseHTTPRequestHandler):
    server_version = "AutoSREPhase1/1.0"

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": f"cannot read {path.name}"}, status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        route = self.path.split("?", 1)[0].strip("/")

        if route == "health":
            master = FRONTEND_DIR / MASTER_DATASET
            generated_at = None
            if master.exists():
                try:
                    generated_at = json.loads(master.read_text(encoding="utf-8")).get(
                        "generated_at"
                    )
                except (OSError, json.JSONDecodeError):
                    pass
            self._send_json(
                {
                    "status": "ok",
                    "phase": "phase1-telemetry",
                    "dataset_present": master.exists(),
                    "dataset_generated_at": generated_at,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                }
            )
            return

        if route == "dataset":
            master = FRONTEND_DIR / MASTER_DATASET
            if not master.exists():
                self._send_json(
                    {"error": "unified_master_dataset.json not found - run package_ml_dataset.py"},
                    status=404,
                )
                return
            self._send_file(master)
            return

        if route == "files":
            self._send_json(
                sorted(p.name for p in FRONTEND_DIR.glob("*.json"))
            )
            return

        # /<name>.json -> serve from frontend_data, path-traversal safe
        candidate = (FRONTEND_DIR / route).resolve()
        if (
            route.endswith(".json")
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIR)
        ):
            self._send_file(candidate)
            return

        self._send_json(
            {"error": "not found", "routes": ["/health", "/dataset", "/files", "/<name>.json"]},
            status=404,
        )

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        print("[serve_dataset] " + fmt % args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 dataset endpoint")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), DatasetHandler)
    print(f"Phase 1 dataset endpoint on http://{args.host}:{args.port}")
    print(f"  GET /dataset -> {MASTER_DATASET}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
