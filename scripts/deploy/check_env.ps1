# Python 환경 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "=== Python 환경 확인 ===" -ForegroundColor Cyan
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "ls -la /home/ubuntu/K_stock_trading/ && cat /etc/systemd/system/k-stock-trading.service"
