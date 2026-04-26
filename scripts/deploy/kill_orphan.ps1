# 고아 프로세스 자동 감지 및 종료
# 2025-12-17: 409 Conflict 문제 해결용
#
# 사용법: powershell -ExecutionPolicy Bypass -File "scripts\deploy\kill_orphan.ps1"

$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$SERVER = "ubuntu@43.200.235.74"
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "=== 고아 프로세스 감지 및 종료 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 현재 Python 프로세스 확인
Write-Host "[1/3] 서버 Python 프로세스 확인..." -ForegroundColor Yellow

$processCheck = @'
ps aux | grep 'python.*src.main' | grep -v grep | awk '{print $2, $11, $12}'
'@

$processes = ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER $processCheck 2>$null

if ([string]::IsNullOrWhiteSpace($processes)) {
    Write-Host "      Python 프로세스 없음" -ForegroundColor Green
    exit 0
}

Write-Host "      발견된 프로세스:" -ForegroundColor White
$processes -split "`n" | ForEach-Object { Write-Host "      - $_" }
Write-Host ""

# 2. systemd 서비스의 메인 PID 확인
Write-Host "[2/3] systemd 서비스 PID 확인..." -ForegroundColor Yellow

$getServicePid = @'
systemctl show k-stock-trading --property=MainPID --value 2>/dev/null || echo "0"
'@

$servicePid = (ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER $getServicePid 2>$null).Trim()
Write-Host "      서비스 메인 PID: $servicePid" -ForegroundColor White
Write-Host ""

# 3. 고아 프로세스 종료
Write-Host "[3/3] 고아 프로세스 종료..." -ForegroundColor Yellow

$killOrphans = @"
SERVICE_PID=`$(systemctl show k-stock-trading --property=MainPID --value 2>/dev/null || echo "0")
SERVICE_CHILD=`$(pgrep -P `$SERVICE_PID 2>/dev/null || echo "")

for PID in `$(ps aux | grep 'python.*src.main' | grep -v grep | awk '{print `$2}'); do
    if [ "`$PID" != "`$SERVICE_PID" ] && [ "`$PID" != "`$SERVICE_CHILD" ]; then
        echo "Killing orphan PID: `$PID"
        kill -9 `$PID 2>/dev/null
    else
        echo "Skipping service PID: `$PID"
    fi
done
echo "Done"
"@

ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER $killOrphans

Write-Host ""
Write-Host "=== 완료 ===" -ForegroundColor Green
Write-Host ""
Write-Host "남은 프로세스 확인:" -ForegroundColor Cyan
ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER "ps aux | grep 'python.*src.main' | grep -v grep || echo '(없음)'"
