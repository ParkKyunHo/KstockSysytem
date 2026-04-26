[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"
ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "cd /home/ubuntu/K_stock_trading/current && source venv/bin/activate && python3 temp_analyze.py"
