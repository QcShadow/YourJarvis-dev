# Ensure cmdlets remain available when launched by a GUI with inherited PSModulePath.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility')
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management')
$script:JarvisRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$env:OPENJARVIS_HOME = $script:JarvisRoot
$env:PYTHONUTF8 = '1'
$env:OLLAMA_MODELS = Join-Path $script:JarvisRoot 'models\ollama'
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
$localNoProxy = 'localhost,127.0.0.1,::1'
$existingNoProxy = if ($env:NO_PROXY) { $env:NO_PROXY } elseif ($env:no_proxy) { $env:no_proxy } else { '' }
$env:NO_PROXY = if ($existingNoProxy) { "$localNoProxy,$existingNoProxy" } else { $localNoProxy }
$env:no_proxy = $env:NO_PROXY
$env:HF_HOME = Join-Path $script:JarvisRoot 'cache\huggingface'
$env:UV_CACHE_DIR = Join-Path $script:JarvisRoot 'cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $script:JarvisRoot 'runtimes\python'
$env:UV_PYTHON_BIN_DIR = Join-Path $script:JarvisRoot 'tools\python-bin'
$env:CARGO_HOME = Join-Path $script:JarvisRoot 'runtimes\rust\cargo'
$env:RUSTUP_HOME = Join-Path $script:JarvisRoot 'runtimes\rust\rustup'
$env:CARGO_TARGET_DIR = Join-Path $script:JarvisRoot 'cache\cargo-target'
$env:CARGO_HTTP_MULTIPLEXING = 'false'
$env:CARGO_NET_RETRY = '10'
$env:TEMP = Join-Path $script:JarvisRoot 'cache\tmp'
$env:TMP = $env:TEMP
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:HF_HUB_OFFLINE = '1'
$env:JARVIS_SKIP_MODEL_PICK = '1'
$env:PYTHONWARNINGS = @(
    'ignore:dropout option adds dropout:UserWarning:torch.nn.modules.rnn',
    'ignore:`torch.nn.utils.weight_norm` is deprecated:FutureWarning:torch.nn.utils.weight_norm',
    'ignore:pkg_resources is deprecated as an API:UserWarning:jieba._compat'
) -join ','

New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $script:JarvisRoot 'logs') -Force | Out-Null

$pathEntries = @(
    (Join-Path $script:JarvisRoot 'tools\uv'),
    (Join-Path $script:JarvisRoot 'tools\python-bin'),
    (Join-Path $script:JarvisRoot 'runtimes\ollama'),
    (Join-Path $script:JarvisRoot 'runtimes\rust\cargo\bin'),
    (Join-Path $script:JarvisRoot 'bin')
)
$env:Path = (($pathEntries + @($env:Path)) -join ';')

$script:JarvisUv = Join-Path $script:JarvisRoot 'tools\uv\uv.exe'
$script:JarvisSource = Join-Path $script:JarvisRoot 'src'
$script:JarvisOllama = Join-Path $script:JarvisRoot 'runtimes\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
    $installedOllama = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($installedOllama) { $script:JarvisOllama = $installedOllama.Source }
    elseif (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe')) {
        $script:JarvisOllama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    }
}

function Get-JarvisLaunchConfig {
    $python = Join-Path $script:JarvisSource '.venv\Scripts\python.exe'
    $config = Join-Path $script:JarvisRoot 'config.toml'
    if (-not (Test-Path -LiteralPath $config)) {
        throw 'Open JARVIS-Install.exe to complete configuration.'
    }
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Open JARVIS-Install.exe to install or repair the runtime.'
    }
    # Passing source through stdin preserves quotes in Windows PowerShell 5.1.
    $configReader = @'
import json, sys, tomllib
with open(sys.argv[1], "rb") as source:
    config = tomllib.load(source)
print(json.dumps({
    "engine": config.get("engine", {}).get("default", "ollama"),
    "agent": config.get("agent", {}).get("default_agent", "orchestrator"),
    "model": config.get("intelligence", {}).get("default_model", ""),
}))
'@
    $launchJson = $configReader | & $python - $config
    if ($LASTEXITCODE -ne 0) { throw 'Invalid config.toml; see the error above.' }
    return ($launchJson | ConvertFrom-Json)
}
