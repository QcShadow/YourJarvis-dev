[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $OllamaArgs
)

. (Join-Path $PSScriptRoot 'env.ps1')

if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
    throw "Ollama is not installed yet at $script:JarvisOllama"
}

& $script:JarvisOllama @OllamaArgs
exit $LASTEXITCODE
