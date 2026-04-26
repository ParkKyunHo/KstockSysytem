@echo off
chcp 65001 >nul
:: ============================================================
:: K_stock_trading 롤백
:: ============================================================
:: 사용법:
::   rollback.bat          - 이전 버전으로 롤백
::   rollback.bat v2025.12.14.001  - 특정 버전으로 롤백
:: ============================================================

setlocal enabledelayedexpansion

call "%~dp0config.bat"

set TARGET_VERSION=%1

echo ============================================================
echo  K_stock_trading 롤백
echo ============================================================
echo.

:: 설정 확인
if "%LIGHTSAIL_HOST%"=="YOUR_LIGHTSAIL_IP_HERE" (
    echo [오류] config.bat에서 LIGHTSAIL_HOST를 설정하세요.
    pause
    exit /b 1
)

:: 현재 버전 확인
for /f "tokens=*" %%i in ('ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "cat %REMOTE_CURRENT%/VERSION 2>/dev/null || echo 'none'"') do set CURRENT_VERSION=%%i
echo  현재 버전: %CURRENT_VERSION%

:: 가용 버전 목록
echo.
echo  가용 버전:
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "ls -1 %REMOTE_RELEASES% | sort -r | head -5"
echo.

:: 타겟 버전 결정
if "%TARGET_VERSION%"=="" (
    set TARGET_VERSION=previous
    echo  롤백 대상: 이전 버전
) else (
    echo  롤백 대상: %TARGET_VERSION%
)

:: 확인
set /p CONFIRM="롤백을 진행하시겠습니까? (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo 취소됨.
    exit /b 0
)

echo.
echo [1/3] 롤백 실행 중...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/rollback.sh %TARGET_VERSION%"

echo.
echo [2/3] 서비스 재시작...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl restart k-stock-trading"

echo.
echo [3/3] 상태 확인...
timeout /t 5 /nobreak >nul
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl status k-stock-trading --no-pager | head -10"

:: 새 버전 확인
for /f "tokens=*" %%i in ('ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "cat %REMOTE_CURRENT%/VERSION 2>/dev/null"') do set NEW_VERSION=%%i

echo.
echo ============================================================
echo  롤백 완료!
echo ============================================================
echo.
echo  이전: %CURRENT_VERSION%
echo  현재: %NEW_VERSION%
echo.
pause
