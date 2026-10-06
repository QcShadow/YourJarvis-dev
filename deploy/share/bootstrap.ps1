[CmdletBinding()]
param([switch] $Voice)
& (Join-Path $PSScriptRoot 'install-jarvis.ps1') -Voice:$Voice
exit $LASTEXITCODE
