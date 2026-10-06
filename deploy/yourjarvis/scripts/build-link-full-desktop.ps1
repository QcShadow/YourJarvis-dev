[CmdletBinding()]
param(
    [string] $OutputDirectory = (Join-Path $PSScriptRoot 'dist\link-full-desktop'),
    [ValidatePattern('^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$')]
    [string] $Version = '1.0.0',
    [string] $UpdateManifestUrl = 'https://github.com/QcShadow/YourJarvis-link/releases/latest/download/update.json',
    [string] $MirrorUpdateManifestUrl = 'https://gitee.com/QcShadow/your-jarvis-link/raw/main/update.json'
)
$ErrorActionPreference = 'Stop'
$sdk = Join-Path $PSScriptRoot 'runtimes\webview2-sdk\1.0.4258.31'
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$core = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.WinForms.dll'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$OutputDirectory\JARVIS-Link.exe" `
    "/win32manifest:$PSScriptRoot\launcher\Desktop.manifest" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.Net.Http.dll /reference:System.Web.Extensions.dll `
    "/reference:$core" "/reference:$forms" `
    (Join-Path $PSScriptRoot 'launcher\LinkDesktop.cs') `
    (Join-Path $PSScriptRoot 'launcher\UpdateChecker.cs')
if ($LASTEXITCODE -ne 0) { throw 'Link desktop compilation failed' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launcher\Desktop.config') -Destination (Join-Path $OutputDirectory 'JARVIS-Link.exe.config') -Force
Copy-Item -LiteralPath $core, $forms -Destination $OutputDirectory -Force
Copy-Item -LiteralPath (Join-Path $sdk 'runtimes\win-x64\native\WebView2Loader.dll') -Destination $OutputDirectory -Force
@{
    version = $Version
    manifestUrls = @($UpdateManifestUrl, $MirrorUpdateManifestUrl) | Where-Object { $_ }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'app-version.json') -Encoding UTF8
Write-Host "JARVIS Link $Version`: $OutputDirectory\JARVIS-Link.exe"
