[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $JarvisArgs
)

. (Join-Path $PSScriptRoot 'env.ps1')

if (-not (Test-Path -LiteralPath $script:JarvisUv)) {
    throw "uv was not found at $script:JarvisUv"
}

$effectiveArgs = @($JarvisArgs)
$command = if ($effectiveArgs.Count -gt 0) { $effectiveArgs[0] } else { '' }

if ($command -in @('ask', 'chat')) {
    # Make the common entry points self-contained and prevent OpenJarvis from
    # silently falling back to a cloud engine after a transient health probe.
    $hasExplicitEngine = @($effectiveArgs | Where-Object {
        $_ -eq '--engine' -or $_ -eq '-e' -or $_ -like '--engine=*'
    }).Count -gt 0

    if (-not $hasExplicitEngine) {
        $launchConfig = Get-JarvisLaunchConfig
        $tail = if ($effectiveArgs.Count -gt 1) {
            @($effectiveArgs[1..($effectiveArgs.Count - 1)])
        } else {
            @()
        }
        $effectiveArgs = @($command, '--engine', $launchConfig.engine) + $tail
    }

    $selectedEngine = ''
    for ($argIndex = 1; $argIndex -lt $effectiveArgs.Count; $argIndex++) {
        if ($effectiveArgs[$argIndex] -in @('--engine', '-e') -and $argIndex + 1 -lt $effectiveArgs.Count) {
            $selectedEngine = $effectiveArgs[$argIndex + 1]
        } elseif ($effectiveArgs[$argIndex] -like '--engine=*') {
            $selectedEngine = $effectiveArgs[$argIndex].Substring(9)
        }
    }
    if ($selectedEngine -eq 'ollama') {
        & (Join-Path $script:JarvisRoot 'start-ollama.ps1') | Out-Null
    }

    if ($command -eq 'chat') {
        $hasRuntimeChoice = @($effectiveArgs | Where-Object {
            $_ -eq '--skip-runtime-panel' -or
            $_ -eq '--num-gpu' -or $_ -like '--num-gpu=*' -or
            $_ -eq '--num-ctx' -or $_ -like '--num-ctx=*' -or
            $_ -eq '--pick-model'
        }).Count -gt 0
        if (-not $hasRuntimeChoice) {
            $effectiveArgs += '--skip-runtime-panel'
        }
    }
}

& $script:JarvisUv run --no-sync --project $script:JarvisSource jarvis @effectiveArgs
exit $LASTEXITCODE
