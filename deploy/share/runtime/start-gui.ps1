[CmdletBinding()]
param(
    [switch] $NoBrowser
)

. (Join-Path $PSScriptRoot 'env.ps1')

$serverUrl = 'http://127.0.0.1:8000'
$healthUrl = "$serverUrl/health"
$pidFile = Join-Path $script:JarvisRoot 'logs\gui-server.pid'
$stdout = Join-Path $script:JarvisRoot 'logs\gui-server.stdout.log'
$stderr = Join-Path $script:JarvisRoot 'logs\gui-server.stderr.log'

function Test-JarvisGuiServer {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return $response.status -eq 'ok'
    } catch {
        return $false
    }
}

$launchConfig = Get-JarvisLaunchConfig
if ($launchConfig.engine -eq 'ollama') {
    & (Join-Path $script:JarvisRoot 'start-ollama.ps1') | Out-Null
}

if (-not (Test-JarvisGuiServer)) {
    $arguments = @(
        'run', '--no-sync', '--project', ('"{0}"' -f $script:JarvisSource),
        'jarvis', 'serve',
        '--host', '127.0.0.1',
        '--port', '8000',
        '--engine', $launchConfig.engine,
        '--agent', $launchConfig.agent
    )
    $process = Start-Process -FilePath $script:JarvisUv `
        -ArgumentList $arguments `
        -WorkingDirectory $script:JarvisRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-JarvisGuiServer) {
            break
        }
        if ($process.HasExited) {
            $details = if (Test-Path -LiteralPath $stderr) {
                (Get-Content -LiteralPath $stderr -Tail 25) -join [Environment]::NewLine
            } else {
                'No server error log was created.'
            }
            throw "JARVIS GUI server exited during startup.`n$details"
        }
    }
}

if (-not (Test-JarvisGuiServer)) {
    throw "JARVIS GUI did not become ready. Check $stderr"
}

# Warm the local TTS model in a detached helper so the browser can open at
# once while the first spoken reply avoids paying the full cold-start cost.
$prewarmCommand = @"
try {
    Invoke-RestMethod -Uri '$serverUrl/v1/speech/tts/health' -TimeoutSec 180 | Out-Null
} catch {
}
"@
$encodedPrewarm = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($prewarmCommand)
)
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoLogo', '-NoProfile', '-EncodedCommand', $encodedPrewarm) `
    -WindowStyle Hidden | Out-Null

if (-not $NoBrowser) {
    Start-Process $serverUrl
}

Write-Host "JARVIS GUI is ready at $serverUrl"
