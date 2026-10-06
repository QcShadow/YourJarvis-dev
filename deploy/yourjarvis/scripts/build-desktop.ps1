[CmdletBinding()]
param(
    [string] $WorkspaceRoot = ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\..'))),
    [string] $OutputDirectory = $PSScriptRoot,
    [ValidatePattern('^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$')]
    [string] $Version = '1.0.0',
    [string] $UpdateManifestUrl = 'https://github.com/QcShadow/YourJarvis-link/releases/latest/download/update-github.json',
    [string] $MirrorUpdateManifestUrl = 'https://gitee.com/QcShadow/your-jarvis-link/raw/main/update.json'
)
$ErrorActionPreference = 'Stop'
$jarvisRoot = $WorkspaceRoot
$launcher = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\launcher'))
$desktopOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $desktopOutput -Force | Out-Null
$sdk = Join-Path $jarvisRoot 'runtimes\webview2-sdk\1.0.4258.31'
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$core = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.WinForms.dll'
foreach ($required in @($compiler, $core, $forms)) {
    if (!(Test-Path -LiteralPath $required)) { throw "Missing desktop dependency: $required" }
}
& $compiler /nologo /target:winexe /platform:x64 /optimize+ `
    "/out:$desktopOutput\JARVIS-Desktop.exe" `
    "/win32manifest:$launcher\Desktop.manifest" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.Net.Http.dll /reference:System.Web.Extensions.dll `
    "/reference:$core" "/reference:$forms" `
    (Join-Path $launcher 'Desktop.cs') `
    (Join-Path $launcher 'UpdateChecker.cs')
if ($LASTEXITCODE -ne 0) { throw 'Desktop compilation failed' }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ `
    "/out:$desktopOutput\JARVIS-Install.exe" `
    "/win32manifest:$launcher\Desktop.manifest" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.Web.Extensions.dll `
    (Join-Path $launcher 'Installer.cs')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
& $compiler /nologo /target:exe /platform:x64 /optimize+ `
    "/out:$desktopOutput\JARVIS-Resources.exe" `
    /reference:System.Net.Http.dll /reference:System.Web.Extensions.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    (Join-Path $launcher 'ResourceFetch.cs')
if ($LASTEXITCODE -ne 0) { throw 'Resource downloader compilation failed' }
Copy-Item -LiteralPath (Join-Path $launcher 'Desktop.config') -Destination (Join-Path $desktopOutput 'JARVIS-Install.exe.config') -Force
Copy-Item -LiteralPath (Join-Path $desktopOutput 'JARVIS-Desktop.exe') -Destination (Join-Path $desktopOutput 'JARVIS.exe') -Force
Copy-Item -LiteralPath (Join-Path $launcher 'Desktop.config') -Destination (Join-Path $desktopOutput 'JARVIS.exe.config') -Force
Copy-Item -LiteralPath (Join-Path $launcher 'Desktop.config') -Destination (Join-Path $desktopOutput 'JARVIS-Desktop.exe.config') -Force
Copy-Item -LiteralPath $core, $forms -Destination $desktopOutput -Force
Copy-Item -LiteralPath (Join-Path $sdk 'runtimes\win-x64\native\WebView2Loader.dll') -Destination $desktopOutput -Force
@{
    version = $Version
    manifestUrls = @($MirrorUpdateManifestUrl, $UpdateManifestUrl) | Where-Object { $_ }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $desktopOutput 'app-version.json') -Encoding UTF8
Write-Host "Desktop app: $desktopOutput\JARVIS.exe (also JARVIS-Desktop.exe)"
