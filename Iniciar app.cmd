@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ISC Email Generator

if not exist "logs" mkdir "logs"
set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"
set "RUNNER=%CD%\backend\run.py"
set "READY_CHECK=%CD%\backend\check_ready.py"
set "APP_ROOT=%CD%"

if not exist "%PYTHON%" goto missing_venv
if not exist "frontend\dist\index.html" goto missing_frontend

"%PYTHON%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 goto missing_python_dependencies

powershell.exe -NoProfile -NonInteractive -Command "Start-Process -FilePath $env:PYTHON -ArgumentList @($env:RUNNER) -WorkingDirectory $env:APP_ROOT -WindowStyle Hidden"
if errorlevel 1 goto launch_failed

set /a READY_ATTEMPTS=0
:wait_ready
"%PYTHON%" "%READY_CHECK%" >nul 2>&1
if not errorlevel 1 exit /b 0
set /a READY_ATTEMPTS+=1
if %READY_ATTEMPTS% GEQ 40 goto readiness_failed
timeout /t 1 /nobreak >nul
goto wait_ready

:launch_failed
set "APP_EXIT=5"
echo ERROR: Windows no pudo iniciar el proceso local de ISC Email Generator.
goto show_failure

:readiness_failed
set "APP_EXIT=6"
echo ERROR: ISC Email Generator no respondio con la version esperada dentro de 40 segundos.

:show_failure
echo.
echo Ultimas lineas del log:
powershell.exe -NoProfile -NonInteractive -Command "Get-Content -LiteralPath (Join-Path $env:APP_ROOT 'logs\app.log') -Tail 20 -ErrorAction SilentlyContinue"

echo.
echo No se pudo iniciar ISC Email Generator. Codigo: %APP_EXIT%
echo Revise el log: %CD%\logs\app.log
echo [%DATE% %TIME%] Inicio fallido. Codigo %APP_EXIT%.>>"logs\app.log"
pause
exit /b %APP_EXIT%

:missing_venv
echo ERROR: falta el entorno virtual backend\.venv.
echo Instale Python 3.11 o superior y ejecute desde esta carpeta:
echo   py -3 -m venv backend\.venv
echo   backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo [%DATE% %TIME%] Falta backend\.venv.>>"logs\app.log"
pause
exit /b 2

:missing_frontend
echo ERROR: falta la compilacion del frontend.
echo Ejecute desde esta carpeta:
echo   cd frontend
echo   npm.cmd install
echo   npm.cmd run build
echo [%DATE% %TIME%] Falta frontend\dist\index.html.>>"logs\app.log"
pause
exit /b 3

:missing_python_dependencies
echo ERROR: faltan dependencias Python en backend\.venv.
echo Ejecute desde esta carpeta:
echo   backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo [%DATE% %TIME%] Faltan dependencias Python.>>"logs\app.log"
pause
exit /b 4
