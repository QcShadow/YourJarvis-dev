[CmdletBinding()]
param()

$root = $PSScriptRoot
$pidFile = Join-Path $root 'logs\gui-server.pid'

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'JARVIS GUI is not running (no PID file).'
    return
}

$rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
$serverPid = 0
if (-not [int]::TryParse($rawPid, [ref] $serverPid)) {
    throw "Invalid PID file: $pidFile"
}

$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($null -ne $process) {
    $processPath = $process.Path
    if ($processPath -notlike '*python*.exe' -and $processPath -notlike '*uv.exe') {
        throw "PID $serverPid is not a JARVIS server process; refusing to stop it."
    }
    # uv launches the Python API server as a child process. Stop the validated
    # process tree so the child cannot keep port 8000 occupied.
    & taskkill.exe /PID $serverPid /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stop JARVIS GUI process tree $serverPid."
    }
    Write-Host "Stopped JARVIS GUI server (PID $serverPid)."
} else {
    Write-Host 'JARVIS GUI server was already stopped.'
}

Remove-Item -LiteralPath $pidFile -Force
