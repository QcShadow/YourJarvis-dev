[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $OllamaArgs
)

. (Join-Path $PSScriptRoot 'env.ps1')

if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
    throw "Ollama is not installed yet at $script:JarvisOllama"
}

if ($OllamaArgs -and $OllamaArgs[0] -ne 'serve') { & (Join-Path $script:JarvisRoot 'start-ollama.ps1') | Out-Null }
& $script:JarvisOllama @OllamaArgs
exit $LASTEXITCODE
