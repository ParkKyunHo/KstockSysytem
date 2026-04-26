# Search logs or run command
param([string]$pattern = "Grand Trend", [switch]$env, [string]$cmd)
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
if ($cmd) {
    ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "$cmd"
} elseif ($env) {
    ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "cat /home/ubuntu/K_stock_trading/current/.env | grep -E 'PARTIAL|SAFETY|ATR_TRAIL'"
} else {
    ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading -n 300 --no-pager | grep -E '$pattern'"
}
