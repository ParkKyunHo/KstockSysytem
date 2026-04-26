# ============================================================
# K_stock_trading 핫픽스 배포 (버전 변경 없이 파일만 업로드)
# ============================================================
# 사용법: .\hotfix.ps1 [-NoRestart]
#   -NoRestart : 파일만 전송하고 서비스 재시작하지 않음
# ============================================================
param(
    [switch]$NoRestart
)

# UTF-8 인코딩 설정 (한글 깨짐 방지)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$ErrorActionPreference = "Stop"

# 설정
$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$LOCAL_PROJECT = "C:\K_stock_trading"
$REMOTE_CURRENT = "/home/ubuntu/K_stock_trading/current"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " K_stock_trading 핫픽스 배포" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# SSH 키 확인
if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host "[ERROR] SSH 키 파일이 없습니다: $LIGHTSAIL_KEY" -ForegroundColor Red
    exit 1
}

# 로컬 검증
Write-Host "[1/3] 로컬 코드 검증..." -ForegroundColor Yellow
python -m py_compile "$LOCAL_PROJECT\src\main.py" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python 문법 오류" -ForegroundColor Red
    exit 1
}
Write-Host "      통과" -ForegroundColor Green

# SSH 옵션 (yes 프롬프트 방지)
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

# 파일 전송
Write-Host "[2/3] 파일 전송..." -ForegroundColor Yellow
$scpCmd = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS -r `"$LOCAL_PROJECT\src`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/`""
Invoke-Expression $scpCmd 2>$null
$scpCmd2 = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$LOCAL_PROJECT\launcher.py`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/`""
Invoke-Expression $scpCmd2 2>$null
$scpCmd3 = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"$LOCAL_PROJECT\.env`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_CURRENT/`""
Invoke-Expression $scpCmd3 2>$null
Write-Host "      완료 (src + launcher.py + .env)" -ForegroundColor Green

# 서비스 재시작
if ($NoRestart) {
    Write-Host "[3/3] 서비스 재시작 건너뜀 (-NoRestart)" -ForegroundColor Yellow
} else {
    Write-Host "[3/3] 서비스 재시작..." -ForegroundColor Yellow
    $sshCmd = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"sudo systemctl restart k-stock-trading`""
    Invoke-Expression $sshCmd
    Start-Sleep -Seconds 3

    $status = & ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl is-active k-stock-trading"
    if ($status -eq "active") {
        Write-Host "      서비스 정상" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] 서비스 시작 실패" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " 핫픽스 완료" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
