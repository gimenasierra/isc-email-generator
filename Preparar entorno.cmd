@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Preparar entorno - ISC Email Generator

if not exist "logs" mkdir "logs"
set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"

if exist "%PYTHON%" goto venv_ok
echo Creando el entorno virtual de Python (primera vez)...
py -3 -m venv backend\.venv
if errorlevel 1 goto venv_failed

:venv_ok
echo Instalando dependencias del backend...
"%PYTHON%" -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 goto deps_failed

if exist "frontend\dist\index.html" goto dist_ok
if not exist "frontend\node_modules" goto need_node
if not exist "frontend\package-lock.json" goto need_node

echo Compilando el frontend...
pushd frontend
call npm.cmd run build
set "BUILD_RESULT=%errorlevel%"
popd
if not "%BUILD_RESULT%"=="0" goto build_failed

:dist_ok
echo.
echo Entorno listo. Inicie la aplicacion con doble clic en "Iniciar app.cmd".
echo La primera vez, configure conexiones ISC y claves de IA desde la interfaz.
pause
exit /b 0

:venv_failed
echo ERROR: no se pudo crear backend\.venv.
echo Instale Python 3.11 o superior desde https://www.python.org/ y vuelva a ejecutar este script.
echo [%DATE% %TIME%] Preparar entorno fallo: venv.>>"logs\app.log"
pause
exit /b 2

:deps_failed
echo ERROR: no se pudieron instalar las dependencias del backend.
echo Revise su conexion a internet y ejecute manualmente:
echo   backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo [%DATE% %TIME%] Preparar entorno fallo: dependencias.>>"logs\app.log"
pause
exit /b 4

:need_node
echo ADVERTENCIA: falta la compilacion del frontend y no hay frontend\node_modules.
echo Esta copia no incluye frontend\dist. Instale Node.js 20 o superior y ejecute:
echo   cd frontend
echo   npm.cmd install
echo   npm.cmd run build
echo O bien, copie la carpeta frontend\dist desde el equipo que la compilo.
echo [%DATE% %TIME%] Preparar entorno: falto frontend dist.>>"logs\app.log"
pause
exit /b 3

:build_failed
echo ERROR: la compilacion del frontend fallo. Revise los mensajes de npm.
echo [%DATE% %TIME%] Preparar entorno fallo: build frontend.>>"logs\app.log"
pause
exit /b 5
