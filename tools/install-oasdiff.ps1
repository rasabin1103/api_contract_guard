# Instalar solo el binario fijado, verificando la descarga antes de extraerla.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$destination = Join-Path $root 'tools/bin'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
$archiveName = "oasdiff_1.34.0_windows_$architecture.tar.gz"
$release = 'https://github.com/oasdiff/oasdiff/releases/download/v1.34.0'
$archive = Join-Path $destination $archiveName
Invoke-WebRequest "$release/$archiveName" -UseBasicParsing -OutFile $archive
Invoke-WebRequest "$release/checksums.txt" -UseBasicParsing -OutFile (Join-Path $destination 'checksums.txt')
$line = Get-Content (Join-Path $destination 'checksums.txt') | Where-Object { $_.EndsWith($archiveName) }
if (-not $line) { throw 'Missing upstream checksum' }
$expected = ($line -split '\s+')[0]
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw 'Checksum mismatch' }
tar -xzf $archive -C $destination
if ($LASTEXITCODE -ne 0) { throw 'Extraction failed' }
$actualVersion = & (Join-Path $destination 'oasdiff.exe') --version
if ($LASTEXITCODE -ne 0 -or $actualVersion -ne 'oasdiff version 1.34.0') { throw 'Unexpected engine version' }
Write-Host $actualVersion
