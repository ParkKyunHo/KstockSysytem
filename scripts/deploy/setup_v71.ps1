# ============================================================
# V7.1 first-time deploy master (운영 진입 Step 2 + 3 + 5 + 6)
# ============================================================
# 사용법 (.env에 V7.1 시크릿 입력 완료 후 한 번 실행):
#   .\setup_v71.ps1                 # archive + 코드 배포 + venv + systemd + start + smoke
#   .\setup_v71.ps1 -SkipArchive    # archive 건너뛰기 (재배포 시)
#   .\setup_v71.ps1 -NoStart        # 코드 + systemd 적용만, service start X
#   .\setup_v71.ps1 -RemoveV70      # archive 후 V7.0 releases 폴더 삭제
#
# 흐름:
#   1. 로컬 V7.1 회귀 + harness (사전 검증, 사용자 신뢰 보장)
#   2. AWS V7.0 release archive (-SkipArchive 시 생략)
#   3. service stop (코드 + systemd 갱신 안전성)
#   4. hotfix.ps1 -InitialDeploy -WithSystemd (코드 + venv + systemd unit + .env)
#   5. service start
#   6. boot_smoke_v71.ps1
# ============================================================
param(
    [switch]$SkipArchive,
    [switch]$NoStart,
    [switch]$RemoveV70
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

$LOCAL = "C:\K_stock_trading"
$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 first-time deploy master" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# [1/6] local V7.1 regression + harness (gating)
# ------------------------------------------------------------
Write-Host "[1/6] local V7.1 regression + harness..." -ForegroundColor Yellow
& "C:\Program Files\Python311\python.exe" -m pytest "$LOCAL\tests\v71" -q --tb=line 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] V7.1 regression failed -- abort" -ForegroundColor Red
    exit 1
}
& "C:\Program Files\Python311\python.exe" "$LOCAL\scripts\harness\run_all.py" 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] V7.1 harness failed -- abort" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# ------------------------------------------------------------
# [2/6] AWS V7.0 archive
# ------------------------------------------------------------
if (-not $SkipArchive) {
    Write-Host ""
    Write-Host "[2/6] AWS V7.0 archive..." -ForegroundColor Yellow
    if ($RemoveV70) {
        & powershell -ExecutionPolicy Bypass -File "$LOCAL\scripts\deploy\aws_archive_v70.ps1" -RemoveOriginal
    } else {
        & powershell -ExecutionPolicy Bypass -File "$LOCAL\scripts\deploy\aws_archive_v70.ps1"
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] V7.0 archive failed -- abort" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[2/6] AWS V7.0 archive skipped" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# [3/6] service stop
# ------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] service stop (safety)..." -ForegroundColor Yellow
& ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl stop k-stock-trading 2>&1 || true"
Write-Host "      OK" -ForegroundColor Green

# ------------------------------------------------------------
# [4/6] hotfix -InitialDeploy -WithSystemd -NoRestart
# ------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] code + venv deps + systemd unit..." -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File "$LOCAL\scripts\deploy\hotfix.ps1" -InitialDeploy -WithSystemd -NoRestart
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] V7.1 deploy failed -- abort" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# [5/6] service start
# ------------------------------------------------------------
if ($NoStart) {
    Write-Host ""
    Write-Host "[5/6] service start skipped (-NoStart)" -ForegroundColor Yellow
    Write-Host "      manual start: ssh ... 'sudo systemctl start k-stock-trading'" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "[5/6] service start..." -ForegroundColor Yellow
& ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl start k-stock-trading"
Start-Sleep -Seconds 8

# ------------------------------------------------------------
# [6/6] boot smoke
# ------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] boot smoke..." -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File "$LOCAL\scripts\deploy\boot_smoke_v71.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host " V7.1 setup completed BUT smoke check has failures." -ForegroundColor Red
    Write-Host " Check journal: scripts\deploy\check_logs.ps1 50" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " V7.1 deploy + boot smoke complete" -ForegroundColor Green
Write-Host " Next: feature_flags.yaml 단계적 활성화 (Step 7, 사용자 승인)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
