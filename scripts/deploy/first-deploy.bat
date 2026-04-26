@echo off
chcp 65001 >nul
:: ============================================================
:: K_stock_trading 최초 배포
:: ============================================================
:: 사용법: first-deploy.bat
::
:: 사전 조건:
:: 1. config.bat에서 LIGHTSAIL_HOST 설정
:: 2. SSH 키 파일 존재 확인
:: 3. 서버 초기 설정 완료 (setup.sh 실행됨)
:: ============================================================

setlocal enabledelayedexpansion

call "%~dp0config.bat"

echo ============================================================
echo  K_stock_trading 최초 배포
echo ============================================================
echo.
echo  서버: %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%
echo  로컬: %LOCAL_PROJECT%
echo.

:: 설정 확인
if "%LIGHTSAIL_HOST%"=="YOUR_LIGHTSAIL_IP_HERE" (
    echo [오류] config.bat에서 LIGHTSAIL_HOST를 설정하세요.
    pause
    exit /b 1
)

:: SSH 키 확인
if not exist "%LIGHTSAIL_KEY%" (
    echo [오류] SSH 키 파일이 없습니다: %LIGHTSAIL_KEY%
    pause
    exit /b 1
)

:: 확인 메시지
echo ============================================================
echo  주의: 최초 배포는 서버 디렉토리 구조를 초기화합니다.
echo ============================================================
echo.
set /p CONFIRM="계속하시겠습니까? (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo 취소됨.
    exit /b 0
)

echo.
echo [1/7] SSH 연결 테스트...
ssh -i "%LIGHTSAIL_KEY%" -o ConnectTimeout=10 %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "echo 'SSH OK'" 2>nul
if errorlevel 1 (
    echo [오류] SSH 연결 실패
    pause
    exit /b 1
)
echo       성공

echo.
echo [2/7] 서버 디렉토리 구조 생성...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "mkdir -p %REMOTE_BASE%/{releases,shared/{logs,data},scripts}"
echo       완료

echo.
echo [3/7] 서버 스크립트 전송...
scp -i "%LIGHTSAIL_KEY%" "%~dp0..\server\*.sh" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_SCRIPTS%/
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "chmod +x %REMOTE_SCRIPTS%/*.sh"
echo       완료

echo.
echo [4/7] systemd 서비스 파일 전송...
scp -i "%LIGHTSAIL_KEY%" "%~dp0..\server\k-stock-trading.service" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:/tmp/
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo mv /tmp/k-stock-trading.service /etc/systemd/system/ && sudo systemctl daemon-reload"
echo       완료

echo.
echo [5/7] 버전 생성...
:: 버전 형식: v2025.12.14.001 (PowerShell로 로케일 독립적 형식)
for /f %%i in ('powershell -c "Get-Date -Format 'yyyy.MM.dd'"') do set TODAY=%%i
set VERSION=v%TODAY%.001
echo       버전: %VERSION%

echo.
echo [6/7] 코드 전송 및 설치...
:: 임시 디렉토리 생성
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "mkdir -p %REMOTE_RELEASES%/%VERSION%"

:: 임시 폴더 생성 (클린 복사용)
set TEMP_DIR=%TEMP%\k_stock_first_deploy_%RANDOM%
mkdir "%TEMP_DIR%" 2>nul
mkdir "%TEMP_DIR%\src" 2>nul

:: src/ 복사 (__pycache__ 제외)
echo       src/ 복사 중 (__pycache__ 제외)...
robocopy "%LOCAL_SRC%" "%TEMP_DIR%\src" /E /XD __pycache__ /XF *.pyc >nul 2>nul

:: 파일 전송
echo       src/ 전송 중...
scp -i "%LIGHTSAIL_KEY%" -r -q "%TEMP_DIR%\src" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%VERSION%/

echo       launcher.py 전송 중...
scp -i "%LIGHTSAIL_KEY%" -q "%LOCAL_LAUNCHER%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%VERSION%/

echo       requirements.txt 전송 중...
scp -i "%LIGHTSAIL_KEY%" -q "%LOCAL_REQUIREMENTS%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%VERSION%/

:: 임시 폴더 삭제
rmdir /S /Q "%TEMP_DIR%" 2>nul

:: 버전 파일 생성
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "echo '%VERSION%' > %REMOTE_RELEASES%/%VERSION%/VERSION"

:: 서버에서 설치 실행
echo       의존성 설치 중...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/install.sh %VERSION%"

echo.
echo [7/7] 서비스 시작...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl enable k-stock-trading && sudo systemctl start k-stock-trading"

echo.
echo ============================================================
echo  최초 배포 완료!
echo ============================================================
echo.
echo  버전: %VERSION%
echo.
echo  다음 단계:
echo  1. 서버에서 .env 파일 설정:
echo     ssh로 접속 후: nano %REMOTE_SHARED%/.env
echo  2. 서비스 재시작:
echo     sudo systemctl restart k-stock-trading
echo  3. 상태 확인:
echo     status.bat 실행
echo.
pause
