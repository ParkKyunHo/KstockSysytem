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
#   .\hotfix.ps1 -ApplyMigration 021  # 신규 V7.1 마이그레이션 적용 (idempotent DDL)
#   .\hotfix.ps1 -ForceMarketHours    # KST 09:00~15:30 가드 우회 (의식적 결정)
#
# Constitution:
#   - .env 시크릿 마스킹 표시만, 평문 transcript 노출 X
#   - shared/.env 갱신 시 권한 600 유지
#   - systemd unit 갱신 시 백업 (.bak.YYYYMMDD)
#   - V7.1 필수 변수 (KIWOOM_ENV / KIWOOM_ACCOUNT_NO / JWT_SECRET) 사전 검증 fail-loud
#   - 장중 (KST 09:00~15:30 평일) 배포 차단 — systemd restart = WS 재연결 + 7-step 복구
# ============================================================
param(
    [switch]$NoRestart,
    [switch]$WithSystemd,
    [switch]$InitialDeploy,
    [string]$ApplyMigration = "",
    [switch]$ForceMarketHours
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
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

$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR"
# Inline arg list for direct `& ssh ...` / `& scp ...` calls (avoids
# PowerShell 5.1 NativeCommandError from native-cmd stderr wrapping).
$SSH_ARGS = @("-i", $LIGHTSAIL_KEY,
              "-o", "StrictHostKeyChecking=no",
              "-o", "UserKnownHostsFile=NUL",
              "-o", "LogLevel=ERROR")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " K_stock_trading V7.1 hotfix" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host "[ERROR] SSH key missing: $LIGHTSAIL_KEY" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# [0/6] 장중 배포 가드 (KST 09:00~15:30 평일)
# ------------------------------------------------------------
if (-not $ForceMarketHours) {
    $kst = [System.TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time")
    $now_kst = [System.TimeZoneInfo]::ConvertTime((Get-Date), $kst)
    $is_weekend = $now_kst.DayOfWeek -eq 'Saturday' -or $now_kst.DayOfWeek -eq 'Sunday'
    $market_open = [datetime]::new($now_kst.Year, $now_kst.Month, $now_kst.Day, 9, 0, 0)
    $market_close = [datetime]::new($now_kst.Year, $now_kst.Month, $now_kst.Day, 15, 30, 0)
    if (-not $is_weekend -and $now_kst -ge $market_open -and $now_kst -le $market_close) {
        Write-Host "[ERROR] 장중 배포 금지 (KST $($now_kst.ToString('yyyy-MM-dd HH:mm:ss ddd')))" -ForegroundColor Red
        Write-Host "        systemd restart = WS 재연결 + 7-step 복구 + Telegram 명령 차단 30초" -ForegroundColor Yellow
        Write-Host "        의식적 결정으로 강제하려면 -ForceMarketHours 사용" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[0/6] market hours guard OK (장 마감 또는 주말)" -ForegroundColor Green
} else {
    Write-Host "[0/6] market hours guard FORCED (-ForceMarketHours)" -ForegroundColor Yellow
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
$dest = "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}"
& scp @SSH_ARGS -r "$LOCAL_PROJECT\src" "${dest}:$REMOTE_CURRENT/"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp src failed" -ForegroundColor Red; exit 1 }
& scp @SSH_ARGS "$LOCAL_PROJECT\requirements.txt" "${dest}:$REMOTE_CURRENT/"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp requirements failed" -ForegroundColor Red; exit 1 }
# .env: send to current/ first (working ref), then mirror to shared/.env
# (systemd EnvironmentFile reads shared/.env). CLAUDE.md Part 5.1 root cause
# (V7.0 inline-comment incident) is the reason we always mirror.
& scp @SSH_ARGS "$envFile" "${dest}:$REMOTE_CURRENT/.env"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp .env failed" -ForegroundColor Red; exit 1 }
& scp @SSH_ARGS "$envFile" "${dest}:/tmp/.env.v71.staging"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp .env staging failed" -ForegroundColor Red; exit 1 }
# V7.0 current/ 에는 scripts/ 폴더 없으므로 (V7.1 첫 배포) mkdir 먼저
& ssh @SSH_ARGS $dest "mkdir -p $REMOTE_CURRENT/scripts"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] mkdir scripts failed" -ForegroundColor Red; exit 1 }
& scp @SSH_ARGS -r "$LOCAL_PROJECT\scripts\harness" "${dest}:$REMOTE_CURRENT/scripts/"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp harness failed" -ForegroundColor Red; exit 1 }

# Frontend dist (Vite + React build artifacts). main.py serves it as
# StaticFiles + SPA catch-all. Skip with warning if dist is absent so the
# code-only hotfix path keeps working.
$frontend_dist = "$LOCAL_PROJECT\frontend\dist"
if (Test-Path $frontend_dist) {
    & ssh @SSH_ARGS $dest "mkdir -p $REMOTE_CURRENT/frontend"
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] mkdir frontend failed" -ForegroundColor Red; exit 1 }
    & scp @SSH_ARGS -r "$frontend_dist" "${dest}:$REMOTE_CURRENT/frontend/"
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp frontend/dist failed" -ForegroundColor Red; exit 1 }
    Write-Host "      OK (src + requirements + .env + harness + frontend/dist)" -ForegroundColor Green
} else {
    Write-Host "      WARN: frontend/dist not found -- run 'cd frontend; npm run build' first" -ForegroundColor Yellow
    Write-Host "      OK (src + requirements + .env + harness; frontend skipped)" -ForegroundColor Green
}

# ------------------------------------------------------------
# [4/6] shared/.env mirror (with backup + perm 600)
# ------------------------------------------------------------
Write-Host "[4/6] shared/.env mirror..." -ForegroundColor Yellow
# Single-quoted here-string so PowerShell does not evaluate bash $().
$shared_template = @'
set -e
sudo cp -f REMOTE_SHARED_ENV REMOTE_BASE/shared/.env.bak.DATE_TAG 2>/dev/null || true
sudo cp -f /tmp/.env.v71.staging REMOTE_SHARED_ENV
sudo chown ubuntu:ubuntu REMOTE_SHARED_ENV
sudo chmod 600 REMOTE_SHARED_ENV
rm -f /tmp/.env.v71.staging
echo "shared/.env updated (perm $(stat -c %a REMOTE_SHARED_ENV))"
'@
$shared_mirror = $shared_template `
    -replace 'REMOTE_SHARED_ENV', $REMOTE_SHARED_ENV `
    -replace 'REMOTE_BASE', $REMOTE_BASE `
    -replace 'DATE_TAG', $DATE_TAG
# Write to a temp file with ASCII (no BOM) then scp + execute remotely.
# stdin-pipe approach lost to PowerShell 5.1 BOM injection on UTF-8 files.
$tempScript = [System.IO.Path]::GetTempFileName() + ".sh"
[System.IO.File]::WriteAllText($tempScript, $shared_mirror, [System.Text.UTF8Encoding]::new($false))
& scp @SSH_ARGS $tempScript "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/mirror.sh"
if ($LASTEXITCODE -ne 0) {
    Remove-Item $tempScript -ErrorAction SilentlyContinue
    Write-Host "[ERROR] mirror.sh scp failed (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
& ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "bash /tmp/mirror.sh && rm /tmp/mirror.sh"
$mirrorRc = $LASTEXITCODE
Remove-Item $tempScript -ErrorAction SilentlyContinue
if ($mirrorRc -ne 0) {
    Write-Host "[ERROR] shared/.env mirror failed (exit=$mirrorRc)" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# ------------------------------------------------------------
# [5a/6] InitialDeploy: venv package install (V7.1 deps)
# ------------------------------------------------------------
if ($InitialDeploy) {
    Write-Host "[5a/6] venv package install (V7.1 deps)..." -ForegroundColor Yellow
    $pip_template = @'
set -e
cd REMOTE_CURRENT
./venv/bin/pip install --upgrade pip 2>&1 | tail -2
./venv/bin/pip install -r requirements.txt 2>&1 | tail -10
./venv/bin/python -c "import uvicorn, fastapi, asyncpg, psycopg, pyotp; print('V7.1 deps OK')"
'@
    $pip_cmd = $pip_template -replace 'REMOTE_CURRENT', $REMOTE_CURRENT
    $pipScript = [System.IO.Path]::GetTempFileName() + ".sh"
    [System.IO.File]::WriteAllText($pipScript, $pip_cmd, [System.Text.UTF8Encoding]::new($false))
    & scp @SSH_ARGS $pipScript "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/pip_install.sh"
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $pipScript -ErrorAction SilentlyContinue
        Write-Host "[ERROR] pip_install.sh scp failed" -ForegroundColor Red
        exit 1
    }
    & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "bash /tmp/pip_install.sh && rm /tmp/pip_install.sh"
    $pipRc = $LASTEXITCODE
    Remove-Item $pipScript -ErrorAction SilentlyContinue
    if ($pipRc -ne 0) {
        Write-Host "[ERROR] pip install failed (exit=$pipRc)" -ForegroundColor Red
        exit 1
    }
    Write-Host "      OK" -ForegroundColor Green
}

# ------------------------------------------------------------
# [5b/6] Optional: systemd unit update (-WithSystemd)
# ------------------------------------------------------------
if ($WithSystemd) {
    Write-Host "[5b/6] systemd unit update..." -ForegroundColor Yellow
    & scp @SSH_ARGS "$LOCAL_PROJECT\scripts\deploy\v71.service" "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/v71.service"
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] scp v71.service failed" -ForegroundColor Red; exit 1 }
    $unit_template = @'
set -e
sudo cp -f /etc/systemd/system/k-stock-trading.service /etc/systemd/system/k-stock-trading.service.bak.DATE_TAG 2>/dev/null || true
sudo cp -f /tmp/v71.service /etc/systemd/system/k-stock-trading.service
sudo chmod 644 /etc/systemd/system/k-stock-trading.service
sudo systemctl daemon-reload
rm -f /tmp/v71.service
echo "systemd unit updated"
'@
    $unit_apply = $unit_template -replace 'DATE_TAG', $DATE_TAG
    $unitScript = [System.IO.Path]::GetTempFileName() + ".sh"
    [System.IO.File]::WriteAllText($unitScript, $unit_apply, [System.Text.UTF8Encoding]::new($false))
    & scp @SSH_ARGS $unitScript "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/tmp/unit_apply.sh"
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $unitScript -ErrorAction SilentlyContinue
        Write-Host "[ERROR] unit_apply.sh scp failed" -ForegroundColor Red
        exit 1
    }
    & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "bash /tmp/unit_apply.sh && rm /tmp/unit_apply.sh"
    $unitRc = $LASTEXITCODE
    Remove-Item $unitScript -ErrorAction SilentlyContinue
    if ($unitRc -ne 0) {
        Write-Host "[ERROR] systemd unit apply failed (exit=$unitRc)" -ForegroundColor Red
        exit 1
    }
    Write-Host "      OK" -ForegroundColor Green
}

# ------------------------------------------------------------
# [5c/6] Optional: V7.1 DB migration apply (-ApplyMigration NNN)
# ------------------------------------------------------------
if ($ApplyMigration -ne "") {
    Write-Host "[5c/6] V7.1 migration $ApplyMigration apply..." -ForegroundColor Yellow
    $py = "C:\Program Files\Python311\python.exe"
    if (-not (Test-Path $py)) {
        Write-Host "[ERROR] Python 3.11 missing locally: $py" -ForegroundColor Red
        exit 1
    }
    & $py "$LOCAL_PROJECT\scripts\deploy\apply_v71_migrations.py" --apply $ApplyMigration
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] migration $ApplyMigration apply failed (exit=$LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "      OK (migration $ApplyMigration applied)" -ForegroundColor Green
}

# ------------------------------------------------------------
# [6/6] Service restart + status check
# ------------------------------------------------------------
if ($NoRestart) {
    Write-Host "[6/6] service restart skipped (-NoRestart)" -ForegroundColor Yellow
} else {
    Write-Host "[6/6] service restart..." -ForegroundColor Yellow
    & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl restart k-stock-trading"
    Start-Sleep -Seconds 5
    $status = & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl is-active k-stock-trading"
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
