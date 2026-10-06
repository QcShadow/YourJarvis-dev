[CmdletBinding()]
param([switch] $Voice)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
if (-not (Test-Path -LiteralPath $script:JarvisUv)) { throw 'Bundled tools\uv\uv.exe is missing.' }
Write-Host 'Installing an isolated Python environment. First run requires internet access.'
$syncArgs = @('sync', '--frozen', '--project', $script:JarvisSource, '--python', '3.12', '--no-dev', '--extra', 'server')
if ($Voice) { $syncArgs += @('--extra', 'desktop', '--extra', 'voice') }
& $script:JarvisUv @syncArgs
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; see the error above.' }
if ($Voice) {
    & $script:JarvisUv pip install --python (Join-Path $script:JarvisSource '.venv\Scripts\python.exe') 'misaki[zh]' 'sherpa-onnx-core==1.13.8'
    if ($LASTEXITCODE -ne 0) { throw 'Chinese voice dependencies could not be installed.' }
}
Write-Host 'Runtime ready. Run setup-jarvis.cmd to choose your own model or API.'
Write-Host 'Local models require Ollama: https://ollama.com/download/windows (or a bundled runtime).'
Write-Host 'Chinese voice weights are optional: use a speech package or download-speech.cmd.'
