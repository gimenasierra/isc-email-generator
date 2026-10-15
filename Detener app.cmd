@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Detener ISC Email Generator
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\stop_app.ps1"
echo.
pause
