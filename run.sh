#!/usr/bin/env bash
# ==============================================================================
# Auto-SRE Platform - Cross-Platform Execution Script
# ==============================================================================
set -euo pipefail

echo "=== [Auto-SRE Platform] Orchestrating Environment ==="

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo "[!] .env not found. Copying .env.example to .env..."
    cp .env.example .env
  else
    echo "[-] Error: .env.example missing."
    exit 1
  fi
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Preflight: Check RAM on Linux/Mac
if command -v free >/dev/null 2>&1; then
  FREE_MB=$(free -m | awk '/^Mem:/{print $7}')
  if [ "$FREE_MB" -lt 6144 ]; then
    echo "[!] WARNING: Available RAM is ${FREE_MB}MB (< 6000MB recommended)."
  fi
fi

if [ "${CHAOS_SECRET:-}" = "dev-chaos-token" ] && [ "${ENABLE_CHAOS:-false}" = "true" ]; then
  echo "[!] SECURITY NOTICE: CHAOS_SECRET is using default 'dev-chaos-token'."
fi

# 1. Clean existing containers
echo "[1/4] Tearing down existing containers and volumes..."
docker compose down -v --remove-orphans

# 2. Build and launch docker services
echo "[2/4] Building and launching Docker services..."
docker compose up -d --build

# 3. Wait for services
echo "[3/4] Waiting for services to become healthy..."
sleep 20

# 4. Launch background daemons
echo "[4/4] Launching background telemetry and monitoring daemons..."
python continuous_telemetry.py &
python frontend_data_sync.py &
python monitor_ram.py &

echo "[+] Platform initialized successfully!"
docker compose ps
