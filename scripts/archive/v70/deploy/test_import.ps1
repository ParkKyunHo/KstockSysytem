# Import 테스트 스크립트
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "Import 테스트 중..." -ForegroundColor Yellow

$testScript = @"
cd /home/ubuntu/K_stock_trading/current
source venv/bin/activate
python -c "
import sys
try:
    from src.core.exit_manager import ExitManager
    print('exit_manager: OK')
except Exception as e:
    print(f'exit_manager: FAIL - {e}')

try:
    from src.core.order_executor import OrderExecutor
    print('order_executor: OK')
except Exception as e:
    print(f'order_executor: FAIL - {e}')

try:
    from src.core.trading_engine import TradingEngine
    print('trading_engine: OK')
except Exception as e:
    print(f'trading_engine: FAIL - {e}')
"
"@

ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 $testScript
