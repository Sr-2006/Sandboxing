<#
.SYNOPSIS
  Starts a FREE Cloudflare quick tunnel (no account needed) that exposes one
  phase's local service to all other laptops over HTTPS.

.DESCRIPTION
  Prints a public https://*.trycloudflare.com URL. Share that URL with the team
  (paste it into federation/.env.federation). The tunnel is NAT-proof: no port
  forwarding, no firewall changes, no static IPs.

.EXAMPLE
  .\federation\start-tunnel.ps1 -Phase phase2
  .\federation\start-tunnel.ps1 -Phase phase3 -Port 11434
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("phase1", "phase2", "phase3", "phase4")]
    [string]$Phase,

    # Override the default local port for the phase
    [int]$Port = 0
)

$defaults = @{
    phase1 = 8090    # federation/serve_dataset.py (Phase 1 dataset endpoint)
    phase2 = 8000    # chroma run (Phase 2 ChromaDB)
    phase3 = 8001    # FastMCP SSE servers (use -Port 11434 for Ollama)
    phase4 = 8002    # Phase 4 veto/security gateway
}
if ($Port -eq 0) { $Port = $defaults[$Phase] }

$exe = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $exe) {
    Write-Host "cloudflared not found - installing via winget..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e
    Write-Host "Installed. Open a NEW terminal and re-run this script." -ForegroundColor Green
    exit 1
}

# Fail fast if nothing is listening locally
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    Write-Host "WARNING: nothing is listening on localhost:$Port yet." -ForegroundColor Yellow
    Write-Host "Start the $Phase service first (see federation/SETUP_GUIDE.md)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Exposing http://localhost:$Port ($Phase) via free Cloudflare quick tunnel..." -ForegroundColor Cyan
Write-Host "Copy the https://*.trycloudflare.com URL printed below into federation/.env.federation" -ForegroundColor Cyan
Write-Host ""
cloudflared tunnel --no-autoupdate --url "http://localhost:$Port"
