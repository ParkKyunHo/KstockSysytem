# 배포된 get_status_text 함수 확인
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sed -n '3395,3430p' /home/ubuntu/K_stock_trading/current/src/core/trading_engine.py"
