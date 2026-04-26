@echo off
chcp 65001 >nul
:: ============================================================
:: K_stock_trading 배포 설정
:: ============================================================
:: 이 파일을 수정하여 서버 정보를 설정하세요.
:: ============================================================

:: SSH 설정
set LIGHTSAIL_HOST=43.200.235.74
set LIGHTSAIL_USER=ubuntu
set LIGHTSAIL_KEY=%USERPROFILE%\.ssh\k-stock-trading-key.pem

:: 서버 경로
set REMOTE_BASE=/home/ubuntu/K_stock_trading
set REMOTE_RELEASES=%REMOTE_BASE%/releases
set REMOTE_CURRENT=%REMOTE_BASE%/current
set REMOTE_SHARED=%REMOTE_BASE%/shared
set REMOTE_SCRIPTS=%REMOTE_BASE%/scripts

:: 로컬 경로
set LOCAL_PROJECT=%~dp0..\..
set LOCAL_SRC=%LOCAL_PROJECT%\src
set LOCAL_LAUNCHER=%LOCAL_PROJECT%\launcher.py
set LOCAL_REQUIREMENTS=%LOCAL_PROJECT%\requirements.txt

:: 버전 관리
set MAX_RELEASES=5

:: 색상 출력 함수
:: (Windows CMD/PowerShell ANSI 색상 제한적 지원)
