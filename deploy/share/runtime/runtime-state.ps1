function Get-FreeJarvisPort {
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); return $listener.LocalEndpoint.Port }
    finally { $listener.Stop() }
}
function Get-OwnedJarvisProcess($state, [string] $executable) {
    if (-not $state -or $state.root -ne $script:JarvisRoot) { return $null }
    try {
        $owned = Get-Process -Id ([int]$state.pid) -ErrorAction Stop
        if ($owned.Path -ne $executable -or [string]$owned.StartTime.ToUniversalTime().Ticks -ne [string]$state.started) { return $null }
        return $owned
    } catch { return $null }
}
function Read-JarvisState([string] $name) {
    $file = Join-Path $script:JarvisRoot ('logs\' + $name + '.json')
    try { return ([IO.File]::ReadAllText($file) | ConvertFrom-Json) } catch { return $null }
}
function Write-JarvisState([string] $name, $process, [int] $port, [string] $identity = '') {
    $state = @{root=$script:JarvisRoot;pid=$process.Id;started=[string]$process.StartTime.ToUniversalTime().Ticks;port=$port;url="http://127.0.0.1:$port";instance=$identity}
    [IO.File]::WriteAllText((Join-Path $script:JarvisRoot ('logs\' + $name + '.json')), ($state | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
    return $state
}
function Test-JarvisEndpoint([string] $url, [string] $identity = '') {
    try {
        $uri = New-Object Uri($url)
        if ($uri.Host -ne '127.0.0.1' -or $uri.Scheme -ne 'http') { return $false }
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Proxy = $null; $request.Timeout = 2000; $request.ReadWriteTimeout = 2000
        $response = $request.GetResponse()
        try { return $response.StatusCode -eq 200 -and (-not $identity -or $response.Headers['X-Jarvis-Instance'] -eq $identity) }
        finally { $response.Close() }
    } catch { return $false }
}
function Stop-OwnedJarvisService([string] $name, [string] $executable) {
    $state = Read-JarvisState $name
    $owned = Get-OwnedJarvisProcess $state $executable
    if ($owned) {
        & taskkill.exe /PID $owned.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Get-OwnedJarvisProcess $state $executable)) { throw '无法退出本安装目录的后台，请退出贾维斯后重试。' }
    }
    $file = Join-Path $script:JarvisRoot ('logs\' + $name + '.json')
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
}
