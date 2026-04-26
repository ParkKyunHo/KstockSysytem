@echo off
chcp 65001 >nul
:: ============================================================
:: 서버 로그 확인
:: ============================================================

call "%~dp0config.bat"

echo ============================================================
echo  K_stock_trading 로그 (실시간)
echo ============================================================
echo.
echo  Ctrl+C로 종료
echo.

ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST% "sudo journalctl -u k-stock-trading -f"
