# Pool 리셋 로그 확인 스크립트
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading --since '2026-01-06 07:38:00' --until '2026-01-06 07:52:00' --no-pager 2>/dev/null | grep -iE 'V6.2-B|리셋|reset|daily|_check'"
