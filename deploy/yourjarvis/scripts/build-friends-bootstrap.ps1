[CmdletBinding()]
param(
    [string] $Output = (Join-Path $PSScriptRoot 'dist\JARVIS-Friends-Bootstrap.zip'),
    [string] $Version = '1.0.0',
    [string] $UpdateManifestUrl = 'https://github.com/QcShadow/YourJarvis-link/releases/latest/download/update-github.json',
    [string] $MirrorUpdateManifestUrl = 'https://gitee.com/QcShadow/your-jarvis-link/raw/main/update.json'
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$desktop = Join-Path $root 'dist\share-desktop'
$outputPath = [IO.Path]::GetFullPath($Output)

& (Join-Path $root 'build-desktop.ps1') `
    -OutputDirectory $desktop `
    -Version $Version `
    -UpdateManifestUrl $UpdateManifestUrl `
    -MirrorUpdateManifestUrl $MirrorUpdateManifestUrl
if ($LASTEXITCODE -ne 0) { throw 'Desktop launcher build failed.' }

$python = Join-Path $root 'src\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw "Missing project Python: $python" }
& $python (Join-Path $root 'src\deploy\share\build_package.py') `
    --root $root `
    --output $outputPath `
    --desktop
if ($LASTEXITCODE -ne 0) { throw 'Friends bootstrap package build failed.' }
Write-Host "Friends bootstrap package: $outputPath"
