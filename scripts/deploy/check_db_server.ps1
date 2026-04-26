# Check database record counts from server
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$LOCAL_SCRIPT = "C:\K_stock_trading\scripts\check_db_counts.py"

Write-Host "=== DB Record Counts ===" -ForegroundColor Cyan

# Upload script to current directory
scp -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL $LOCAL_SCRIPT "ubuntu@43.200.235.74:/home/ubuntu/K_stock_trading/current/check_db_counts.py"

# Run script using the correct venv path
ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "cd /home/ubuntu/K_stock_trading/current && source /home/ubuntu/K_stock_trading/current/venv/bin/activate && python check_db_counts.py"
