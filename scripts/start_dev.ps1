# scripts/start_dev.ps1
#
# Local dev environment launcher. Starts the V7.1 backend (8080) +
# vite frontend (5173) together so the developer doesn't have to
# remember two commands. Production deploy is *separate* — this
# script never touches AWS Lightsail.
#
# Usage:
#   1. Right-click this file → "Run with PowerShell", or
#   2. Open PowerShell at repo root and run:
#        powershell -ExecutionPolicy Bypass -File scripts\start_dev.ps1
#
# What it does:
#   1. Stop any stale processes still bound to 8080 / 5173
#   2. Start backend (dev_run_local.py) in a NEW PowerShell window
#      so its logs stay visible + you can Ctrl+C it independently
#   3. Wait ~6 s for FastAPI to come up
#   4. Start frontend (npm run dev) in THIS window (foreground)
#
# Login: admin / admin (no TOTP, SQLite at data/dev.db, trading
# engine OFF).

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " V7.1 dev environment - backend + frontend" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------
# 1. Free 8080 / 5173 if a stale dev process is still bound
# ---------------------------------------------------------------
foreach ($port in 8080, 5173) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        Write-Host "[cleanup] killing stale process on port $port (PID $($c.OwningProcess))" -ForegroundColor Yellow
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 500

# ---------------------------------------------------------------
# 2. Start backend in a new window
# ---------------------------------------------------------------
$pythonExe = "C:\Program Files\Python311\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "[ERROR] Python 3.11 not found at $pythonExe" -ForegroundColor Red
    exit 1
}
$backendScript = Join-Path $repoRoot "scripts\dev_run_local.py"
if (-not (Test-Path $backendScript)) {
    Write-Host "[ERROR] $backendScript missing" -ForegroundColor Red
    exit 1
}

Write-Host "[1/2] Starting backend (8080) in a new PowerShell window..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "Set-Location '$repoRoot'; & '$pythonExe' '$backendScript'"
) -WindowStyle Normal

# ---------------------------------------------------------------
# 3. Wait for backend boot (typical: 5-8s incl. dev_seed)
# ---------------------------------------------------------------
Write-Host "[wait] giving backend ~6 s to boot..." -ForegroundColor DarkGray
Start-Sleep -Seconds 6

# ---------------------------------------------------------------
# 4. Start frontend in this window (foreground)
# ---------------------------------------------------------------
Write-Host "[2/2] Starting frontend (5173) in this window..." -ForegroundColor Green
Write-Host "      Login: admin / admin" -ForegroundColor Yellow
Write-Host "      Open: http://localhost:5173" -ForegroundColor Yellow
Write-Host ""
Set-Location (Join-Path $repoRoot "frontend")
npm run dev
