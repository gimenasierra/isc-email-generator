$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$portablePython = Join-Path $root 'runtime\python.exe'
$portableMode = Test-Path -LiteralPath $portablePython -PathType Leaf
if ($portableMode -and -not $env:ISC_EMAIL_GENERATOR_STATE_DIR) {
    if (-not $env:LOCALAPPDATA) {
        Write-Host 'Windows no informó una carpeta LOCALAPPDATA para localizar la instancia portable.' -ForegroundColor Red
        exit 2
    }
    $env:ISC_EMAIL_GENERATOR_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ISC Email Generator'
}
$stateRoot = if ($env:ISC_EMAIL_GENERATOR_STATE_DIR) { $env:ISC_EMAIL_GENERATOR_STATE_DIR } else { $root }
$port = 8000
if ($env:ISC_EMAIL_GENERATOR_PORT) {
    if (-not [int]::TryParse($env:ISC_EMAIL_GENERATOR_PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        Write-Host 'ISC_EMAIL_GENERATOR_PORT debe ser un número entero entre 1 y 65535.' -ForegroundColor Red
        exit 2
    }
}
$pidName = if ($port -eq 8000) { 'app.pid' } else { "app-$port.pid" }
$pidFile = Join-Path $stateRoot ".run\$pidName"
$pythonPath = if ($portableMode) { $portablePython } else { Join-Path $root 'backend\.venv\Scripts\python.exe' }
$runnerPath = Join-Path $root 'backend\run.py'

$appPid = 0
$recoveredFromPort = $false
if (Test-Path -LiteralPath $pidFile) {
    $pidText = (Get-Content -Raw -LiteralPath $pidFile).Trim()
    if (-not [int]::TryParse($pidText, [ref]$appPid)) {
        Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
        $appPid = 0
    }
}

if ($appPid -gt 0) {
    $nativeProcess = Get-Process -Id $appPid -ErrorAction SilentlyContinue
    if (-not $nativeProcess) {
        Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
        $appPid = 0
    }
}

if ($appPid -eq 0) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') } |
        Select-Object -First 1
    if (-not $listener) {
        Write-Host 'La aplicación ya estaba detenida.' -ForegroundColor Yellow
        exit 0
    }
    $appPid = [int]$listener.OwningProcess
    $recoveredFromPort = $true
}

try {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $appPid" -ErrorAction Stop
} catch {
    Write-Host 'No se pudo validar de forma segura el proceso. No se finalizó ningún proceso.' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf) -or -not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
    Write-Host 'No se encontraron el Python y el iniciador esperados. No se finalizó ningún proceso.' -ForegroundColor Red
    exit 1
}
$expectedPython = (Resolve-Path -LiteralPath $pythonPath).Path
$expectedRunner = (Resolve-Path -LiteralPath $runnerPath).Path
$basePython = (& $expectedPython -c 'import sys; print(sys._base_executable)' 2>$null | Select-Object -First 1).Trim()
$sameExecutable = $process.ExecutablePath -and (
    ($process.ExecutablePath -ieq $expectedPython) -or
    ($basePython -and ($process.ExecutablePath -ieq $basePython))
)
$sameRunner = $process.CommandLine -and ($process.CommandLine.IndexOf($expectedRunner, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)

if (-not ($sameExecutable -and $sameRunner)) {
    if ($recoveredFromPort) {
        Write-Host "El puerto $port está ocupado por otro proceso. No se finalizó ningún proceso." -ForegroundColor Red
    } else {
        Write-Host 'El PID pertenece a otro proceso. No se finalizó ningún proceso.' -ForegroundColor Red
    }
    exit 1
}

Stop-Process -Id $appPid -ErrorAction Stop
Wait-Process -Id $appPid -Timeout 10 -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
if ($recoveredFromPort) {
    Write-Host 'Se recuperó de forma segura la instancia que había perdido su archivo PID.' -ForegroundColor Yellow
}
Write-Host 'ISC Email Generator se detuvo correctamente.' -ForegroundColor Green
