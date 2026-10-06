[CmdletBinding()]
param([switch] $NoModelDownload)
& (Join-Path $PSScriptRoot 'install-jarvis.ps1')
exit $LASTEXITCODE
