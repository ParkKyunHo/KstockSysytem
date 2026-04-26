[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"
ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "journalctl -u k-stock-trading --since '2026-01-15 10:10:20' --until '2026-01-15 10:10:35' --no-pager 2>/dev/null"
