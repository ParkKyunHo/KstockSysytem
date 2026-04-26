# 서버 Python 프로세스 확인 및 고아 프로세스 감지
# 2025-12-17: 409 Conflict 문제 진단용
#
# 사용법: powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_processes.ps1"

$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$SERVER = "ubuntu@43.200.235.74"
$SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"

Write-Host "=== 서버 프로세스 진단 ===" -ForegroundColor Cyan
Write-Host ""

# 1. systemd 서비스 상태
Write-Host "[1/3] systemd 서비스 상태:" -ForegroundColor Yellow
$serviceStatus = ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER "systemctl is-active k-stock-trading 2>/dev/null" 2>$null
$servicePid = ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER "systemctl show k-stock-trading --property=MainPID --value 2>/dev/null" 2>$null

Write-Host "      상태: $serviceStatus"
Write-Host "      메인 PID: $servicePid"
Write-Host ""

# 2. 모든 trading 관련 Python 프로세스
Write-Host "[2/3] Trading 관련 Python 프로세스:" -ForegroundColor Yellow
$processes = ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER "ps aux | grep -E 'python.*(src.main|launcher)' | grep -v grep" 2>$null

if ([string]::IsNullOrWhiteSpace($processes)) {
    Write-Host "      (없음)" -ForegroundColor Gray
} else {
    $processes -split "`n" | ForEach-Object {
        $parts = $_ -split '\s+'
        $pid = $parts[1]
        $cmd = ($parts[10..($parts.Length-1)] -join ' ')

        if ($pid -eq $servicePid.Trim()) {
            Write-Host "      [서비스] PID $pid : $cmd" -ForegroundColor Green
        } else {
            Write-Host "      [고아?!] PID $pid : $cmd" -ForegroundColor Red
        }
    }
}
Write-Host ""

# 3. 고아 프로세스 판정
Write-Host "[3/3] 진단 결과:" -ForegroundColor Yellow

$orphanCheck = @"
SERVICE_PID=`$(systemctl show k-stock-trading --property=MainPID --value 2>/dev/null || echo "0")
SERVICE_CHILD=`$(pgrep -P `$SERVICE_PID 2>/dev/null || echo "")
ORPHAN_COUNT=0

for PID in `$(ps aux | grep 'python.*src.main' | grep -v grep | awk '{print `$2}'); do
    if [ "`$PID" != "`$SERVICE_PID" ] && [ "`$PID" != "`$SERVICE_CHILD" ]; then
        ORPHAN_COUNT=`$((ORPHAN_COUNT + 1))
    fi
done

echo `$ORPHAN_COUNT
"@

$orphanCount = (ssh -i $LIGHTSAIL_KEY $SSH_OPTS.Split(' ') $SERVER $orphanCheck 2>$null).Trim()

if ($orphanCount -eq "0") {
    Write-Host "      정상 - 고아 프로세스 없음" -ForegroundColor Green
} else {
    Write-Host "      경고 - 고아 프로세스 $orphanCount 개 발견!" -ForegroundColor Red
    Write-Host ""
    Write-Host "      해결 방법:" -ForegroundColor Yellow
    Write-Host "      powershell -ExecutionPolicy Bypass -File `"scripts\deploy\kill_orphan.ps1`""
}
Write-Host ""
