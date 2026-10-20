@echo off
setlocal
chcp 65001 >nul
title Detener ISC Email Generator
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_app.ps1"
set "APP_EXIT=%ERRORLEVEL%"
echo.
if not "%ISC_EMAIL_GENERATOR_NONINTERACTIVE%"=="1" pause
exit /b %APP_EXIT%
