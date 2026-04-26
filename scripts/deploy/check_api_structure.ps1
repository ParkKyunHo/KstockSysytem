# API 구조 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "=== 서버 API 구조 확인 ===" -ForegroundColor Cyan
$sshCmd = "ssh -i `"$LIGHTSAIL_KEY`" $SSH_OPTS `"ubuntu@43.200.235.74`" `"ls -la /home/ubuntu/K_stock_trading/current/src/api/`""
Invoke-Expression $sshCmd
