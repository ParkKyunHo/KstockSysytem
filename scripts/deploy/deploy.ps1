# ============================================================
# K_stock_trading 배포 스크립트 (PowerShell)
# ============================================================
# 사용법: .\deploy.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# 설정
$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"
$LOCAL_PROJECT = "C:\K_stock_trading"
$REMOTE_BASE = "/home/ubuntu/K_stock_trading"

# SSH 옵션 (yes 프롬프트 방지)
$SSH_OPTS = @("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " K_stock_trading 배포" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# SSH 키 확인
if (-not (Test-Path $LIGHTSAIL_KEY)) {
    Write-Host "[ERROR] SSH 키 파일이 없습니다: $LIGHTSAIL_KEY" -ForegroundColor Red
    exit 1
}

# Step 1: 로컬 검증
Write-Host "[1/6] 로컬 코드 검증..." -ForegroundColor Yellow
python -m py_compile "$LOCAL_PROJECT\src\main.py" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python 문법 오류" -ForegroundColor Red
    exit 1
}
Write-Host "      문법 검증 통과" -ForegroundColor Green

# Step 2: SSH 연결 테스트
Write-Host "[2/6] SSH 연결 테스트..." -ForegroundColor Yellow
$sshTest = ssh -i $LIGHTSAIL_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "echo OK" 2>&1
if ($sshTest -ne "OK") {
    Write-Host "[ERROR] SSH 연결 실패" -ForegroundColor Red
    exit 1
}
Write-Host "      SSH 연결 성공" -ForegroundColor Green

# Step 3: 현재 버전 확인 및 새 버전 생성
Write-Host "[3/6] 버전 생성..." -ForegroundColor Yellow
$currentVersion = & ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "cat $REMOTE_BASE/current/VERSION 2>/dev/null || echo 'none'"
Write-Host "      현재 버전: $currentVersion"

$today = Get-Date -Format "yyyy.MM.dd"
$todayCount = & ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "ls -1 $REMOTE_BASE/releases 2>/dev/null | grep 'v$today' | wc -l"
$nextSeq = ([int]$todayCount + 1).ToString("D3")
$newVersion = "v$today.$nextSeq"
Write-Host "      새 버전: $newVersion" -ForegroundColor Green

# Step 4: 릴리즈 디렉토리 생성 및 파일 전송
Write-Host "[4/6] 파일 전송..." -ForegroundColor Yellow
& ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "mkdir -p $REMOTE_BASE/releases/$newVersion"

# src/ 전송 (하위 디렉토리 포함)
Write-Host "      src/ 전송 중..."
& scp -i $LIGHTSAIL_KEY @SSH_OPTS -r "$LOCAL_PROJECT\src" "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_BASE/releases/$newVersion/" 2>$null

# launcher.py, requirements.txt 전송
Write-Host "      launcher.py, requirements.txt 전송 중..."
& scp -i $LIGHTSAIL_KEY @SSH_OPTS "$LOCAL_PROJECT\launcher.py" "$LOCAL_PROJECT\requirements.txt" "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}:$REMOTE_BASE/releases/$newVersion/" 2>$null

# VERSION 파일 생성
& ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "echo '$newVersion' > $REMOTE_BASE/releases/$newVersion/VERSION"
Write-Host "      전송 완료" -ForegroundColor Green

# Step 5: 서버 설치 (venv, 의존성, symlink)
Write-Host "[5/6] 서버 설치..." -ForegroundColor Yellow
$installOutput = & ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "$REMOTE_BASE/scripts/install.sh $newVersion" 2>&1
if ($installOutput -match "설치 완료") {
    Write-Host "      설치 완료" -ForegroundColor Green
} else {
    Write-Host "[WARNING] 설치 스크립트 출력 확인 필요" -ForegroundColor Yellow
    Write-Host $installOutput
}

# Step 6: 심볼릭 링크 전환 및 서비스 재시작
Write-Host "[6/6] 서비스 배포..." -ForegroundColor Yellow
& ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "ln -sfn $REMOTE_BASE/releases/$newVersion $REMOTE_BASE/current && sudo systemctl restart k-stock-trading && sleep 3"

# 헬스체크
$status = & ssh -i $LIGHTSAIL_KEY @SSH_OPTS "${LIGHTSAIL_USER}@${LIGHTSAIL_HOST}" "sudo systemctl is-active k-stock-trading"
if ($status -eq "active") {
    Write-Host "      서비스 정상 실행 중" -ForegroundColor Green
} else {
    Write-Host "[ERROR] 서비스 시작 실패" -ForegroundColor Red
    Write-Host "      롤백 실행: rollback.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " 배포 완료: $newVersion" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "로그 확인: .\check_logs.ps1"
