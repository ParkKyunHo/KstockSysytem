# ============================================================
# V7.1 P-Wire-Box-1 invariant verification (배포 직전 운영자 실행)
# ============================================================
# Purpose:
#   P-Wire-Box-1 land 후 P-Wire-Box-2 land 전까지 자금 안전 invariant 검증.
#   feature_flags.yaml 주석에 명시된 5 flag (자동 매수 발화 경로)가
#   모두 false 유지되는지 확인. 위반 시 exit 1 → 배포 중단.
#
# Usage:
#   .\check_invariants.ps1                    # 모든 검증
#   .\check_invariants.ps1 -SkipMarketHours   # 장중 가드 건너뛰기
#   .\check_invariants.ps1 -SkipDb            # DB 검증 건너뛰기 (네트워크 X)
#
# Exit codes:
#   0 = 전부 통과
#   1 = invariant 위반 (배포 금지)
# ============================================================
param(
    [switch]$SkipMarketHours,
    [switch]$SkipDb
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Continue"

$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$REMOTE_BASE = "/home/ubuntu/K_stock_trading"
$LOCAL_PROJECT = "C:\K_stock_trading"

$SSH_ARGS = @("-i", $LIGHTSAIL_KEY,
              "-o", "StrictHostKeyChecking=no",
              "-o", "UserKnownHostsFile=NUL",
              "-o", "LogLevel=ERROR")

# P-Wire-Box-1 INVARIANT — feature_flags.yaml 주석과 동기화 필수.
# 이 5 flag가 동시에 false 유지되어야 자동 매수 발화 경로 차단.
$INVARIANT_FLAGS = @(
    "box_entry_detector",
    "pullback_strategy",
    "breakout_strategy",
    "path_b_daily",
    "buy_executor_v71"
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 P-Wire-Box-1 invariant check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$violations = @()
$pass = 0

# ------------------------------------------------------------
# [1] 장중 배포 가드 (KST 09:00~15:30)
# ------------------------------------------------------------
if (-not $SkipMarketHours) {
    Write-Host ""
    Write-Host "[1] Market hours guard (KST 09:00~15:30)..." -ForegroundColor Yellow
    $kst = [System.TimeZoneInfo]::FindSystemTimeZoneById("Korea Standard Time")
    $now_kst = [System.TimeZoneInfo]::ConvertTime((Get-Date), $kst)
    Write-Host "      Current KST: $($now_kst.ToString('yyyy-MM-dd HH:mm:ss ddd'))"
    $is_weekend = $now_kst.DayOfWeek -eq 'Saturday' -or $now_kst.DayOfWeek -eq 'Sunday'
    $market_open = New-Object System.DateTime $now_kst.Year, $now_kst.Month, $now_kst.Day, 9, 0, 0
    $market_close = New-Object System.DateTime $now_kst.Year, $now_kst.Month, $now_kst.Day, 15, 30, 0
    if (-not $is_weekend -and $now_kst -ge $market_open -and $now_kst -le $market_close) {
        $violations += "장중 배포 금지 (KST $($now_kst.ToString('HH:mm'))). -SkipMarketHours로 강제 가능."
        Write-Host "      VIOLATION (장중)" -ForegroundColor Red
    } else {
        Write-Host "      OK (장 마감 또는 주말)" -ForegroundColor Green
        $pass++
    }
} else {
    Write-Host ""
    Write-Host "[1] Market hours guard SKIPPED (-SkipMarketHours)" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# [2] Local feature_flags.yaml invariant
# ------------------------------------------------------------
Write-Host ""
Write-Host "[2] Local feature_flags.yaml invariant..." -ForegroundColor Yellow
$yaml_path = "$LOCAL_PROJECT\config\feature_flags.yaml"
if (-not (Test-Path $yaml_path)) {
    $violations += "feature_flags.yaml not found locally"
    Write-Host "      VIOLATION (file missing)" -ForegroundColor Red
} else {
    $yaml_content = Get-Content $yaml_path -Raw
    $local_violations = @()
    foreach ($flag in $INVARIANT_FLAGS) {
        if ($yaml_content -match "(?m)^\s*${flag}:\s*true") {
            $local_violations += "${flag}=true (must be false)"
        }
    }
    if ($local_violations.Count -gt 0) {
        $violations += "Local yaml invariant violated: $($local_violations -join '; ')"
        Write-Host "      VIOLATION ($($local_violations -join ', '))" -ForegroundColor Red
    } else {
        Write-Host "      OK (5 invariant flags all false)" -ForegroundColor Green
        $pass++
    }
}

# ------------------------------------------------------------
# [3] AWS shared/.env env-override invariant
# ------------------------------------------------------------
if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host ""
    Write-Host "[3] AWS env override SKIPPED (no SSH key)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "[3] AWS shared/.env env-override invariant..." -ForegroundColor Yellow
    # V71_FF__V71__<UPPER_FLAG>=true 형태 가능. 5 flag UPPERCASE 변환.
    $env_keys = $INVARIANT_FLAGS | ForEach-Object {
        "V71_FF__V71__$(($_).ToUpper())"
    }
    $grep_pattern = ($env_keys -join '|')
    $remote_env = "$REMOTE_BASE/shared/.env"
    $env_check = & ssh @SSH_ARGS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" `
        "sudo grep -E '^($grep_pattern)=' $remote_env 2>/dev/null | grep -i 'true' || echo 'NONE_TRUE'"
    if ($env_check -match 'NONE_TRUE' -or [string]::IsNullOrWhiteSpace($env_check)) {
        Write-Host "      OK (no env override sets invariant flags to true)" -ForegroundColor Green
        $pass++
    } else {
        $violations += "AWS env override violation: $env_check"
        Write-Host "      VIOLATION: $env_check" -ForegroundColor Red
    }
}

# ------------------------------------------------------------
# [4] DB support_boxes row count + idx_boxes_active 정의
# ------------------------------------------------------------
if (-not $SkipDb) {
    Write-Host ""
    Write-Host "[4] DB support_boxes inspection..." -ForegroundColor Yellow
    $py = "C:\Program Files\Python311\python.exe"
    if (-not (Test-Path $py)) {
        Write-Host "      SKIP (Python 3.11 missing locally)" -ForegroundColor Yellow
    } else {
        $diag = & $py "$LOCAL_PROJECT\scripts\deploy\apply_v71_migrations.py" `
            --check 021 --verify-box-active-index 2>&1
        Write-Host $diag
        # rc 0 = idx 정합 OK. rc 1 = idx 미land 또는 정의 불일치.
        if ($LASTEXITCODE -eq 0) {
            Write-Host "      OK (idx_boxes_active aligned)" -ForegroundColor Green
            $pass++
        } else {
            $violations += "idx_boxes_active not aligned with PRD §2.2 (run apply_v71_migrations.py --apply 021)"
            Write-Host "      VIOLATION (run apply --apply 021)" -ForegroundColor Red
        }
    }
} else {
    Write-Host ""
    Write-Host "[4] DB inspection SKIPPED (-SkipDb)" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
if ($violations.Count -eq 0) {
    Write-Host " RESULT: PASS ($pass checks)" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    exit 0
} else {
    Write-Host " RESULT: FAIL ($($violations.Count) violations)" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    foreach ($v in $violations) {
        Write-Host "   - $v" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "P-Wire-Box-1 INVARIANT (config/feature_flags.yaml 주석):" -ForegroundColor Yellow
    Write-Host "   P-Wire-Box-2 land 전까지 다음 5 flag false 유지:" -ForegroundColor Yellow
    Write-Host "   $($INVARIANT_FLAGS -join ', ')" -ForegroundColor Yellow
    exit 1
}
