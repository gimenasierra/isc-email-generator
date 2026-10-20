<#
.SYNOPSIS
  Genera el ZIP portable de ISC Email Generator para Windows x64.

.DESCRIPTION
  Compila el frontend, descarga y verifica Python 3.12 embebible y pip, instala
  wheels cerrados dentro del runtime y prueba el paquete sin usar Python o Node
  del PATH en ejecución. El equipo destinatario solo debe descomprimir e iniciar.

.PARAMETER SkipFrontendBuild
  Conserva frontend\dist tal como está. Útil si ya se ejecutaron los checks.

.PARAMETER SkipSmokeTest
  Omite solamente la prueba final de inicio/detención. No recomendado.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File ".\Empaquetar distribución.ps1"
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$pythonVersion = '3.12.10'
$pythonArchiveName = "python-$pythonVersion-embed-amd64.zip"
$pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/$pythonArchiveName"
$pythonSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
$pipVersion = '25.0.1'
$pipWheelName = "pip-$pipVersion-py3-none-any.whl"
$pipUrl = 'https://files.pythonhosted.org/packages/c9/bc/b7db44f5f39f9d0494071bddae6880eb645970366d0a200022a1a93d57f5/pip-25.0.1-py3-none-any.whl'
$pipSha256 = 'c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f'

$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$stageName = 'ISC Email Generator portable'
$stage = Join-Path $env:TEMP "$stageName $([guid]::NewGuid().ToString('N'))"
$downloadDir = Join-Path $env:TEMP "isc-email-generator-download-$([guid]::NewGuid().ToString('N'))"
$smokeState = Join-Path $env:TEMP "isc-email-generator-state-$([guid]::NewGuid().ToString('N'))"
$outDir = Join-Path $root 'dist'
$zipPath = Join-Path $outDir 'isc-email-generator-windows-x64.zip'
$portableRequirements = Join-Path $root 'backend\requirements-portable-win-x64.txt'

function Copy-Tree {
    param([string]$From, [string]$To)
    if (-not (Test-Path -LiteralPath $From)) {
        throw "Falta el contenido requerido: $From"
    }
    $parent = Split-Path -Parent $To
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $From -Destination $To -Recurse -Force
}

function Download-VerifiedFile {
    param(
        [string]$Uri,
        [string]$Destination,
        [string]$ExpectedSha256
    )
    Write-Host "Descargando $Uri"
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "La verificación SHA-256 falló para $(Split-Path -Leaf $Destination). Esperado: $ExpectedSha256; obtenido: $actual"
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "El comando falló con código $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Remove-PythonCaches {
    param([string]$Path)
    Get-ChildItem -LiteralPath $Path -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $Path -Recurse -File -Filter '*.pyc' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Remove-VerifiedTemporaryDirectory {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return
    }
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Se rechazó limpiar una ruta fuera del directorio temporal: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
}

function Get-FreeLocalPort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function Test-PortablePackage {
    param([string]$PackageRoot)
    $oldState = $env:ISC_EMAIL_GENERATOR_STATE_DIR
    $oldPort = $env:ISC_EMAIL_GENERATOR_PORT
    $oldNoBrowser = $env:ISC_EMAIL_GENERATOR_NO_BROWSER
    $oldNoninteractive = $env:ISC_EMAIL_GENERATOR_NONINTERACTIVE
    $port = Get-FreeLocalPort
    $startCommand = Join-Path $PackageRoot 'Iniciar app.cmd'
    $stopCommand = Join-Path $PackageRoot 'Detener app.cmd'
    try {
        $env:ISC_EMAIL_GENERATOR_STATE_DIR = $smokeState
        $env:ISC_EMAIL_GENERATOR_PORT = [string]$port
        $env:ISC_EMAIL_GENERATOR_NO_BROWSER = '1'
        $env:ISC_EMAIL_GENERATOR_NONINTERACTIVE = '1'
        New-Item -ItemType Directory -Path $smokeState -Force | Out-Null

        Write-Host "Probando inicio portable desde un directorio de trabajo ajeno y una ruta con espacios (puerto $port)..."
        Push-Location -LiteralPath $env:TEMP
        try {
            & $env:ComSpec /d /c ('call "{0}"' -f $startCommand)
            $startExitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($startExitCode -ne 0) {
            throw "La prueba del lanzador portable falló con código $startExitCode. Revise $smokeState\logs."
        }
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 5
        if ($health.status -ne 'ok' -or -not $health.runtime_signature) {
            throw 'La comprobación HTTP del paquete portable no devolvió el estado esperado.'
        }

        Push-Location -LiteralPath $env:TEMP
        try {
            & $env:ComSpec /d /c ('call "{0}"' -f $stopCommand)
            $stopExitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($stopExitCode -ne 0) {
            throw "La prueba de detención portable falló con código $stopExitCode."
        }
        Write-Host 'Prueba de inicio, salud HTTP y detención: correcta.' -ForegroundColor Green
    } finally {
        $pidFile = Join-Path $smokeState ".run\app-$port.pid"
        if (Test-Path -LiteralPath $pidFile) {
            $runningPid = 0
            $pidText = (Get-Content -Raw -LiteralPath $pidFile).Trim()
            if ([int]::TryParse($pidText, [ref]$runningPid)) {
                Stop-Process -Id $runningPid -Force -ErrorAction SilentlyContinue
            }
        }
        $env:ISC_EMAIL_GENERATOR_STATE_DIR = $oldState
        $env:ISC_EMAIL_GENERATOR_PORT = $oldPort
        $env:ISC_EMAIL_GENERATOR_NO_BROWSER = $oldNoBrowser
        $env:ISC_EMAIL_GENERATOR_NONINTERACTIVE = $oldNoninteractive
    }
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'Este empaquetador requiere Windows x64.'
}
if (-not (Test-Path -LiteralPath $portableRequirements -PathType Leaf)) {
    throw "Falta el lock de dependencias portables: $portableRequirements"
}

try {
    if (-not $SkipFrontendBuild) {
        $npmCommand = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
        if (-not $npmCommand) {
            throw 'Para generar el paquete se necesita Node.js con npm. El destinatario del ZIP no lo necesita.'
        }
        $npm = $npmCommand.Source
        Write-Host 'Instalando dependencias cerradas y compilando el frontend...'
        Invoke-Checked -FilePath $npm -Arguments @('ci') -WorkingDirectory (Join-Path $root 'frontend')
        Invoke-Checked -FilePath $npm -Arguments @('run', 'build') -WorkingDirectory (Join-Path $root 'frontend')
    }

    $frontendIndex = Join-Path $root 'frontend\dist\index.html'
    if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
        throw 'El frontend no está compilado. Genérelo o quite -SkipFrontendBuild.'
    }

    New-Item -ItemType Directory -Path $stage, $downloadDir -Force | Out-Null
    $pythonArchive = Join-Path $downloadDir $pythonArchiveName
    $pipWheel = Join-Path $downloadDir $pipWheelName
    Download-VerifiedFile -Uri $pythonUrl -Destination $pythonArchive -ExpectedSha256 $pythonSha256
    Download-VerifiedFile -Uri $pipUrl -Destination $pipWheel -ExpectedSha256 $pipSha256

    $runtimeDir = Join-Path $stage 'runtime'
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $runtimeDir -Force
    $pthFile = Join-Path $runtimeDir 'python312._pth'
    if (-not (Test-Path -LiteralPath $pthFile -PathType Leaf)) {
        throw 'El paquete embebible de Python no contiene python312._pth.'
    }
    @('python312.zip', '.', 'Lib\site-packages', 'import site') | Set-Content -LiteralPath $pthFile -Encoding ASCII

    $sitePackages = Join-Path $runtimeDir 'Lib\site-packages'
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($pipWheel, $sitePackages)
    $runtimePython = Join-Path $runtimeDir 'python.exe'
    Invoke-Checked -FilePath $runtimePython -Arguments @(
        '-m', 'pip', 'install',
        '--disable-pip-version-check',
        '--only-binary=:all:',
        '--no-deps',
        '--target', $sitePackages,
        '--requirement', $portableRequirements
    ) -WorkingDirectory $root

    Copy-Tree -From (Join-Path $root 'backend\app') -To (Join-Path $stage 'backend\app')
    New-Item -ItemType Directory -Path (Join-Path $stage 'backend\prompts\projects') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'backend\prompts\adaptation_rules.md') -Destination (Join-Path $stage 'backend\prompts') -Force
    foreach ($name in @('run.py', 'check_ready.py', 'requirements.txt', 'requirements-portable-win-x64.txt', '.env.example')) {
        Copy-Item -LiteralPath (Join-Path $root "backend\$name") -Destination (Join-Path $stage 'backend') -Force
    }
    Copy-Tree -From (Join-Path $root 'frontend\dist') -To (Join-Path $stage 'frontend\dist')
    Copy-Tree -From (Join-Path $root 'scripts') -To (Join-Path $stage 'scripts')
    foreach ($name in @('Iniciar app.cmd', 'Detener app.cmd', 'README.md', 'LEEME-PORTABLE.txt')) {
        Copy-Item -LiteralPath (Join-Path $root $name) -Destination $stage -Force
    }

    @(
        'ISC Email Generator - Windows x64',
        "Python=$pythonVersion",
        "pip=$pipVersion",
        "requirements=$(Split-Path -Leaf $portableRequirements)",
        'El runtime y las dependencias fueron incorporados durante el empaquetado.'
    ) | Set-Content -LiteralPath (Join-Path $stage 'VERSION-PORTABLE.txt') -Encoding UTF8

    Remove-PythonCaches -Path $stage
    Invoke-Checked -FilePath $runtimePython -Arguments @(
        '-B', '-c',
        'import platform, sys; import fastapi, httpx, pydantic, truststore, uvicorn; assert sys.version_info[:2] == (3, 12); assert platform.machine().upper() in {"AMD64", "X86_64"}'
    ) -WorkingDirectory $env:TEMP

    if (-not $SkipSmokeTest) {
        Test-PortablePackage -PackageRoot $stage
    }
    Remove-PythonCaches -Path $stage

    $forbidden = @(
        (Join-Path $stage 'backend\.env'),
        (Join-Path $stage 'backend\.venv'),
        (Join-Path $stage 'backend\data'),
        (Join-Path $stage 'frontend\node_modules'),
        (Join-Path $stage '.git'),
        (Join-Path $stage 'logs'),
        (Join-Path $stage '.run')
    )
    foreach ($path in $forbidden) {
        if (Test-Path -LiteralPath $path) {
            throw "El stage contiene un archivo o directorio prohibido: $path"
        }
    }
    $unexpectedLogs = Get-ChildItem -LiteralPath $stage -Recurse -File -Filter '*.log' -ErrorAction SilentlyContinue
    if ($unexpectedLogs) {
        throw 'El stage contiene logs y se canceló el empaquetado.'
    }

    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $sizeMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
    Write-Host ''
    Write-Host "Paquete generado y validado: $zipPath ($sizeMb MB)" -ForegroundColor Green
    Write-Host 'Destino: descomprimir y ejecutar "Iniciar app.cmd". No requiere instalaciones ni permisos de administrador.'
} finally {
    foreach ($temporaryPath in @($stage, $downloadDir, $smokeState)) {
        Remove-VerifiedTemporaryDirectory -Path $temporaryPath
    }
}
