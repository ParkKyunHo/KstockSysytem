# ============================================================
# V7.1 dashboard admin user creation
# ============================================================
# Usage:
#   .\scripts\admin\create_admin.ps1
#
# Flow:
#   1. PowerShell prompts username (plaintext OK -- not PII)
#   2. PowerShell hands username to python create_admin.py via argv
#   3. Python prompts password twice via getpass.getpass() (hidden)
#   4. Python hashes (bcrypt rounds=12) + INSERT into users
#
# Why getpass instead of PowerShell SecureString | stdin pipe?
#   PowerShell 5.1 wraps string objects when piping to native exes,
#   so Python sys.stdin.read() received an empty string. Letting
#   Python read the password directly is the most portable + safe path.
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 dashboard admin creation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Password is requested by Python (getpass) -- input is hidden." -ForegroundColor Yellow
Write-Host "Minimum 8 chars; 16+ recommended." -ForegroundColor Yellow
Write-Host ""

$username = Read-Host "username (3-32 chars, A-Z a-z 0-9 _ -)"
if ([string]::IsNullOrWhiteSpace($username)) {
    Write-Host "[ERROR] username empty" -ForegroundColor Red
    exit 1
}
if ($username -notmatch "^[A-Za-z0-9_-]{3,32}$") {
    Write-Host "[ERROR] username invalid format (3-32 chars, A-Z/a-z/0-9/_/-)" -ForegroundColor Red
    exit 1
}

$py = "C:\Program Files\Python311\python.exe"
$script = "$PSScriptRoot\create_admin.py"

Write-Host ""
& $py $script $username

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] admin creation failed (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Done -- next steps" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "1. Verify login (POST):" -ForegroundColor Cyan
Write-Host "   curl -X POST http://43.200.235.74:8080/api/v71/auth/login \" -ForegroundColor Gray
Write-Host "        -H 'Content-Type: application/json' \" -ForegroundColor Gray
Write-Host "        -d '{`"username`":`"<USERNAME>`",`"password`":`"<PASSWORD>`"}'" -ForegroundColor Gray
Write-Host ""
Write-Host "2. After frontend deploy: open in browser." -ForegroundColor Cyan
