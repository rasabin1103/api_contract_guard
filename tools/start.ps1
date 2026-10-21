# Lanzador de usuario. La ruta del repositorio se calcula desde este fichero,
# por lo que funciona tambien al abrir Iniciar.cmd desde otra carpeta.
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root 'backend'
$runtime = Join-Path $root '.runtime'
$baseUrl = "http://127.0.0.1:$Port"
$server = $null
$setupLock = $null
$exitCode = 0

function Invoke-Checked {
    # Los ejecutables nativos no lanzan excepciones PowerShell al devolver un error.
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo al ejecutar $Executable (codigo $LASTEXITCODE)."
    }
}

function Test-Guard {
    # No reutilizar un programa ajeno que casualmente responda en el mismo puerto.
    try {
        $health = Invoke-RestMethod "$baseUrl/health" -TimeoutSec 2
        $schema = Invoke-RestMethod "$baseUrl/openapi.json" -TimeoutSec 2
        return ($health.status -eq 'ok' -and $schema.info.title -eq 'ASE API Contract Guard')
    }
    catch { return $false }
}

function Assert-FreePort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() }
    catch { throw "El puerto $Port esta ocupado por otro servicio. Usa Iniciar.cmd -Port 8011." }
    finally { $listener.Stop() }
}

function Open-Swagger {
    Write-Host "Swagger listo: $baseUrl/docs" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "$baseUrl/docs" }
}

try {
    Write-Host 'ASE API Contract Guard - instalacion y arranque local' -ForegroundColor Cyan
    if (Test-Guard) {
        Write-Host 'El servicio ya esta activo; se reutiliza sin modificarlo.'
        if ($Verify) {
            throw 'La verificacion de instalacion requiere un puerto libre. Usa -Port 8011 -Verify.'
        }
        Open-Swagger
    }
    else {
        Assert-FreePort
        New-Item -ItemType Directory -Force -Path $runtime | Out-Null
        try {
            $setupLock = [System.IO.File]::Open((Join-Path $runtime 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        }
        catch { throw 'Ya hay otra instalacion en curso. Espera a que termine y vuelve a intentarlo.' }

        # Herramientas y caches locales: no instalar Python global ni modificar el PATH.
        $env:UV_CACHE_DIR = Join-Path $runtime 'cache'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
        $env:UV_PYTHON_BIN_DIR = Join-Path $runtime 'bin'
        $env:UV_NO_MODIFY_PATH = '1'
        $env:UV_NO_PROGRESS = '1'
        $env:PYTHONUTF8 = '1'
        $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        $uvDirectory = Join-Path $runtime 'uv'
        $uv = Join-Path $uvDirectory 'uv.exe'
        if (-not (Test-Path -LiteralPath $uv)) {
            Write-Host '[1/4] Descargando instalador local de Python (uv 0.12.12)...'
            $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
            $archiveName = "uv-$architecture-pc-windows-msvc.zip"
            $release = 'https://github.com/astral-sh/uv/releases/download/0.12.12'
            $archive = Join-Path $runtime $archiveName
            $checksumFile = "$archive.sha256"
            Invoke-WebRequest "$release/$archiveName" -UseBasicParsing -OutFile $archive
            Invoke-WebRequest "$release/$archiveName.sha256" -UseBasicParsing -OutFile $checksumFile
            $expected = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0]
            if ($expected -notmatch '^[a-fA-F0-9]{64}$' -or
                (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) {
                throw 'La descarga de uv no coincide con el checksum oficial.'
            }
            Expand-Archive -LiteralPath $archive -DestinationPath $uvDirectory -Force
            if (-not (Test-Path -LiteralPath $uv)) { throw 'No se encontro uv.exe en el archivo oficial.' }
        }
        Invoke-Checked $uv @('--version')

        Write-Host '[2/4] Preparando Python 3.13 y dependencias...'
        $venv = Join-Path $runtime 'venv'
        $python = Join-Path $venv 'Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $python)) {
            Invoke-Checked $uv @('venv', '--python', '3.13', '--managed-python', $venv)
        }
        Invoke-Checked $uv @('pip', 'install', '--python', $python, '-r', (Join-Path $backend 'requirements.lock'))
        Invoke-Checked $uv @('pip', 'install', '--python', $python, '--no-deps', '-e', $backend)

        Write-Host '[3/4] Comprobando motor oasdiff 1.34.0...'
        $oasdiff = Join-Path $root 'tools/bin/oasdiff.exe'
        $engineReady = $false
        if (Test-Path -LiteralPath $oasdiff) {
            $engineVersion = & $oasdiff --version
            $engineReady = ($LASTEXITCODE -eq 0 -and $engineVersion -eq 'oasdiff version 1.34.0')
        }
        if (-not $engineReady) { & (Join-Path $PSScriptRoot 'install-oasdiff.ps1') }
        Invoke-Checked $oasdiff @('--version')
        $env:ACG_OASDIFF_PATH = $oasdiff

        Write-Host '[4/4] Aplicando migraciones y arrancando API...'
        Push-Location $backend
        try { Invoke-Checked $python @('-m', 'alembic', 'upgrade', 'head') }
        finally { Pop-Location }

        # Comprobar otra vez tras instalar: otro proceso pudo ocupar el puerto mientras tanto.
        Assert-FreePort
        $logs = Join-Path $runtime 'logs'
        New-Item -ItemType Directory -Force -Path $logs | Out-Null
        $stdout = Join-Path $logs "api-$Port.log"
        $stderr = Join-Path $logs "api-$Port.error.log"
        $server = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port"
        ) -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $deadline = [DateTime]::UtcNow.AddSeconds(60)
        while (-not (Test-Guard)) {
            $server.Refresh()
            if ($server.HasExited) {
                throw "El servidor se ha detenido. Revisa $stderr"
            }
            if ([DateTime]::UtcNow -gt $deadline) { throw "La API no respondio a tiempo. Revisa $stderr" }
            Start-Sleep -Milliseconds 300
        }
        $setupLock.Dispose()
        $setupLock = $null

        if ($Verify) {
            Invoke-Checked $python @((Join-Path $PSScriptRoot 'smoke_api.py'), '--url', $baseUrl)
            Write-Host 'Instalacion y flujo completo verificados. Se detiene solo el servidor de esta prueba.' -ForegroundColor Green
        }
        else {
            Open-Swagger
            Write-Host 'Manten esta ventana abierta. Pulsa Ctrl+C para detener este servicio.'
            Write-Host "Logs: $logs"
            while (-not $server.HasExited) {
                Start-Sleep -Milliseconds 500
                $server.Refresh()
            }
            throw "El servidor ha terminado inesperadamente. Revisa $stderr"
        }
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'La primera instalacion necesita internet. No se borran contratos ni datos existentes.'
    $exitCode = 1
}
finally {
    # Solo detener el hijo que ha creado este lanzador; nunca una instancia reutilizada.
    if ($null -ne $setupLock) { $setupLock.Dispose() }
    if ($null -ne $server) {
        $server.Refresh()
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
        $server.Dispose()
    }
}
exit $exitCode
