# 서버 테스트 스크립트
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "cd /home/ubuntu/K_stock_trading/current && source venv/bin/activate && python -m src.main 2>&1 | head -50"
