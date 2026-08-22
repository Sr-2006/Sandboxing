param (
    [string]$Action = "up"
)

$env:CHAOS_TARGET_NAMESPACE = "shadow"

$UpRequired = @(
    "shadow-postgres-db", "shadow-redis", "shadow-rabbitmq",
    "shadow-api-gateway", "shadow-auth-service", "shadow-order-service",
    "shadow-payment-service", "shadow-otel-collector"
)

if ($Action -eq "up") {
    Write-Host "[shadow] Starting shadow stack..." -ForegroundColor Green
    docker compose -f docker-compose.yml -f docker-compose.shadow.yml up -d --build
    Write-Host "[shadow] Waiting 15s for health checks..." -ForegroundColor Yellow
    Start-Sleep -Seconds 15

    foreach ($name in $UpRequired) {
        $status = docker inspect -f '{{.State.Status}}' $name 2>$null
        $health = docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}N/A{{end}}' $name 2>$null
        Write-Host ("{0,-30} Status: {1,-10} Health: {2,-10}" -f $name, $status, $health)
    }

    foreach ($name in $UpRequired) {
        $status = docker inspect -f '{{.State.Status}}' $name 2>$null
        if ($status -ne "running") {
            Write-Host "[shadow] ERROR: $name is not running." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "[shadow] All required shadow containers are healthy." -ForegroundColor Green
}
elseif ($Action -eq "down") {
    Write-Host "[shadow] Tearing down shadow stack and ephemeral volumes..." -ForegroundColor Yellow
    docker compose -f docker-compose.yml -f docker-compose.shadow.yml down -v
    Write-Host "[shadow] Shadow stack removed." -ForegroundColor Green
}
else {
    Write-Host "Usage: .\run-shadow.ps1 -Action [up|down]" -ForegroundColor Red
    exit 1
}
