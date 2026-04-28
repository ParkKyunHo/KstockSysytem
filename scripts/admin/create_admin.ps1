# ============================================================
# V7.1 dashboard admin user creation -- zero password leak
# ============================================================
# Usage:
#   .\scripts\admin\create_admin.ps1
#
# Flow:
#   1. Prompt username (plaintext OK -- not PII)
#   2. Prompt password as SecureString (hidden)
#   3. JSON {username, password} -> python create_admin.py via stdin
#   4. Python computes bcrypt(rounds=12) hash + DB INSERT
#   5. Plaintext password is wiped from memory immediately
#
# Re-run:
#   - Same username -> NOOP (duplicate guard)
#   - Password reset requires a separate tool (not provided yet)
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 dashboard admin creation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Password input is hidden (SecureString)." -ForegroundColor Yellow
Write-Host "Minimum 8 chars; 16+ recommended." -ForegroundColor Yellow
Write-Host ""

# ------------------------------------------------------------
# Username (plaintext OK)
# ------------------------------------------------------------
$username = Read-Host "username (3-32 chars, A-Z a-z 0-9 _ -)"
if ([string]::IsNullOrWhiteSpace($username)) {
    Write-Host "[ERROR] username empty" -ForegroundColor Red
    exit 1
}
if ($username -notmatch "^[A-Za-z0-9_-]{3,32}$") {
    Write-Host "[ERROR] username invalid format (3-32 chars, A-Z/a-z/0-9/_/-)" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# Password (SecureString - not echoed, not logged)
# ------------------------------------------------------------
$secure1 = Read-Host "password (input is hidden)" -AsSecureString
$secure2 = Read-Host "password (re-enter)" -AsSecureString

# SecureString -> plain (briefly held in memory)
$bstr1 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
$bstr2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
try {
    $plain1 = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr1)
    $plain2 = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr2)
}
finally {
    # Zero out BSTR memory immediately (defence in depth)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
}

if ($plain1 -ne $plain2) {
    Write-Host "[ERROR] passwords do not match" -ForegroundColor Red
    exit 1
}
if ($plain1.Length -lt 8) {
    Write-Host "[ERROR] password must be at least 8 chars" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# Call python create_admin.py via stdin pipe (no argv/env exposure)
# ------------------------------------------------------------
$payload = @{ username = $username; password = $plain1 } | ConvertTo-Json -Compress

# Drop plaintext refs immediately
$plain1 = $null
$plain2 = $null

$py = "C:\Program Files\Python311\python.exe"
$script = "$PSScriptRoot\create_admin.py"

Write-Host ""
Write-Host "DB INSERT in progress..." -ForegroundColor Yellow
$payload | & $py $script

# Drop payload too
$payload = $null
[System.GC]::Collect()

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
Write-Host "        -d '{`"username`":`"<USERNAME>`", `"password`":`"<PASSWORD>`"}'" -ForegroundColor Gray
Write-Host ""
Write-Host "2. After frontend deploy: open in browser." -ForegroundColor Cyan
