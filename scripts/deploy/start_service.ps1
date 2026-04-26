# 서비스 시작 스크립트
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "서비스 시작 중..." -ForegroundColor Green
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo systemctl start k-stock-trading && echo 'Service started'"
