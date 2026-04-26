# 서비스 상태 및 최신 로그 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "=== 서비스 상태 ===" -ForegroundColor Cyan
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo systemctl status k-stock-trading --no-pager"

Write-Host ""
Write-Host "=== 최신 로그 (실시간) ===" -ForegroundColor Cyan
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading -n 30 --no-pager -o cat"
