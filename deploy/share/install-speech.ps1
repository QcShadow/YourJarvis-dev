[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Choices)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$Root=[IO.Path]::GetFullPath($Root)
$selected=@($Choices.Split(',') | Select-Object -Unique)
$mapping=@{'asr-zh'=@('runtime-voice','runtime-native','asr-zh');'asr-en'=@('runtime-voice','runtime-native','speech-en');'tts'=@('runtime-voice','runtime-native','tts-kokoro');'piper'=@('runtime-piper');'clone'=@('runtime-qwen','model-qwen')}
$lock=$null
try {
    if(@($selected | Where-Object { -not $mapping.ContainsKey($_) }).Count -or -not $selected.Count) {throw '语音选择无效。'}
    $lock=[IO.File]::Open((Join-Path $Root '.installer.lock'),'OpenOrCreate','ReadWrite','None')
    $required=if($selected -contains 'clone'){8GB}else{4GB}
    if((New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Root))).AvailableFreeSpace -lt $required){throw '磁盘空间不足；普通语音需要 4 GB，录音创建音色需要 8 GB。'}
    & (Join-Path $Root 'stop-gui.ps1') | Out-Null
    $packages=@($selected | ForEach-Object {$mapping[$_]} | Select-Object -Unique)
    foreach($package in $packages) {
        [Console]::WriteLine("正在准备资源：$package")
        & (Join-Path $Root 'JARVIS-Resources.exe') $Root (Join-Path $Root 'resources.json') $package 'gitee'
        if($LASTEXITCODE -ne 0){throw "资源 $package 未完成。"}
    }
    & (Join-Path $Root 'src\.venv\Scripts\python.exe') (Join-Path $Root 'scripts\configure_speech.py') --root $Root --choices $Choices
    if($LASTEXITCODE -ne 0){throw '语音配置检查未通过。'}
    [Console]::WriteLine('语音资源已安装并检查通过。')
    exit 0
} catch {[Console]::WriteLine($_.Exception.Message);exit 1}
finally {if($lock){$lock.Dispose()}}
