[CmdletBinding()]
param([Parameter(Mandatory=$true)][string] $Root)
$ErrorActionPreference = 'Stop'
# GUI parents may inherit a module path belonging to a different PowerShell.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility')
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management')
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security')
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$Root = [IO.Path]::GetFullPath($Root)

function Step([int] $number, [string] $message) { [Console]::WriteLine("JARVIS_STEP|$number|$message") }
function Run([string] $file, [string[]] $arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $file @arguments 2>&1 | ForEach-Object { [Console]::WriteLine([string]$_) }; $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "安装命令失败（退出代码 $code）。请检查网络和下方日志后点击重试。" }
}
function Bridge([string] $action) {
    $request | ConvertTo-Json -Compress | & $python (Join-Path $Root 'scripts\configure_portable.py') --root $Root --action $action
    if ($LASTEXITCODE -ne 0) { throw '模型连接或配置检查未通过，请按日志提示修改后重试。' }
}
function Download([string] $url, [string] $target) {
    $partial = $target + '.part'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            [Console]::WriteLine("正在下载运行组件（第 $attempt 次尝试）…")
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $partial -TimeoutSec 900
            Move-Item -LiteralPath $partial -Destination $target -Force
            return
        } catch {
            if ($attempt -eq 3) { throw '运行组件下载失败。请检查网络或代理后重试；已完成的安装步骤会保留。' }
            Start-Sleep -Seconds 2
        }
    }
}
function Test-WebView {
    try {
        Add-Type -Path (Join-Path $Root 'Microsoft.Web.WebView2.Core.dll')
        return [bool][Microsoft.Web.WebView2.Core.CoreWebView2Environment]::GetAvailableBrowserVersionString()
    } catch { return $false }
}
$lock = $null
try {
    Step 1 '检查安装包、目录权限和磁盘空间'
    if (-not [Environment]::Is64BitOperatingSystem) { throw '此安装包需要 64 位 Windows 10/11。' }
    $lock = [IO.File]::Open((Join-Path $Root '.installer.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    foreach ($file in @('env.ps1','tools\uv\uv.exe','src\pyproject.toml','src\uv.lock','scripts\configure_portable.py','JARVIS.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $file))) { throw "安装包缺少 $file。请完整解压新版 ZIP 后重试。" }
    }
    if (Test-Path -LiteralPath (Join-Path $Root 'package-manifest.json')) {
        $manifest = Get-Content -LiteralPath (Join-Path $Root 'package-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in $manifest.files) {
            $file = [IO.Path]::GetFullPath((Join-Path $Root $item.path))
            if (-not $file.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '安装包清单路径无效。' }
            if (-not (Test-Path -LiteralPath $file)) { throw "安装文件缺失：$($item.path)。请完整解压安装包。" }
            $stream = [IO.File]::OpenRead($file)
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $stream.Dispose(); $sha.Dispose() }
            if ($hash -ne $item.sha256) { throw "文件校验失败：$($item.path)。请重新下载并解压安装包。" }
        }
    }
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Root))
    $requiredGb = if ($request.voice -eq 'text' -and -not $request.preserve) { 4 } else { 10 }
    if ($drive.AvailableFreeSpace -lt ($requiredGb * 1GB)) { throw "安装磁盘至少需要 $requiredGb GB 可用空间，请更换目录或清理空间。" }
    . (Join-Path $Root 'env.ps1')
    $env:HF_HUB_OFFLINE = '0'
    $env:UV_HTTP_TIMEOUT = '180'
    $env:UV_HTTP_RETRIES = '3'
    $env:UV_LINK_MODE = 'copy'
    $python = Join-Path $Root 'src\.venv\Scripts\python.exe'
    Step 2 '安装独立 Python 和应用依赖（首次下载可能需要几分钟）'
    Run $script:JarvisUv @('python','install','3.12','--no-bin','--no-registry')
    $managed = Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory -Filter 'cpython-3.12*' | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe') } | Select-Object -First 1
    if (-not $managed) { throw 'Python 下载未完成，请检查网络后重试。' }
    $sync = @('sync','--frozen','--project',$script:JarvisSource,'--python',(Join-Path $managed.FullName 'python.exe'),'--no-dev','--extra','server','--extra','desktop')
    if ($request.voice -ne 'text' -and -not $request.preserve) { $sync += @('--extra','voice') }
    Run $script:JarvisUv $sync
    if ($request.preserve) {
        $existing = & $python (Join-Path $Root 'scripts\configure_portable.py') --root $Root --action existing
        if ($LASTEXITCODE -ne 0) { throw '无法读取现有配置，请取消保留配置并重新选择方案。' }
        $request = ($existing -join "`n") | ConvertFrom-Json
    }
    Bridge 'validate'
    Step 3 '检查桌面窗口组件 WebView2'
    if (-not (Test-WebView)) {
        $webview = Join-Path $env:TEMP 'MicrosoftEdgeWebview2Setup.exe'
        Download 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' $webview
        $signature = Get-AuthenticodeSignature -LiteralPath $webview
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'WebView2 安装器签名校验失败，请检查网络后重试。' }
        Run $webview @('/silent','/install')
        if (-not (Test-WebView)) { throw 'WebView2 未安装成功，请重启 Windows 后点击重试。' }
    }
    Step 4 '准备模型并测试连接'
    if ($request.profile -notin @('api','remote-host')) {
        $tags = $null
        try { $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 } catch { }
        if (-not $tags) {
            if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
                $installed = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
                if (Test-Path -LiteralPath $installed) { $script:JarvisOllama = $installed }
            }
            if (-not (Test-Path -LiteralPath $script:JarvisOllama)) {
                $setup = Join-Path $env:TEMP 'OllamaSetup.exe'
                Download 'https://ollama.com/download/OllamaSetup.exe' $setup
                $signature = Get-AuthenticodeSignature -LiteralPath $setup
                if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Ollama') { throw 'Ollama 安装器签名校验失败，请检查网络后重试。' }
                Run $setup @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR=' + (Join-Path $Root 'runtimes\ollama')))
                $script:JarvisOllama = Join-Path $Root 'runtimes\ollama\ollama.exe'
                if (-not (Test-Path -LiteralPath $script:JarvisOllama)) { throw 'Ollama 安装未完成，请重试。' }
            }
            & (Join-Path $Root 'start-ollama.ps1')
            $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
        }
        if ($request.model -notin @($tags.models | ForEach-Object { $_.name })) {
            [Console]::WriteLine("正在下载 $($request.model)，请耐心等待；重试会复用已下载内容。")
            $body = @{ name = $request.model; stream = $false } | ConvertTo-Json
            $pull = Invoke-RestMethod 'http://127.0.0.1:11434/api/pull' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 7200
            if ($pull.error) { throw '模型下载失败，请检查模型名称和网络后重试。' }
        }
    }
    Bridge 'check'
    Step 5 '准备所选语音（文字模式自动跳过下载）'
    if ($request.voice -ne 'text') {
        if ($request.preserve) { Run $script:JarvisUv ($sync + @('--extra','voice')) }
        Run $script:JarvisUv @('pip','install','--python',$python,'misaki[zh]','sherpa-onnx-core==1.13.8')
        $voiceArgs = @((Join-Path $Root 'scripts\download_speech_assets.py'),'--root',$Root)
        if ($request.voice -eq 'en') { $voiceArgs += '--english' }
        Run $python $voiceArgs
        if ($request.voice -eq 'en') { Run $script:JarvisUv @('pip','install','--python',$python,'https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl') }
        Run $python @('-c','import sherpa_onnx, kokoro, misaki.zh; print("Voice runtime ready")')
    }
    Step 6 '保存配置并完成应用自检'
    Bridge 'write'
    Run $python @('-m','openjarvis.cli','setup','check')
    [IO.File]::WriteAllText((Join-Path $Root 'install-complete.json'), (@{ version = '0.1.2'; completed = (Get-Date -Format o) } | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Step 7 '安装完成，现在可以启动 JARVIS'
    exit 0
} catch {
    [Console]::WriteLine('JARVIS_ERROR|' + $_.Exception.Message)
    exit 1
} finally { if ($lock) { $lock.Dispose() } }





