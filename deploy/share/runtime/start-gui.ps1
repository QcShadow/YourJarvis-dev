[CmdletBinding()]
param([switch] $NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
. (Join-Path $PSScriptRoot 'env.ps1')
. (Join-Path $PSScriptRoot 'runtime-state.ps1')
$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $script:JarvisRoot 'logs\gui-start.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $launchConfig = Get-JarvisLaunchConfig
    $python = Join-Path $script:JarvisSource '.venv\Scripts\python.exe'
    $state = Read-JarvisState 'gui-runtime'
    $owned = Get-OwnedJarvisProcess $state $python
    if (-not ($owned -and $state.instance -and (Test-JarvisEndpoint ($state.url + '/health') $state.instance))) {
        Stop-OwnedJarvisService 'gui-runtime' $python
        if ($launchConfig.engine -eq 'ollama') {
            & (Join-Path $script:JarvisRoot 'start-ollama.ps1') | Out-Null
            $env:JARVIS_LOCAL_OLLAMA = $env:OLLAMA_HOST
        }
        $env:JARVIS_PORTABLE_CLIENT = '1'
        $env:OPENJARVIS_API_KEY = $null; $env:PYTHONHOME = $null; $env:PYTHONPATH = $null
        $ready = $false
        for ($retry = 0; $retry -lt 3 -and -not $ready; $retry++) {
            $port = Get-FreeJarvisPort
            $env:JARVIS_DESKTOP_INSTANCE = [Guid]::NewGuid().ToString('N')
            $arguments = @('-m','openjarvis.cli','--quiet','serve','--host','127.0.0.1','--port',[string]$port,'--engine',$launchConfig.engine,'--agent',$launchConfig.agent,'--model',('"{0}"' -f $launchConfig.model))
            $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $script:JarvisRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $script:JarvisRoot 'logs\gui-server.stdout.log') -RedirectStandardError (Join-Path $script:JarvisRoot 'logs\gui-server.stderr.log') -PassThru
            $state = Write-JarvisState 'gui-runtime' $process $port $env:JARVIS_DESKTOP_INSTANCE
            for ($attempt = 0; $attempt -lt 180; $attempt++) {
                Start-Sleep -Milliseconds 500; $process.Refresh()
                if ($process.HasExited) { break }
                if (Test-JarvisEndpoint ($state.url + '/health') $state.instance) { $ready = $true; break }
            }
            if (-not $ready) {
                Stop-OwnedJarvisService 'gui-runtime' $python
                $details = (Get-Content -LiteralPath (Join-Path $script:JarvisRoot 'logs\gui-server.stderr.log') -Tail 20) -join [Environment]::NewLine
                if ($details -notmatch 'address already in use|10048') { throw "本安装目录的后台未启动成功，请点击修复安装。`n$details" }
            }
        }
        if (-not $ready) { throw '本地端口暂时不可用，请重试启动。' }
    }
    if (-not $NoBrowser) { Start-Process $state.url }
    Write-Host ('JARVIS_RUNTIME|' + ($state | ConvertTo-Json -Compress))
} finally { if ($lock) { $lock.Dispose() } }
