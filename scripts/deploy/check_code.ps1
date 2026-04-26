# 배포된 코드 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 'grep -A 25 "def get_status_text" /home/ubuntu/K_stock_trading/current/src/core/trading_engine.py | head -30'
