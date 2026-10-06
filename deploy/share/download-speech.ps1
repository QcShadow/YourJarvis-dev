[CmdletBinding()]
param([switch] $English)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
$env:HF_HUB_OFFLINE = '0'
$python = Join-Path $script:JarvisSource '.venv\Scripts\python.exe'
$downloadArgs = @((Join-Path $script:JarvisRoot 'scripts\download_speech_assets.py'), '--root', $script:JarvisRoot)
if ($English) { $downloadArgs += '--english' }
& $python @downloadArgs
if ($LASTEXITCODE -ne 0) { throw 'Speech asset download failed. Re-run to resume.' }
if ($English) {
    $englishG2p = 'https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl'
    & $script:JarvisUv pip install --python $python $englishG2p
    if ($LASTEXITCODE -ne 0) { throw 'English voice language resources could not be installed. Run bootstrap.cmd -Voice first.' }
}
Write-Host 'Speech assets ready. Run bootstrap.cmd -Voice if voice dependencies are not installed.'
