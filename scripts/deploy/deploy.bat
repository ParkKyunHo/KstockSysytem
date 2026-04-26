@echo off
chcp 65001 >nul
:: ============================================================
:: K_stock_trading 업데이트 배포
:: ============================================================
:: 사용법: deploy.bat
::
:: 프로세스:
:: 1. 로컬 검증 (Python 문법 체크)
:: 2. 서버 상태 확인
:: 3. 새 릴리즈 버전 생성
:: 4. 코드 전송
:: 5. 의존성 설치
:: 6. 심볼릭 링크 전환
:: 7. 서비스 재시작
:: 8. 헬스체크
:: 9. 실패 시 자동 롤백
:: ============================================================

setlocal enabledelayedexpansion

call "%~dp0config.bat"

echo ============================================================
echo  K_stock_trading 업데이트 배포
echo ============================================================
echo.

:: 설정 확인
if "%LIGHTSAIL_HOST%"=="YOUR_LIGHTSAIL_IP_HERE" (
    echo [오류] config.bat에서 LIGHTSAIL_HOST를 설정하세요.
    pause
    exit /b 1
)

:: ============================================================
:: Step 1: 로컬 검증
:: ============================================================
echo [1/8] 로컬 코드 검증...

:: Python 문법 체크
python -m py_compile "%LOCAL_SRC%\main.py" 2>nul
if errorlevel 1 (
    echo [오류] Python 문법 오류 발견
    echo        python -m py_compile src\main.py 로 확인하세요.
    pause
    exit /b 1
)
echo       문법 검증 통과

:: 필수 파일 확인
if not exist "%LOCAL_SRC%\main.py" (
    echo [오류] src\main.py 파일 없음
    pause
    exit /b 1
)
if not exist "%LOCAL_LAUNCHER%" (
    echo [오류] launcher.py 파일 없음
    pause
    exit /b 1
)
echo       필수 파일 확인 완료

:: ============================================================
:: Step 2: 서버 상태 확인
:: ============================================================
echo.
echo [2/8] 서버 상태 확인...

ssh -i "%LIGHTSAIL_KEY%" -o ConnectTimeout=10 %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "echo 'OK'" 2>nul
if errorlevel 1 (
    echo [오류] SSH 연결 실패
    pause
    exit /b 1
)
echo       SSH 연결 성공

:: 현재 버전 확인
for /f "tokens=*" %%i in ('ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "cat %REMOTE_CURRENT%/VERSION 2>/dev/null || echo 'none'"') do set CURRENT_VERSION=%%i
echo       현재 버전: %CURRENT_VERSION%

:: ============================================================
:: Step 3: 새 버전 생성
:: ============================================================
echo.
echo [3/8] 새 버전 생성...

:: 오늘 날짜의 다음 시퀀스 찾기 (PowerShell로 로케일 독립적 형식)
for /f %%i in ('powershell -c "Get-Date -Format 'yyyy.MM.dd'"') do set TODAY=%%i

:: 서버에서 오늘 버전 수 확인
for /f "tokens=*" %%i in ('ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "ls -1 %REMOTE_RELEASES% 2>/dev/null | grep 'v%TODAY%' | wc -l"') do set TODAY_COUNT=%%i
set /a NEXT_SEQ=%TODAY_COUNT%+1
set SEQ_PADDED=00%NEXT_SEQ%
set SEQ_PADDED=%SEQ_PADDED:~-3%

set NEW_VERSION=v%TODAY%.%SEQ_PADDED%
echo       새 버전: %NEW_VERSION%

:: ============================================================
:: Step 4: 코드 전송
:: ============================================================
echo.
echo [4/8] 코드 전송...

:: 릴리즈 디렉토리 생성
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "mkdir -p %REMOTE_RELEASES%/%NEW_VERSION%/src"

:: 임시 폴더 생성 (클린 복사용)
set TEMP_DIR=%TEMP%\k_stock_deploy_%RANDOM%
mkdir "%TEMP_DIR%" 2>nul
mkdir "%TEMP_DIR%\src" 2>nul

:: src/ 복사 (__pycache__ 제외)
echo       src/ 복사 중 (__pycache__ 제외)...
robocopy "%LOCAL_SRC%" "%TEMP_DIR%\src" /E /XD __pycache__ /XF *.pyc >nul 2>nul

:: 파일 전송 (진행률 숨김)
echo       src/ 전송 중...
scp -i "%LIGHTSAIL_KEY%" -r -q "%TEMP_DIR%\src" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%NEW_VERSION%/

echo       launcher.py 전송 중...
scp -i "%LIGHTSAIL_KEY%" -q "%LOCAL_LAUNCHER%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%NEW_VERSION%/

echo       requirements.txt 전송 중...
scp -i "%LIGHTSAIL_KEY%" -q "%LOCAL_REQUIREMENTS%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%:%REMOTE_RELEASES%/%NEW_VERSION%/

:: 임시 폴더 삭제
rmdir /S /Q "%TEMP_DIR%" 2>nul

:: 버전 파일
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "echo '%NEW_VERSION%' > %REMOTE_RELEASES%/%NEW_VERSION%/VERSION"
echo       전송 완료

:: ============================================================
:: Step 5: 서버에서 설치
:: ============================================================
echo.
echo [5/8] 의존성 설치...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/install.sh %NEW_VERSION%"

:: ============================================================
:: Step 6: 서비스 중지
:: ============================================================
echo.
echo [6/8] 서비스 전환 준비...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl stop k-stock-trading"
echo       서비스 중지됨

:: ============================================================
:: Step 7: 심볼릭 링크 전환
:: ============================================================
echo.
echo [7/8] 버전 전환...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "rm -f %REMOTE_CURRENT% && ln -s %REMOTE_RELEASES%/%NEW_VERSION% %REMOTE_CURRENT%"
echo       %NEW_VERSION% 활성화됨

:: 서비스 시작
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl start k-stock-trading"
echo       서비스 시작됨

:: ============================================================
:: Step 8: 헬스체크
:: ============================================================
echo.
echo [8/8] 헬스체크 (10초 대기)...
timeout /t 10 /nobreak >nul

ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/health-check.sh"
if errorlevel 1 (
    echo.
    echo [경고] 헬스체크 실패! 롤백 중...
    ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/rollback.sh previous"
    echo [오류] 배포 실패, 이전 버전으로 롤백됨
    pause
    exit /b 1
)

:: ============================================================
:: 완료
:: ============================================================
echo.
echo ============================================================
echo  배포 완료!
echo ============================================================
echo.
echo  이전 버전: %CURRENT_VERSION%
echo  새 버전:   %NEW_VERSION%
echo.

:: 오래된 릴리즈 정리
echo  오래된 릴리즈 정리 중...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "%REMOTE_SCRIPTS%/cleanup.sh"

echo.
pause
