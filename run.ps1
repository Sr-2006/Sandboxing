# ==============================================================================
# Auto-SRE Platform Phase 1 - Master Automation Script
# Cleanly tears down, builds, starts microservices stack and launches background daemons
# ==============================================================================

Write-Host "=== [Auto-SRE Phase 1] Starting Stack Orchestration ===" -ForegroundColor Cyan

# 0. Ensure .env exists (compose requires JWT_SECRET / CHAOS_SECRET / DB creds)
if (-not (Test-Path .env)) {
    if (Test-Path .env.example) {
        Write-Host "[!] .env not found. Copying .env.example to .env..." -ForegroundColor Yellow
        Copy-Item .env.example .env
    } else {
        Write-Host "[-] Error: .env.example missing." -ForegroundColor Red
        exit 1
    }
}

# 1. Environment Variables - Load from .env
$env:ENABLE_CHAOS = "false"

# Load ENABLE_CHAOS / CHAOS_SECRET / TARGET_HOST / INTERNAL_SERVICE_TOKEN from .env
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*(ENABLE_CHAOS|CHAOS_SECRET|TARGET_HOST|INTERNAL_SERVICE_TOKEN|REDIS_PASSWORD)\s*=\s*(.+)\s*$') {
        Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2].Trim()
    }
}

# Preflight: Check Available RAM (Guardrail for 16GB systems)
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1024 / 1024, 2)
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1024 / 1024, 2)
    Write-Host "[*] System RAM: ${freeGB} GB free / ${totalGB} GB total" -ForegroundColor Cyan
    if ($freeGB -lt 6.0) {
        Write-Host "[!] WARNING: Free RAM is ${freeGB} GB (< 6.0 GB recommended). Docker stack + chaos simulations may stress memory." -ForegroundColor Yellow
        Write-Host "    Consider closing background applications if you experience container OOMs." -ForegroundColor Gray
    }
} catch {
    # Fallback silently
}

# FIX C6: Hard fail if chaos is enabled with placeholder / insecure tokens
if ($env:ENABLE_CHAOS -eq "true" -and ($env:CHAOS_SECRET -eq "dev-chaos-token" -or $env:CHAOS_SECRET -eq "CHANGE_ME_chaos_secret")) {
    Write-Host "[-] ERROR: ENABLE_CHAOS is true but CHAOS_SECRET is set to a default/insecure placeholder ('$($env:CHAOS_SECRET)')." -ForegroundColor Red
    Write-Host "    Please set a secure, non-default CHAOS_SECRET in .env before enabling chaos." -ForegroundColor Red
    exit 1
}

# 2. Stop Existing Daemons & Clean Containers
Write-Host "`n[1/4] Stopping and removing existing containers/volumes..." -ForegroundColor Yellow
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'continuous_telemetry\.py|frontend_data_sync\.py|monitor_ram\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
docker compose down -v --remove-orphans

# 3. Build and Start Full Docker Stack
Write-Host "`n[2/4] Building and launching Docker services..." -ForegroundColor Yellow
docker compose up -d --build

# 4. Wait for Service Health Checks
Write-Host "`n[3/4] Waiting for all microservices and infra containers to be healthy..." -ForegroundColor Yellow
$maxAttempts = 24
$attempt = 0
$allHealthy = $false

while ($attempt -lt $maxAttempts) {
    Start-Sleep -Seconds 5
    $attempt++
    
    # Get statuses
    $unhealthy = docker ps --filter "health=unhealthy" --format "{{.Names}}"
    $starting = docker ps --filter "health=starting" --format "{{.Names}}"
    
    if (-not $unhealthy -and -not $starting) {
        $allHealthy = $true
        break
    }
    Write-Host "    Attempt ${attempt}/${maxAttempts}: Waiting for services to initialize..." -ForegroundColor Gray
}

if ($allHealthy) {
    Write-Host "[+] All services initialized and healthy!" -ForegroundColor Green
} else {
    Write-Host "[!] Warning: Some services may still be starting or reporting health status." -ForegroundColor DarkYellow
}

# 5. Launch Background Python Telemetry & Monitoring Daemons
Write-Host "`n[4/4] Launching background telemetry and monitoring daemons..." -ForegroundColor Yellow

# Terminate any previously running background jobs for these scripts
Get-Job | Where-Object { $_.Name -like "AutoSRE_*" } | Stop-Job -PassThru | Remove-Job

$job1 = Start-Job -Name "AutoSRE_Telemetry" -ScriptBlock {
    Set-Location $using:PWD
    python continuous_telemetry.py
}
Write-Host "    -> Started continuous_telemetry.py (Job ID: $($job1.Id))" -ForegroundColor Green

$job2 = Start-Job -Name "AutoSRE_Sync" -ScriptBlock {
    Set-Location $using:PWD
    python frontend_data_sync.py
}
Write-Host "    -> Started frontend_data_sync.py (Job ID: $($job2.Id))" -ForegroundColor Green

$job3 = Start-Job -Name "AutoSRE_RAMMonitor" -ScriptBlock {
    Set-Location $using:PWD
    python monitor_ram.py
}
Write-Host "    -> Started monitor_ram.py (Job ID: $($job3.Id))" -ForegroundColor Green

# Save active job PIDs and IDs to jobs.lck
$jobInfo = @(
    "AutoSRE_Telemetry,$($job1.Id),$($job1.State)",
    "AutoSRE_Sync,$($job2.Id),$($job2.State)",
    "AutoSRE_RAMMonitor,$($job3.Id),$($job3.State)"
)
$jobInfo | Out-File -FilePath "jobs.lck" -Encoding utf8

# Check job health after 3 seconds
Start-Sleep -Seconds 3
$failedJobs = Get-Job | Where-Object { $_.Name -like "AutoSRE_*" -and $_.State -ne "Running" }
if ($failedJobs) {
    foreach ($fj in $failedJobs) {
        Write-Host "[!] WARNING: Background daemon '$($fj.Name)' exited prematurely with state: $($fj.State)" -ForegroundColor Red
    }
} else {
    Write-Host "[+] All background daemons running smoothly." -ForegroundColor Green
}

# 6. Display Stack Summary
Write-Host "`n==============================================================================" -ForegroundColor Cyan
Write-Host " Auto-SRE Phase 1 Platform Operational Summary" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host "`n[+] Pipeline ready! To trigger log clustering and packaging at any time, run:" -ForegroundColor Green
Write-Host "    python phase1_processor.py; python package_ml_dataset.py" -ForegroundColor White
Write-Host "`n[+] To inject a random chaos scenario, run:" -ForegroundColor Green
Write-Host "    python chaos_scenarios.py --once`n" -ForegroundColor White
