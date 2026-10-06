[CmdletBinding()]
param([switch] $NoLaunch, [switch] $Voice)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $installer = Join-Path $PSScriptRoot 'JARVIS-Install.exe'
    if (-not (Test-Path -LiteralPath $installer)) { throw '安装包不完整：缺少 JARVIS-Install.exe。请重新下载并完整解压新版安装包。' }
    $arguments = @('--from-script')
    if ($NoLaunch) { $arguments += '--no-launch' }
    if ($Voice) { $arguments += '--voice' }
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -PassThru
    $process.WaitForExit()
    exit $process.ExitCode
} catch {
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'JARVIS 安装', 'OK', 'Error')
    exit 1
}
