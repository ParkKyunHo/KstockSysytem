# 로그 확인 스크립트

# UTF-8 인코딩 설정 (한글 깨짐 방지)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

# 인자가 있으면 해당 줄 수 사용, 없으면 50줄
$lines = if ($args[0]) { $args[0] } else { 50 }

ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL ubuntu@43.200.235.74 "sudo journalctl -u k-stock-trading -n $lines --no-pager"
