# RVOL 체크 스크립트 실행
$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "RVOL 체크 스크립트 복사 및 실행" -ForegroundColor Cyan

# 1. 스크립트 복사 (current 디렉토리로)
$scpCmd = "scp -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"C:\K_stock_trading\scripts\check_rvol_simple.py`" `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:/home/ubuntu/K_stock_trading/current/check_rvol_simple.py`""
Write-Host "복사 중..." -ForegroundColor Yellow
Invoke-Expression $scpCmd

# 2. 실행 (PYTHONPATH 명시적 설정)
Write-Host "실행 중..." -ForegroundColor Yellow
$sshCmd = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}`" `"cd /home/ubuntu/K_stock_trading/current && PYTHONPATH=/home/ubuntu/K_stock_trading/current /home/ubuntu/K_stock_trading/current/venv/bin/python check_rvol_simple.py`""
Invoke-Expression $sshCmd

Write-Host "완료" -ForegroundColor Green
