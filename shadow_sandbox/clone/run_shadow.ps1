<#
.SYNOPSIS
    Management script for Shadow Sandbox Layer 1 environment (PowerShell).
.EXAMPLE
    .\run_shadow.ps1 up
    .\run_shadow.ps1 status
    .\run_shadow.ps1 health
    .\run_shadow.ps1 down
#>

param (
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("up", "down", "status", "health")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ComposeFile = Join-Path $ScriptDir "docker-compose.shadow.yml"
$EnvFile = Join-Path $ScriptDir "env.shadow"
$NetworkName = "shadow-net"
$ObsTools = @("otel-collector", "jaeger", "prometheus")

switch ($Action.ToLower()) {
    "up" {
        Write-Host "[SHADOW] Setting up shadow network '$NetworkName'..." -ForegroundColor Cyan
        $netExists = docker network ls -q -f name="^${NetworkName}$"
        if (-not $netExists) {
            docker network create $NetworkName
            Write-Host "[SHADOW] Network '$NetworkName' created." -ForegroundColor Green
        } else {
            Write-Host "[SHADOW] Network '$NetworkName' already exists." -ForegroundColor Yellow
        }

        Write-Host "[SHADOW] Checking observability dual-homing..." -ForegroundColor Cyan
        foreach ($tool in $ObsTools) {
            $toolId = docker ps -q -f name="^/${tool}$"
            if ($toolId) {
                $insp = docker inspect $tool --format '{{json .NetworkSettings.Networks}}'
                if ($insp -notmatch $NetworkName) {
                    Write-Host "[SHADOW] Connecting '$tool' to '$NetworkName' (dual-homing)..." -ForegroundColor Cyan
                    docker network connect $NetworkName $tool
                } else {
                    Write-Host "[SHADOW] '$tool' already dual-homed." -ForegroundColor Yellow
                }
            } else {
                Write-Host "[SHADOW] Observability service '$tool' is not currently running (skipping dual-homed attach)." -ForegroundColor Yellow
            }
        }

        Write-Host "[SHADOW] Launching 7 shadow services..." -ForegroundColor Cyan
        docker compose -f $ComposeFile --env-file $EnvFile up -d --build
        Write-Host "[SHADOW] Shadow environment launched successfully." -ForegroundColor Green
    }

    "down" {
        Write-Host "[SHADOW] Stopping shadow services..." -ForegroundColor Cyan
        docker compose -f $ComposeFile --env-file $EnvFile down -v

        Write-Host "[SHADOW] Disconnecting observability tools from '$NetworkName'..." -ForegroundColor Cyan
        foreach ($tool in $ObsTools) {
            $toolId = docker ps -q -f name="^/${tool}$"
            if ($toolId) {
                $insp = docker inspect $tool --format '{{json .NetworkSettings.Networks}}'
                if ($insp -match $NetworkName) {
                    Write-Host "[SHADOW] Disconnecting '$tool' from '$NetworkName'..." -ForegroundColor Cyan
                    docker network disconnect $NetworkName $tool
                }
            }
        }

        $netExists = docker network ls -q -f name="^${NetworkName}$"
        if ($netExists) {
            Write-Host "[SHADOW] Removing network '$NetworkName'..." -ForegroundColor Cyan
            docker network rm $NetworkName
        }
        Write-Host "[SHADOW] Shadow environment completely cleaned up." -ForegroundColor Green
    }

    "status" {
        Write-Host "=== Shadow Containers ===" -ForegroundColor Cyan
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" -f name=shadow-

        Write-Host "`n=== Shadow Network Inspection ===" -ForegroundColor Cyan
        $netExists = docker network ls -q -f name="^${NetworkName}$"
        if ($netExists) {
            docker network inspect $NetworkName --format "{{range .Containers}}{{.Name}} ({{.IPv4Address}})`n{{end}}"
        } else {
            Write-Host "Network '$NetworkName' does not exist." -ForegroundColor Red
        }
    }

    "health" {
        Write-Host "=== Shadow Containers Health Status ===" -ForegroundColor Cyan
        $containers = @("shadow-postgres-db", "shadow-redis", "shadow-rabbitmq", "shadow-api-gateway", "shadow-auth-service", "shadow-order-service", "shadow-payment-service")
        foreach ($c in $containers) {
            $cid = docker ps -q -f name="^/${c}$"
            if ($cid) {
                $status = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $c
                Write-Host ("{0,-25} : {1}" -f $c, $status)
            } else {
                Write-Host ("{0,-25} : NOT RUNNING" -f $c) -ForegroundColor Red
            }
        }
    }
}
