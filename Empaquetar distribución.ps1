<#
.SYNOPSIS
  Genera un ZIP de distribucion para otra PC Windows.

.DESCRIPTION
  Incluye el backend (sin .venv ni .env), el frontend ya compilado,
  los lanzadores y la documentacion. Excluye datos locales, secretos,
  dependencias y artefactos de desarrollo.

  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File "Empaquetar distribucion.ps1"
#>
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8

$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$stageName = 'isc-email-generator'
$stage = Join-Path $env:TEMP "$stageName-dist-$([guid]::NewGuid().ToString('N'))"
$outDir = Join-Path $root 'dist'
$zipPath = Join-Path $outDir "$stageName.zip"

function Copy-Tree {
    param([string]$From, [string]$To)
    if (-not (Test-Path -LiteralPath $From)) { throw "Falta el contenido requerido: $From" }
    $parent = Split-Path -Parent $To
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $From -Destination $To -Recurse -Force
}

try {
    $frontendIndex = Join-Path $root 'frontend\dist\index.html'
    if (-not (Test-Path -LiteralPath $frontendIndex)) {
        throw "El frontend no esta compilado. Ejecute 'npm.cmd run build' dentro de frontend\ y vuelva a intentarlo."
    }

    $venvPython = Join-Path $root 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Warning 'No se encontro backend\.venv; el destinatario debera ejecutar "Preparar entorno.cmd" (igual que siempre).'
    }

    Write-Host "Preparando paquete en $stage ..."
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    # Backend: codigo, prompts, arranque y requirements. Nunca .venv, .env ni data.
    Copy-Tree -From (Join-Path $root 'backend\app') -To (Join-Path $stage 'backend\app')
    Copy-Tree -From (Join-Path $root 'backend\prompts') -To (Join-Path $stage 'backend\prompts')
    Copy-Item -LiteralPath (Join-Path $root 'backend\run.py') -Destination (Join-Path $stage 'backend') -Force
    Copy-Item -LiteralPath (Join-Path $root 'backend\check_ready.py') -Destination (Join-Path $stage 'backend') -Force
    Copy-Item -LiteralPath (Join-Path $root 'backend\requirements.txt') -Destination (Join-Path $stage 'backend') -Force
    Copy-Item -LiteralPath (Join-Path $root 'backend\.env.example') -Destination (Join-Path $stage 'backend') -Force

    # Frontend ya compilado: el destinatario no necesita Node.js.
    Copy-Tree -From (Join-Path $root 'frontend\dist') -To (Join-Path $stage 'frontend\dist')

    # Lanzadores, scripts y documentacion.
    foreach ($name in @('Iniciar app.cmd', 'Detener app.cmd', 'Preparar entorno.cmd', 'README.md', 'AGENTS.md')) {
        Copy-Item -LiteralPath (Join-Path $root $name) -Destination $stage -Force
    }
    Copy-Tree -From (Join-Path $root 'scripts') -To (Join-Path $stage 'scripts')

    # Guías de estilo personales: son contenido del usuario, no del proyecto.
    $projectsDir = Join-Path $stage 'backend\prompts\projects'
    if (Test-Path -LiteralPath $projectsDir) {
        Get-ChildItem -LiteralPath $projectsDir -File | Where-Object { $_.Name -ne '.gitkeep' } | Remove-Item -Force
    }

    # Artefactos de desarrollo que no deben viajar.
    Get-ChildItem -LiteralPath $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $stage -Recurse -File -Filter '*.pyc' | Remove-Item -Force

    # Carpetas vacias que la app crea al correr.
    New-Item -ItemType Directory -Path (Join-Path $stage 'backend\data') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stage 'logs') -Force | Out-Null

    # Salvaguarda: si algo filtrado llegara a existir en stage, se elimina.
    foreach ($forbidden in @(
            (Join-Path $stage 'backend\.env'),
            (Join-Path $stage 'backend\.venv'),
            (Join-Path $stage 'frontend\node_modules'),
            (Join-Path $stage '.git')
        )) {
        if (Test-Path -LiteralPath $forbidden) {
            Remove-Item -LiteralPath $forbidden -Recurse -Force
            Write-Warning "Se excluyo del paquete: $forbidden"
        }
    }

    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal

    $sizeMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
    Write-Host ''
    Write-Host "Paquete generado: $zipPath ($sizeMb MB)" -ForegroundColor Green
    Write-Host 'En la PC destino: descomprimir, ejecutar "Preparar entorno.cmd" una vez y luego "Iniciar app.cmd".'
    Write-Host 'El ZIP no contiene .env, datos locales ni .venv: cada usuario configura sus propias credenciales.'
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}
