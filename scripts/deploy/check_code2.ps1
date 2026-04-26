# 배포된 코드에서 status 관련 함수 찾기
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 'grep -n "status_text\|get_status" /home/ubuntu/K_stock_trading/current/src/core/trading_engine.py'
