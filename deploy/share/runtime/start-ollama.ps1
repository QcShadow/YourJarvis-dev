[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
. (Join-Path $PSScriptRoot 'runtime-state.ps1')
$executable = Join-Path $script:JarvisRoot 'runtimes\ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw '本安装目录缺少模型运行组件，请点击修复安装。' }
$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $script:JarvisRoot 'logs\ollama-start.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $state = Read-JarvisState 'ollama-runtime'
    $owned = Get-OwnedJarvisProcess $state $executable
    if (-not ($owned -and (Test-JarvisEndpoint ($state.url + '/api/tags')))) {
        Stop-OwnedJarvisService 'ollama-runtime' $executable
        $port = Get-FreeJarvisPort
        $env:OLLAMA_HOST = "http://127.0.0.1:$port"
        $ollamaHome = Join-Path $script:JarvisRoot 'runtimes\ollama-home'
        New-Item -ItemType Directory -Path $ollamaHome -Force | Out-Null
        $previousProfile = $env:USERPROFILE
        try {
            $env:USERPROFILE = $ollamaHome
            $process = Start-JarvisService $executable @('serve') (Join-Path $script:JarvisRoot 'logs\ollama.stdout.log') (Join-Path $script:JarvisRoot 'logs\ollama.stderr.log')
        } finally { $env:USERPROFILE = $previousProfile }
        $state = Write-JarvisState 'ollama-runtime' $process $port
        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Milliseconds 500; $process.Refresh()
            if ($process.HasExited) { break }
            if (Test-JarvisEndpoint ($state.url + '/api/tags')) { $ready = $true; break }
        }
        if (-not $ready) { Stop-OwnedJarvisService 'ollama-runtime' $executable; throw '本安装目录的模型服务启动失败，请查看 logs\ollama.stderr.log 后重试。' }
    }
    $env:OLLAMA_HOST = $state.url
    $env:JARVIS_LOCAL_OLLAMA = $state.url
    Write-Host "本安装目录的模型服务已就绪：$($state.url)"
} finally { if ($lock) { $lock.Dispose() } }
