[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'env.ps1')

try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
    Write-Host 'Ollama is already running on http://127.0.0.1:11434.'
    return
} catch {
    # Start the local server below.
}

if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
    throw "Ollama is not installed yet at $script:JarvisOllama"
}

$ollamaHome = Join-Path $script:JarvisRoot 'runtimes\ollama-home'
New-Item -ItemType Directory -Path $ollamaHome -Force | Out-Null
# Ollama has no separate OLLAMA_HOME setting for its small key/config folder.
# Scope USERPROFILE to this child process only; the Windows account is unchanged.
$env:USERPROFILE = $ollamaHome

$stdout = Join-Path $script:JarvisRoot 'logs\ollama.stdout.log'
$stderr = Join-Path $script:JarvisRoot 'logs\ollama.stderr.log'
Start-Process -FilePath $script:JarvisOllama `
    -ArgumentList 'serve' `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr | Out-Null

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
        Write-Host 'Ollama started on http://127.0.0.1:11434.'
        return
    } catch {
        # Keep waiting until the bounded startup timeout expires.
    }
}

throw "Ollama did not become ready. Check $stderr"
