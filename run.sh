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
