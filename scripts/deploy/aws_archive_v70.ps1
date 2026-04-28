# ============================================================
# AWS Lightsail V7.0 archive 정리 (운영 진입 Step 2)
# ============================================================
# Phase: V7.0 release 폴더를 tar.gz로 archive 후 사용자 확인 받고 원본 정리.
#
# 사용법:
#   .\aws_archive_v70.ps1                # archive 생성 + 디스크 사용량 보고
#   .\aws_archive_v70.ps1 -RemoveOriginal  # archive 후 V7.0 releases 폴더 삭제
#
# 보존:
#   - shared/.env (V7.1 사용)
#   - shared/data/ (V7.0 운영 데이터)
#   - shared/logs/ (V7.0 로그)
#   - venv/ (V7.1 그대로 사용 — Python 3.11 + V7.1 deps 추가)
#
# Archive:
#   - releases/v2025.12.14.001 (V7.0 빌드 #1)
#   - releases/v2025.12.14.002 (V7.0 빌드 #2, current가 가리키는 곳)
# ============================================================
param(
    [switch]$RemoveOriginal
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$REMOTE_BASE = "/home/ubuntu/K_stock_trading"
$DATE_TAG = Get-Date -Format "yyyyMMdd"

$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR"
$SSH_ARGS = @("-i", $LIGHTSAIL_KEY,
              "-o", "StrictHostKeyChecking=no",
              "-o", "UserKnownHostsFile=NUL",
              "-o", "LogLevel=ERROR")
$dest = "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AWS Lightsail V7.0 archive" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host "[ERROR] SSH key missing: $LIGHTSAIL_KEY" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# [1/4] Pre-check: service must be inactive
# ------------------------------------------------------------
Write-Host "[1/4] service inactive check..." -ForegroundColor Yellow
$status = & ssh @SSH_ARGS $dest "sudo systemctl is-active k-stock-trading || echo inactive"
if ($status -eq "active") {
    Write-Host "[ERROR] service is active -- stop it first (sudo systemctl stop k-stock-trading)" -ForegroundColor Red
    exit 1
}
Write-Host "      OK (status=$status)" -ForegroundColor Green

# ------------------------------------------------------------
# [2/4] disk usage before
# ------------------------------------------------------------
Write-Host "[2/4] disk usage (before)..." -ForegroundColor Yellow
$df_before = & ssh @SSH_ARGS $dest "df -h /home/ubuntu | tail -1; du -sh $REMOTE_BASE/releases/* 2>/dev/null"
Write-Host $df_before
Write-Host ""

# ------------------------------------------------------------
# [3/4] tar.gz archive
# ------------------------------------------------------------
Write-Host "[3/4] tar.gz archive..." -ForegroundColor Yellow
# Build the bash command via single-quoted here-string so PowerShell
# does not try to evaluate $() / $var. Inject DATE_TAG via -replace.
$archive_cmd_template = @'
set -e
cd REMOTE_BASE_PLACEHOLDER
mkdir -p archive
for r in releases/v2025.12.14.*; do
    [ -d "$r" ] || continue
    bn=$(basename "$r")
    if [ -f "archive/v70_${bn}_DATE_TAG_PLACEHOLDER.tar.gz" ]; then
        echo "  already archived: archive/v70_${bn}_DATE_TAG_PLACEHOLDER.tar.gz"
        continue
    fi
    echo "  archiving $r ..."
    tar -czf "archive/v70_${bn}_DATE_TAG_PLACEHOLDER.tar.gz" -C releases "$bn"
    echo "    size=$(du -sh archive/v70_${bn}_DATE_TAG_PLACEHOLDER.tar.gz | cut -f1)"
done
echo "=== ARCHIVE LIST ==="
ls -lh archive/ | tail -20
'@
$archive_cmd = $archive_cmd_template `
    -replace 'REMOTE_BASE_PLACEHOLDER', $REMOTE_BASE `
    -replace 'DATE_TAG_PLACEHOLDER', $DATE_TAG
$archive_cmd | & ssh @SSH_ARGS $dest "bash"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] archive failed (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# ------------------------------------------------------------
# [4/4] (optional) remove original release folders
# ------------------------------------------------------------
if ($RemoveOriginal) {
    Write-Host "[4/4] remove original V7.0 releases..." -ForegroundColor Yellow
    $remove_template = @'
set -e
cd REMOTE_BASE_PLACEHOLDER
echo "BEFORE current symlink: $(readlink current 2>/dev/null || echo none)"
if [ -L current ]; then
    target=$(readlink current)
    if echo "$target" | grep -q "v2025.12.14"; then
        echo "  unlinking current (V7.0 target: $target)"
        rm -f current
    fi
fi
for r in releases/v2025.12.14.*; do
    [ -d "$r" ] || continue
    bn=$(basename "$r")
    if [ -f "archive/v70_${bn}_DATE_TAG_PLACEHOLDER.tar.gz" ]; then
        echo "  removing $r"
        rm -rf "$r"
    else
        echo "  SKIP $r (no archive found)"
    fi
done
echo "=== AFTER ==="
ls releases/ 2>/dev/null
df -h /home/ubuntu | tail -1
'@
    $remove_cmd = $remove_template `
        -replace 'REMOTE_BASE_PLACEHOLDER', $REMOTE_BASE `
        -replace 'DATE_TAG_PLACEHOLDER', $DATE_TAG
    $remove_cmd | & ssh @SSH_ARGS $dest "bash"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] remove failed (exit=$LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "      OK" -ForegroundColor Green
} else {
    Write-Host "[4/4] original V7.0 releases preserved (use -RemoveOriginal to delete)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " V7.0 archive complete" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
