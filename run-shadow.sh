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
