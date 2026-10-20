@echo off
setlocal
chcp 65001 >nul
title ISC Email Generator
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_app.ps1"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" if not "%ISC_EMAIL_GENERATOR_NONINTERACTIVE%"=="1" pause
exit /b %APP_EXIT%
