#!/usr/bin/env bash
# Management script for Shadow Sandbox Layer 1 environment (Bash).
# Usage: ./run_shadow.sh [up|down|status|health]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.shadow.yml"
ENV_FILE="${SCRIPT_DIR}/env.shadow"
NETWORK_NAME="shadow-net"
OBS_TOOLS=("otel-collector" "jaeger" "prometheus")

ACTION="${1:-up}"

case "${ACTION}" in
    up)
        echo -e "\033[0;36m[SHADOW] Setting up shadow network '${NETWORK_NAME}'...\033[0m"
        if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
            docker network create "${NETWORK_NAME}"
            echo -e "\033[0;32m[SHADOW] Network '${NETWORK_NAME}' created.\033[0m"
        else
            echo -e "\033[0;33m[SHADOW] Network '${NETWORK_NAME}' already exists.\033[0m"
        fi

        echo -e "\033[0;36m[SHADOW] Checking observability dual-homing...\033[0m"
        for tool in "${OBS_TOOLS[@]}"; do
            if docker ps -q -f name="^/${tool}$" | grep -q .; then
                if ! docker inspect "${tool}" --format '{{json .NetworkSettings.Networks}}' | grep -q "${NETWORK_NAME}"; then
                    echo -e "\033[0;36m[SHADOW] Connecting '${tool}' to '${NETWORK_NAME}' (dual-homing)...\033[0m"
                    docker network connect "${NETWORK_NAME}" "${tool}"
                else
                    echo -e "\033[0;33m[SHADOW] '${tool}' already dual-homed.\033[0m"
                fi
            else
                echo -e "\033[0;33m[SHADOW] Observability service '${tool}' is not currently running (skipping dual-homed attach).\033[0m"
            fi
        done

        echo -e "\033[0;36m[SHADOW] Launching 7 shadow services...\033[0m"
        docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --build
        echo -e "\033[0;32m[SHADOW] Shadow environment launched successfully.\033[0m"
        ;;

    down)
        echo -e "\033[0;36m[SHADOW] Stopping shadow services...\033[0m"
        docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down -v

        echo -e "\033[0;36m[SHADOW] Disconnecting observability tools from '${NETWORK_NAME}'...\033[0m"
        for tool in "${OBS_TOOLS[@]}"; do
            if docker ps -q -f name="^/${tool}$" | grep -q .; then
                if docker inspect "${tool}" --format '{{json .NetworkSettings.Networks}}' | grep -q "${NETWORK_NAME}"; then
                    echo -e "\033[0;36m[SHADOW] Disconnecting '${tool}' from '${NETWORK_NAME}'...\033[0m"
                    docker network disconnect "${NETWORK_NAME}" "${tool}" || true
                fi
            fi
        done

        if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
            echo -e "\033[0;36m[SHADOW] Removing network '${NETWORK_NAME}'...\033[0m"
            docker network rm "${NETWORK_NAME}" || true
        fi
        echo -e "\033[0;32m[SHADOW] Shadow environment completely cleaned up.\033[0m"
        ;;

    status)
        echo -e "\033[0;36m=== Shadow Containers ===\033[0m"
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" -f name=shadow-

        echo -e "\n\033[0;36m=== Shadow Network Inspection ===\033[0m"
        if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
            docker network inspect "${NETWORK_NAME}" --format '{{range .Containers}}{{.Name}} ({{.IPv4Address}}){{"\n"}}{{end}}'
        else
            echo -e "\033[0;31mNetwork '${NETWORK_NAME}' does not exist.\033[0m"
        fi
        ;;

    health)
        echo -e "\033[0;36m=== Shadow Containers Health Status ===\033[0m"
        containers=("shadow-postgres-db" "shadow-redis" "shadow-rabbitmq" "shadow-api-gateway" "shadow-auth-service" "shadow-order-service" "shadow-payment-service")
        for c in "${containers[@]}"; do
            if docker ps -q -f name="^/${c}$" | grep -q .; then
                status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$c")
                printf "%-25s : %s\n" "$c" "$status"
            else
                printf "%-25s : NOT RUNNING\n" "$c"
            fi
        done
        ;;

    *)
        echo "Usage: $0 [up|down|status|health]"
        exit 1
        ;;
esac
