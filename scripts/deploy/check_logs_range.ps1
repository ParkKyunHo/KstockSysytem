# 시간 범위 로그 확인 스크립트
# Usage: check_logs_range.ps1 "2026-01-16 07:55" "2026-01-16 09:00"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

$since = if ($args[0]) { $args[0] } else { "today" }
$until = if ($args[1]) { $args[1] } else { "" }

if ($until) {
    ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading --since '$since' --until '$until' --no-pager"
} else {
    ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading --since '$since' --no-pager"
}
