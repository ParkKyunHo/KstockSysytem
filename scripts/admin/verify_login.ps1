# ============================================================
# V7.1 dashboard login verifier
# ============================================================
# Usage:
#   .\scripts\admin\verify_login.ps1
#
# Flow:
#   1. PowerShell prompts username
#   2. Python prompts password (getpass, hidden)
#   3. Python POSTs to /api/v71/auth/login
#   4. Prints masked tokens + expiry (no plaintext token / password)
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 dashboard login verifier" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$username = Read-Host "username"
if ([string]::IsNullOrWhiteSpace($username)) {
    Write-Host "[ERROR] username empty" -ForegroundColor Red
    exit 1
}

$py = "C:\Program Files\Python311\python.exe"
$script = "$PSScriptRoot\verify_login.py"

& $py $script $username
exit $LASTEXITCODE
