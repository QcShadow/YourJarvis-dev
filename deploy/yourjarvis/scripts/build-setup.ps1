[CmdletBinding()]
param([Parameter(Mandatory=$true)][string] $Package,[Parameter(Mandatory=$true)][string] $Output)
$ErrorActionPreference='Stop'
$launcher=Join-Path $PSScriptRoot '..\launcher'
$compiler='C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ `
    "/out:$Output" "/resource:$Package,package.zip" `
    "/win32manifest:$launcher\Desktop.manifest" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    (Join-Path $launcher 'SetupBootstrap.cs')
if($LASTEXITCODE -ne 0) {throw 'Setup EXE compilation failed'}
