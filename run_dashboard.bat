@echo off
chcp 65001 >nul
cd /d "%~dp0"
title StarCraft II AI - 대시보드 서버
call .venv\Scripts\activate.bat
python dashboard_server.py
pause
