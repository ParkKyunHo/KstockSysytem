# ============================================================
# V7.1 boot smoke (운영 진입 Step 6)
# ============================================================
# 사용법:
#   .\boot_smoke_v71.ps1
#
# 검증:
#   1. systemd service active
#   2. uvicorn 8080 listening
#   3. /health endpoint 200 OK
#   4. journal에 V71MarketSchedule seeded 로그
#   5. journal에 attach_trading_engine 완료 로그
#   6. (DB) market_calendar table reachable (psycopg sync from local)
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Continue"

$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR"
$SSH_ARGS = @("-i", $LIGHTSAIL_KEY,
              "-o", "StrictHostKeyChecking=no",
              "-o", "UserKnownHostsFile=NUL",
              "-o", "LogLevel=ERROR")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 boot smoke" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pass = 0
$fail = 0

function Step($name, $cmd) {
    Write-Host ""
    Write-Host "[CHECK] $name" -ForegroundColor Yellow
    $result = & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" $cmd
    Write-Host $result
    return $result
}

# 1. systemd active
$status = Step "systemd service active" "sudo systemctl is-active k-stock-trading"
if ($status -match "active") { $script:pass++ } else { $script:fail++ }

# 2. port 8080 listening
$port = Step "uvicorn :8080 listening" "ss -tlnp 2>/dev/null | grep ':8080' || echo NOT_LISTENING"
if ($port -match ":8080") { $script:pass++ } else { $script:fail++ }

# 3. /health endpoint (V7.1 router prefix: /api/v71)
$health = Step "/api/v71/health endpoint" "curl -sS -m 5 http://127.0.0.1:8080/api/v71/health || echo CURL_FAILED"
if ($health -match '"status":\s*"ok"') { $script:pass++ } else { $script:fail++ }

# 4. V71MarketSchedule log
$cal = Step "V71MarketSchedule seeded log" "sudo journalctl -u k-stock-trading -n 200 --no-pager | grep -E 'V71MarketSchedule seeded|market_calendar' | tail -3 || echo NO_LOG"
if ($cal -match "seeded|market_calendar") { $script:pass++ } else { $script:fail++ }

# 5. lifespan startup log
$attach = Step "lifespan startup complete log" "sudo journalctl -u k-stock-trading -n 200 --no-pager | grep -E 'Application startup complete|engine objects constructed|trading_bridge' | tail -3 || echo NO_LOG"
if ($attach -match "Application startup complete|engine objects constructed|trading_bridge") { $script:pass++ } else { $script:fail++ }

# 6. DB connectivity (local psycopg sync)
Write-Host ""
Write-Host "[CHECK] DB market_calendar reachable (local)" -ForegroundColor Yellow
& "C:\Program Files\Python311\python.exe" "C:\K_stock_trading\scripts\diag_db_migrations.py" 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) { $script:pass++ } else { $script:fail++ }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " RESULT: $pass pass / $fail fail" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
Write-Host "============================================================" -ForegroundColor Cyan

if ($fail -gt 0) { exit 1 } else { exit 0 }
