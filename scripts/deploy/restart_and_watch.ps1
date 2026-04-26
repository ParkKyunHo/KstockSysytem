# 서비스 재시작 후 실시간 로그 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "=== 서비스 재시작 ===" -ForegroundColor Yellow
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo systemctl restart k-stock-trading"
Start-Sleep -Seconds 5

Write-Host "=== 최신 로그 ===" -ForegroundColor Cyan
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading -n 50 --no-pager"
