# 서비스 중지 스크립트
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "서비스 중지 중..." -ForegroundColor Yellow
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo systemctl stop k-stock-trading && echo 'Service stopped successfully'"
