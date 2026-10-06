[CmdletBinding()]
param([Parameter(Mandatory=$true)][string] $Root)
$ErrorActionPreference = 'Stop'
foreach ($module in @('Utility','Management','Security')) { Import-Module (Join-Path $PSHOME "Modules\Microsoft.PowerShell.$module") }
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$Root = [IO.Path]::GetFullPath($Root)
$channel = if ($request.channel -eq 'github') { 'github' } else { 'gitee' }
function Step([int] $number, [string] $message) { [Console]::WriteLine("JARVIS_STEP|$number|$message") }
function Run([string] $file, [string[]] $arguments) {
    $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $file @arguments 2>&1 | ForEach-Object { [Console]::WriteLine([string]$_) }; $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "安装命令失败（退出代码 $code）。请按日志提示修改后重试，下载进度会保留。" }
}
function Resource([string] $name) { Run (Join-Path $Root 'JARVIS-Resources.exe') @($Root,(Join-Path $Root 'resources.json'),$name,$channel) }
function Bridge([string] $action) {
    $request | ConvertTo-Json -Compress | & $python (Join-Path $Root 'scripts\configure_portable.py') --root $Root --action $action
    if ($LASTEXITCODE -ne 0) { throw '模型连接或配置检查未通过，请按日志提示修改后重试。' }
}
function Test-WebView {
    try { Add-Type -Path (Join-Path $Root 'Microsoft.Web.WebView2.Core.dll'); return [bool][Microsoft.Web.WebView2.Core.CoreWebView2Environment]::GetAvailableBrowserVersionString() } catch { return $false }
}
$lock = $null
try {
    Step 1 '检查安装包、目录权限和磁盘空间'
    if (-not [Environment]::Is64BitOperatingSystem) { throw '此安装包需要 64 位 Windows 10/11。' }
    $lock = [IO.File]::Open((Join-Path $Root '.installer.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    foreach ($file in @('env.ps1','resources.json','JARVIS-Resources.exe','src\pyproject.toml','scripts\configure_portable.py','JARVIS.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $file))) { throw "安装包缺少 $file。请重新运行新版 JARVIS-Setup.exe。" }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'package-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $manifest.files) {
        $file = [IO.Path]::GetFullPath((Join-Path $Root $item.path))
        if (-not $file.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '安装包清单路径无效。' }
        if (-not (Test-Path -LiteralPath $file)) { throw "安装文件缺失：$($item.path)。请重新运行新版安装 EXE。" }
        $stream = [IO.File]::OpenRead($file); $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() } finally { $stream.Dispose(); $sha.Dispose() }
        if ($hash -ne $item.sha256) { throw "文件校验失败：$($item.path)。请重新下载新版安装 EXE。" }
    }
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Root))
    $requiredGb = if ($request.voice -eq 'text' -and -not $request.preserve) { 4 } else { 10 }
    if ($drive.AvailableFreeSpace -lt ($requiredGb * 1GB)) { throw "安装磁盘至少需要 $requiredGb GB 可用空间。" }
    . (Join-Path $Root 'env.ps1')
    # A closed desktop window may have left its backend running. Stop only
    # the process recorded by this installation, after checking its path.
    $pidFile = Join-Path $Root 'logs\gui-server.pid'
    if (Test-Path -LiteralPath $pidFile) {
        $ownedPid = 0
        if ([int]::TryParse(([IO.File]::ReadAllText($pidFile).Trim()), [ref]$ownedPid)) {
            $owned = Get-Process -Id $ownedPid -ErrorAction SilentlyContinue
            if ($owned -and $owned.Path -in @((Join-Path $Root 'src\.venv\Scripts\python.exe'),(Join-Path $Root 'tools\uv\uv.exe'))) {
                Run 'taskkill.exe' @('/PID',[string]$ownedPid,'/T','/F')
            }
        }
        Remove-Item -LiteralPath $pidFile -Force
    }
    & (Join-Path $Root 'stop-gui.ps1') | Out-Null
    $completion = Join-Path $Root 'install-complete.json'
    if (Test-Path -LiteralPath $completion) { Remove-Item -LiteralPath $completion -Force }
    $python = Join-Path $Root 'src\.venv\Scripts\python.exe'
    Step 2 '从发布地址准备 Python 和完整运行环境（Gitee 优先，失败自动切换）'
    Resource 'python'
    Resource 'runtime-text'
    Resource 'runtime-native'
    Run $python @('-c','import sys,fastapi,uvicorn; import openjarvis.server.app; from pathlib import Path; assert Path(sys._base_executable).is_relative_to(Path(sys.prefix).parents[1]); import openjarvis_rust; print(sys.executable)')
    if ($request.preserve) {
        $existing = & $python (Join-Path $Root 'scripts\configure_portable.py') --root $Root --action existing
        if ($LASTEXITCODE -ne 0) { throw '无法读取现有配置，请取消保留配置并重新选择方案。' }
        $request = ($existing -join "`n") | ConvertFrom-Json
    }
    Bridge 'validate'
    Step 3 '检查桌面窗口组件 WebView2'
    if (-not (Test-WebView)) {
        Resource 'webview2'
        $webview = Join-Path $Root 'cache\installers\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
        $signature = Get-AuthenticodeSignature -LiteralPath $webview
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'WebView2 安装器签名校验失败。' }
        Run $webview @('/silent','/install')
        if (-not (Test-WebView)) { throw 'WebView2 未安装成功，请重启 Windows 后点击重试。' }
    }
    Step 4 '从发布地址准备模型并测试连接'
    if ($request.profile -notin @('api','remote-host')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root 'runtimes\ollama\ollama.exe'))) { Resource 'ollama-cpu' }
        $script:JarvisOllama = Join-Path $Root 'runtimes\ollama\ollama.exe'
        if ($request.model -eq 'qwen2.5:0.5b') { Resource 'llm-lite' }
        & (Join-Path $Root 'start-ollama.ps1')
        $tags = Invoke-RestMethod ($env:OLLAMA_HOST + '/api/tags') -TimeoutSec 5
        if ($request.model -notin @($tags.models | ForEach-Object { $_.name })) {
            [Console]::WriteLine('默认模型已从发布资源准备；自定义模型仍使用上游下载。')
            $body = @{ name = $request.model; stream = $false } | ConvertTo-Json
            $pull = Invoke-RestMethod ($env:OLLAMA_HOST + '/api/pull') -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 7200
            if ($pull.error) { throw '模型下载失败。请检查模型名称和网络后重试。' }
        }
    }
    Bridge 'check'
    Step 5 '从发布地址准备所选语音并实际测试'
    if ($request.voice -ne 'text') {
        Resource 'runtime-voice'
        Resource 'runtime-native'
        Resource 'speech-zh'
        if ($request.voice -eq 'en') { Resource 'speech-en' }
        Run $python @((Join-Path $Root 'scripts\verify_voice.py'),'--root',$Root,'--voice',$request.voice)
    }
    Step 6 '保存配置并测试真实后端启动'
    Bridge 'write'
    Run $python @('-m','openjarvis.cli','setup','check')
    Run $python @((Join-Path $Root 'scripts\smoke_installed.py'),$Root)
    [IO.File]::WriteAllText((Join-Path $Root 'install-complete.json'), (@{ version = '0.1.4'; completed = (Get-Date -Format o) } | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Step 7 '安装完成，后端与模型已通过实际启动测试'
    exit 0
} catch { [Console]::WriteLine('JARVIS_ERROR|' + $_.Exception.Message); exit 1 }
finally { if ($lock) { $lock.Dispose() } }
