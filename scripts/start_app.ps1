$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$portablePython = Join-Path $root 'runtime\python.exe'
$developmentPython = Join-Path $root 'backend\.venv\Scripts\python.exe'
$runner = Join-Path $root 'backend\run.py'
$readyCheck = Join-Path $root 'backend\check_ready.py'
$frontendIndex = Join-Path $root 'frontend\dist\index.html'
$portableMode = Test-Path -LiteralPath $portablePython -PathType Leaf

if ($portableMode) {
    $python = $portablePython
    if (-not $env:ISC_EMAIL_GENERATOR_STATE_DIR) {
        if (-not $env:LOCALAPPDATA) {
            Write-Host 'ERROR: Windows no informo una carpeta LOCALAPPDATA escribible para guardar la configuracion.' -ForegroundColor Red
            exit 2
        }
        $env:ISC_EMAIL_GENERATOR_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ISC Email Generator'
    }
} else {
    $python = $developmentPython
}
$stateRoot = if ($env:ISC_EMAIL_GENERATOR_STATE_DIR) { $env:ISC_EMAIL_GENERATOR_STATE_DIR } else { $root }

$logDir = if ($portableMode) { Join-Path $stateRoot 'logs' } else { Join-Path $root 'logs' }
$startupLog = Join-Path $logDir 'inicio.log'
$stdoutLog = Join-Path $logDir 'inicio-salida.log'
$stderrLog = Join-Path $logDir 'inicio-error.log'
$appLog = Join-Path $logDir 'app.log'

function Write-StartupLog {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $startupLog -Value "$timestamp $Message" -Encoding UTF8
}

function Show-RecentLog {
    param([string]$Path, [string]$Title)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Write-Host ''
        Write-Host $Title -ForegroundColor Yellow
        Get-Content -LiteralPath $Path -Tail 20 -ErrorAction SilentlyContinue
    }
}

try {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Write-StartupLog "Inicio solicitado. Modo: $(if ($portableMode) { 'portable' } else { 'desarrollo' })."

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        if ($portableMode) {
            throw 'Falta runtime\python.exe. Vuelva a extraer el ZIP portable completo.'
        }
        throw 'Falta backend\.venv\Scripts\python.exe. Ejecute "Preparar entorno.cmd".'
    }
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf) -or -not (Test-Path -LiteralPath $readyCheck -PathType Leaf)) {
        throw 'Faltan archivos del backend. Vuelva a extraer o restaurar la aplicacion completa.'
    }
    if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
        if ($portableMode) {
            throw 'Falta frontend\dist\index.html. Vuelva a extraer el ZIP portable completo.'
        }
        throw 'Falta el frontend compilado. Ejecute "npm.cmd run build" dentro de frontend.'
    }

    & $python -c 'import fastapi, httpx, pydantic, truststore, uvicorn' *> $null
    if ($LASTEXITCODE -ne 0) {
        if ($portableMode) {
            throw 'El runtime portable esta incompleto o danado. Vuelva a descargar y extraer el ZIP completo.'
        }
        throw 'Faltan dependencias en backend\.venv. Ejecute "Preparar entorno.cmd".'
    }

    Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    $quotedRunner = '"' + $runner + '"'
    $process = Start-Process -FilePath $python -ArgumentList $quotedRunner -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    Write-StartupLog "Proceso iniciado con PID $($process.Id)."

    for ($attempt = 1; $attempt -le 40; $attempt++) {
        & $python $readyCheck *> $null
        if ($LASTEXITCODE -eq 0) {
            $port = if ($env:ISC_EMAIL_GENERATOR_PORT) { $env:ISC_EMAIL_GENERATOR_PORT } else { '8000' }
            Write-StartupLog "Aplicacion disponible en http://127.0.0.1:$port."
            Write-Host "ISC Email Generator esta disponible en http://127.0.0.1:$port" -ForegroundColor Green
            exit 0
        }
        $process.Refresh()
        if ($process.HasExited) {
            break
        }
        Start-Sleep -Seconds 1
    }

    $process.Refresh()
    if (-not $process.HasExited) {
        Write-StartupLog 'El servidor no quedo listo dentro de 40 segundos.'
        throw 'La aplicacion no respondio dentro de 40 segundos.'
    }
    Write-StartupLog "El proceso termino antes de quedar listo. Codigo $($process.ExitCode)."
    throw "La aplicacion termino durante el inicio (codigo $($process.ExitCode))."
} catch {
    $message = $_.Exception.Message
    try { Write-StartupLog "ERROR: $message" } catch { }
    Write-Host "ERROR: $message" -ForegroundColor Red
    Show-RecentLog -Path $stderrLog -Title 'Detalle del inicio:'
    Show-RecentLog -Path $appLog -Title 'Ultimas lineas del servidor:'
    Write-Host ''
    Write-Host "Revise los logs en: $logDir"
    exit 1
}
