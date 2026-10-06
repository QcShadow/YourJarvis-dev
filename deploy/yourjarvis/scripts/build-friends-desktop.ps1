[CmdletBinding()]
param(
    [string] $OutputDirectory = (Join-Path $PSScriptRoot 'dist\friends-desktop'),
    [ValidatePattern('^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$')]
    [string] $Version = '1.0.0',
    [string] $UpdateManifestUrl = '',
    [string] $MirrorUpdateManifestUrl = ''
)
$ErrorActionPreference = 'Stop'
$desktopOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $desktopOutput -Force | Out-Null
$sdk = Join-Path $PSScriptRoot 'runtimes\webview2-sdk\1.0.4258.31'
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$core = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.WinForms.dll'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$desktopOutput\JARVIS-Link.exe" "/win32manifest:$PSScriptRoot\launcher\Desktop.manifest" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Net.Http.dll /reference:System.Web.Extensions.dll "/reference:$core" "/reference:$forms" (Join-Path $PSScriptRoot 'launcher\FriendsDesktop.cs') (Join-Path $PSScriptRoot 'launcher\UpdateChecker.cs')
if ($LASTEXITCODE -ne 0) { throw 'Friends desktop compilation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launcher\Desktop.config') -Destination (Join-Path $desktopOutput 'JARVIS-Link.exe.config') -Force
Copy-Item -LiteralPath $core,$forms -Destination $desktopOutput -Force
Copy-Item -LiteralPath (Join-Path $sdk 'runtimes\win-x64\native\WebView2Loader.dll') -Destination $desktopOutput -Force
@{
    version = $Version
    manifestUrls = @($UpdateManifestUrl, $MirrorUpdateManifestUrl) | Where-Object { $_ }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $desktopOutput 'app-version.json') -Encoding UTF8
Write-Host "JARVIS Link: $desktopOutput\JARVIS-Link.exe"
