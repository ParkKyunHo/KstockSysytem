@echo off
chcp 65001 >nul
:: ============================================================
:: SSH 접속
:: ============================================================

call "%~dp0config.bat"

echo ============================================================
echo  K_stock_trading SSH 접속
echo ============================================================
echo.
echo  서버: %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%
echo.

ssh -i "%LIGHTSAIL_KEY%" %LIGHTSAIL_USER%@%LIGHTSAIL_HOST%
