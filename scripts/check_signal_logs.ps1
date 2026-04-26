[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"
ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "journalctl -u k-stock-trading --since '2026-01-15 09:00' --no-pager 2>/dev/null | grep -iE 'sniper|detect|signal_detector|check_signal|_detect' | head -50"
