<#
.SYNOPSIS
    Root wrapper script for Shadow Sandbox lifecycle management.
#>
param (
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("up", "down", "status", "health")]
    [string]$Action = "up"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetScript = Join-Path $ScriptDir "clone\run_shadow.ps1"
& $TargetScript -Action $Action
