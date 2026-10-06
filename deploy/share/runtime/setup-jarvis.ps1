[CmdletBinding()]
param([switch] $NoModelDownload)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
Write-Host 'Choose a model/API and a voice preset. Local starter models are downloaded after configuration.'
& $script:JarvisUv run --no-sync --project $script:JarvisSource jarvis --quiet setup wizard
if ($LASTEXITCODE -ne 0) { throw 'Configuration was not saved.' }
$launchConfig = Get-JarvisLaunchConfig
if (-not $NoModelDownload -and $launchConfig.engine -eq 'ollama') {
    & (Join-Path $PSScriptRoot 'start-ollama.ps1') | Out-Null
    $installed = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
    if ($launchConfig.model -notin @($installed.models | ForEach-Object { $_.name })) {
        Write-Host "Downloading selected model: $($launchConfig.model)"
        & $script:JarvisOllama pull $launchConfig.model
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Retry with ollama.cmd pull MODEL.' }
    }
}
Write-Host 'Configuration ready. Open JARVIS.exe or start-gui.cmd.'
