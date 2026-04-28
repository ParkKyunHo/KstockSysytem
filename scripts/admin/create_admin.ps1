# ============================================================
# V7.1 dashboard admin user 생성 — 비밀번호 transcript 노출 0
# ============================================================
# 사용법:
#   .\scripts\admin\create_admin.ps1
#
# 흐름:
#   1. username 입력 (평문 OK — username은 PII 아님)
#   2. password 입력 (SecureString — 화면/transcript 노출 X)
#   3. JSON {username, password} 를 Python create_admin.py 에 stdin pipe
#   4. Python 이 bcrypt(rounds=12) hash 생성 + DB INSERT
#   5. plaintext 비밀번호는 메모리에 잠시만 머문 후 즉시 폐기
#
# 재실행:
#   - 같은 username 으로 재실행 시 NOOP (중복 방지)
#   - 비밀번호 변경은 별도 도구 필요 (현재 미제공)
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " V7.1 dashboard admin 생성" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "비밀번호는 화면/transcript에 표시되지 않습니다 (SecureString)." -ForegroundColor Yellow
Write-Host "비밀번호는 8자 이상, 가능하면 16자 이상 권장." -ForegroundColor Yellow
Write-Host ""

# ------------------------------------------------------------
# Username (평문 OK)
# ------------------------------------------------------------
$username = Read-Host "username (3-32자, A-Z a-z 0-9 _ -)"
if ([string]::IsNullOrWhiteSpace($username)) {
    Write-Host "[ERROR] username 비어있음" -ForegroundColor Red
    exit 1
}
if ($username -notmatch "^[A-Za-z0-9_-]{3,32}$") {
    Write-Host "[ERROR] username 형식 잘못됨 (3-32자, A-Z/a-z/0-9/_/-)" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# Password (SecureString — 화면 마스킹 X, transcript 노출 X)
# ------------------------------------------------------------
$secure1 = Read-Host "password (입력 시 화면에 안 보입니다)" -AsSecureString
$secure2 = Read-Host "password 한 번 더" -AsSecureString

# SecureString -> plain (잠시만 메모리에 보관)
$bstr1 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
$bstr2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
try {
    $plain1 = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr1)
    $plain2 = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr2)
}
finally {
    # 곧바로 BSTR 메모리 zero (defence in depth)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
}

if ($plain1 -ne $plain2) {
    Write-Host "[ERROR] 두 번 입력한 비밀번호가 다릅니다" -ForegroundColor Red
    exit 1
}
if ($plain1.Length -lt 8) {
    Write-Host "[ERROR] 비밀번호는 8자 이상" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# Python create_admin.py 호출 (stdin pipe — argv/env 노출 X)
# ------------------------------------------------------------
$payload = @{ username = $username; password = $plain1 } | ConvertTo-Json -Compress

# 즉시 plaintext 변수 폐기
$plain1 = $null
$plain2 = $null

$py = "C:\Program Files\Python311\python.exe"
$script = "$PSScriptRoot\create_admin.py"

Write-Host ""
Write-Host "DB INSERT 진행..." -ForegroundColor Yellow
$payload | & $py $script

# Payload 변수도 폐기
$payload = $null
[System.GC]::Collect()

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] admin 생성 실패 (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " 완료 — 다음 단계" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "1. dashboard 로그인 (POST):" -ForegroundColor Cyan
Write-Host "   curl -X POST http://43.200.235.74:8080/api/v71/auth/login \" -ForegroundColor Gray
Write-Host "        -H 'Content-Type: application/json' \" -ForegroundColor Gray
Write-Host "        -d '{`"username`":`"<username>`", `"password`":`"<password>`"}'" -ForegroundColor Gray
Write-Host ""
Write-Host "2. frontend 배포 후 브라우저에서 로그인 (다음 단계)" -ForegroundColor Cyan
