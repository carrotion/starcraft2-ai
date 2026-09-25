@echo off
chcp 65001 >nul
title StarCraft II AI - 웹 대시보드 (관리자 권한 실행기)

echo ======================================================================
echo   [StarCraft II AI] 관리자 권한 확인 중...
echo ======================================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [안내] 관리자 권한이 필요합니다. UAC 권한 승인 창을 띄웁니다...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/k cd /d \"\"%~dp0\"\" && call .venv\Scripts\activate.bat && python dashboard_server.py' -Verb RunAs"
    exit /b
)

echo [OK] 관리자 권한 획득 완료!
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python dashboard_server.py
pause
