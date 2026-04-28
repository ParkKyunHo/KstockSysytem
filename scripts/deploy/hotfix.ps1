# ============================================================
# K_stock_trading V7.1 hotfix deploy (V7.0 launcher 폐기 후 갱신)
# ============================================================
# Phase: 운영 진입 Step 3 (V7.1 코드 배포)
#
# 사용법:
#   .\hotfix.ps1                      # 코드 + .env 전송 + 서비스 재시작
#   .\hotfix.ps1 -NoRestart           # 파일만 전송
#   .\hotfix.ps1 -WithSystemd         # v71.service 적용 + daemon-reload
#   .\hotfix.ps1 -InitialDeploy       # 첫 V7.1 배포 (venv 패키지 설치 포함)
#
# Constitution:
#   - .env 시크릿 마스킹 표시만, 평문 transcript 노출 X
#   - shared/.env 갱신 시 권한 600 유지
#   - systemd unit 갱신 시 백업 (.bak.YYYYMMDD)
#   - V7.1 필수 변수 (KIWOOM_ENV / KIWOOM_ACCOUNT_NO / JWT_SECRET) 사전 검증 fail-loud
# ============================================================
param(
    [switch]$NoRestart,
    [switch]$WithSystemd,
    [switch]$InitialDeploy
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$LOCAL_PROJECT = "C:\K_stock_trading"
$REMOTE_BASE = "/home/ubuntu/K_stock_trading"
$REMOTE_CURRENT = "$REMOTE_BASE/current"
$REMOTE_SHARED_ENV = "$REMOTE_BASE/shared/.env"
$DATE_TAG = Get-Date -Format "yyyyMMdd"

$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " K_stock_trading V7.1 hotfix" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host "[ERROR] SSH key missing: $LIGHTSAIL_KEY" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# [1/6] V7.1 .env 필수 변수 사전 검증 (실거래 fail-loud)
# ------------------------------------------------------------
Write-Host "[1/6] .env V7.1 prerequisites..." -ForegroundColor Yellow
$envFile = "$LOCAL_PROJECT\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] .env not found: $envFile" -ForegroundColor Red
    exit 1
}
$required_v71 = @(
    "KIWOOM_APP_KEY", "KIWOOM_APP_SECRET",
    "KIWOOM_ENV", "KIWOOM_ACCOUNT_NO",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "DATABASE_URL", "JWT_SECRET"
)
$missing = @()
foreach ($k in $required_v71) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^$k=(.+)$" } | Select-Object -First 1
    if ($null -eq $line) {
        $missing += $k
    } else {
        $val = ($matches[1] -replace "\s*#.*$", "").Trim()
        if ($val.Length -eq 0) { $missing += "$k(EMPTY)" }
    }
}
if ($missing.Count -gt 0) {
    Write-Host "[ERROR] missing V7.1 secrets: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "         Refer to .env.v71.example to fill them in." -ForegroundColor Red
    exit 1
}
Write-Host "      OK ($($required_v71.Count) keys present)" -ForegroundColor Green

# ------------------------------------------------------------
# [2/6] V7.1 import smoke (local)
# ------------------------------------------------------------
Write-Host "[2/6] V7.1 import smoke..." -ForegroundColor Yellow
& "C:\Program Files\Python311\python.exe" -c "import src.web.v71.main; import src.web.v71.trading_bridge"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] V7.1 import smoke failed" -ForegroundColor Red
    exit 1
}
Write-Host "      OK (src.web.v71.main + trading_bridge)" -ForegroundColor Green

# ------------------------------------------------------------
# [3/6] Code transfer (src/ + .env + requirements.txt + scripts/harness)
# ------------------------------------------------------------
Write-Host "[3/6] code transfer..." -ForegroundColor Yellow
$scp_src = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS -r `"$LOCAL_PROJECT\src`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/`""
Invoke-Expression $scp_src 2>$null
$scp_req = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$LOCAL_PROJECT\requirements.txt`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/`""
Invoke-Expression $scp_req 2>$null
# .env: send to current/ first (working ref), then mirror to shared/.env
# (systemd EnvironmentFile reads shared/.env). CLAUDE.md Part 5.1 root cause
# (V7.0 inline-comment incident) is the reason we always mirror.
$scp_env = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$envFile`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/.env`""
Invoke-Expression $scp_env 2>$null
$scp_envtmp = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$envFile`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/.env.v71.staging`""
Invoke-Expression $scp_envtmp 2>$null
$scp_harness = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS -r `"$LOCAL_PROJECT\scripts\harness`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/scripts/`""
Invoke-Expression $scp_harness 2>$null
Write-Host "      OK (src + requirements + .env + harness)" -ForegroundColor Green

# ------------------------------------------------------------
# [4/6] shared/.env mirror (with backup + perm 600)
# ------------------------------------------------------------
Write-Host "[4/6] shared/.env mirror..." -ForegroundColor Yellow
$shared_mirror = @"
set -e
sudo cp -f $REMOTE_SHARED_ENV $REMOTE_BASE/shared/.env.bak.$DATE_TAG 2>/dev/null || true
sudo cp -f /tmp/.env.v71.staging $REMOTE_SHARED_ENV
sudo chown ubuntu:ubuntu $REMOTE_SHARED_ENV
sudo chmod 600 $REMOTE_SHARED_ENV
rm -f /tmp/.env.v71.staging
echo "shared/.env updated (perm $(stat -c %a $REMOTE_SHARED_ENV))"
"@
$ssh_mirror = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"$shared_mirror`""
Invoke-Expression $ssh_mirror
Write-Host "      OK" -ForegroundColor Green

# ------------------------------------------------------------
# [5a/6] InitialDeploy: venv package install (V7.1 deps)
# ------------------------------------------------------------
if ($InitialDeploy) {
    Write-Host "[5a/6] venv package install (V7.1 deps)..." -ForegroundColor Yellow
    $pip_cmd = @"
set -e
cd $REMOTE_CURRENT
./venv/bin/pip install --upgrade pip 2>&1 | tail -2
./venv/bin/pip install -r requirements.txt 2>&1 | tail -10
./venv/bin/python -c "import uvicorn, fastapi, asyncpg, psycopg, pyotp; print('V7.1 deps OK')"
"@
    $ssh_pip = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"$pip_cmd`""
    Invoke-Expression $ssh_pip
    Write-Host "      OK" -ForegroundColor Green
}

# ------------------------------------------------------------
# [5b/6] Optional: systemd unit update (-WithSystemd)
# ------------------------------------------------------------
if ($WithSystemd) {
    Write-Host "[5b/6] systemd unit update..." -ForegroundColor Yellow
    $scp_unit = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$LOCAL_PROJECT\scripts\deploy\v71.service`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/v71.service`""
    Invoke-Expression $scp_unit 2>$null
    $unit_apply = @"
set -e
sudo cp -f /etc/systemd/system/k-stock-trading.service /etc/systemd/system/k-stock-trading.service.bak.$DATE_TAG 2>/dev/null || true
sudo cp -f /tmp/v71.service /etc/systemd/system/k-stock-trading.service
sudo chmod 644 /etc/systemd/system/k-stock-trading.service
sudo systemctl daemon-reload
rm -f /tmp/v71.service
echo "systemd unit updated"
"@
    $ssh_unit = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"$unit_apply`""
    Invoke-Expression $ssh_unit
    Write-Host "      OK" -ForegroundColor Green
}

# ------------------------------------------------------------
# [6/6] Service restart + status check
# ------------------------------------------------------------
if ($NoRestart) {
    Write-Host "[6/6] service restart skipped (-NoRestart)" -ForegroundColor Yellow
} else {
    Write-Host "[6/6] service restart..." -ForegroundColor Yellow
    $ssh_restart = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"sudo systemctl restart k-stock-trading`""
    Invoke-Expression $ssh_restart
    Start-Sleep -Seconds 5
    $status = & ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl is-active k-stock-trading"
    if ($status -eq "active") {
        Write-Host "      OK (active)" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] service start failed (status=$status)" -ForegroundColor Red
        Write-Host "        check: journalctl -u k-stock-trading -n 50 --no-pager" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " V7.1 hotfix complete" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
