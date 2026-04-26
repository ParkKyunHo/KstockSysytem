# 강제 종료
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

Write-Host "강제 종료 (SIGKILL)..." -ForegroundColor Red
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "kill -9 32232; sleep 1; ps aux | grep python | grep -v grep"
