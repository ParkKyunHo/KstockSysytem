@echo off
chcp 65001 >nul
:: ============================================================
:: 서버 상태 확인
:: ============================================================

call "%~dp0config.bat"

echo ============================================================
echo  K_stock_trading 서버 상태
echo ============================================================
echo.

echo [1/4] 서비스 상태...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo systemctl status k-stock-trading --no-pager -l"

echo.
echo [2/4] 현재 버전...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "cat %REMOTE_CURRENT%/VERSION 2>/dev/null || echo 'VERSION 파일 없음'"

echo.
echo [3/4] 리소스 사용량...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "echo '메모리:' && free -h | head -2 && echo && echo '디스크:' && df -h / | tail -1"

echo.
echo [4/4] 최근 로그 (5줄)...
ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo journalctl -u k-stock-trading -n 5 --no-pager"

echo.
echo ============================================================
pause
