"""Derive Link's native shell from the full developer desktop shell."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
text = (root / "launcher/Desktop.cs").read_text(encoding="utf-8-sig")
text = text.replace('"Local\\\\JarvisDesktop"', '"Local\\\\JarvisLinkFull-" + InstanceKey.Value')
text = text.replace('"Local\\\\JarvisDesktopActivate"', '"Local\\\\JarvisLinkFullActivate-" + InstanceKey.Value')
text = text.replace('    private const string Server = "http://127.0.0.1:8000";',
                    '    private string Server;\n    private Process backend;\n    private bool restarting;')
text = text.replace('Text = "JARVIS";', 'Text = "JARVIS Link";')
text = text.replace('tray.Text = "JARVIS";', 'tray.Text = "JARVIS Link";')
text = text.replace('private static bool IsLocal(string address)', 'private bool IsLocal(string address)')
text = text.replace('&& uri.Scheme == "http" && uri.Host == "127.0.0.1" && uri.Port == 8000;',
                    '&& Server != null && uri.GetLeftPart(UriPartial.Authority) == Server;')
start = text.index('            if (!File.Exists(Path.Combine(root, "config.toml")))')
end = text.index('            Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));', start)
text = text[:start] + '            await StartBackend();\n' + text[end:]
text = text.replace('CoreWebView2Environment.CreateAsync(null,',
                    'CoreWebView2Environment.CreateAsync(Path.Combine(root, "runtimes", "webview2"),')
text = text.replace('            await StartBackend();', '''            await StartBackend();
            var runtime = Path.Combine(root, "runtimes", "webview2");
            if (Environment.OSVersion.Version.Build < 22000) {
                foreach (string sid in new string[] {"*S-1-15-2-2", "*S-1-15-2-1"}) {
                    var permissions = new ProcessStartInfo("icacls.exe", "\\\"" + runtime + "\\\" /grant \\\"" + sid + ":(OI)(CI)(RX)\\\"") {
                        UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
                    };
                    using (var process = Process.Start(permissions)) {
                        await Task.Run(() => process.WaitForExit(10000));
                        if (!process.HasExited || process.ExitCode != 0) throw new Exception("无法设置包内浏览器读取权限，请解压到自己的可写目录。");
                    }
                }
            }''')
text = text.replace('"--autoplay-policy=no-user-gesture-required"',
                    '"--autoplay-policy=no-user-gesture-required --disable-background-networking --disable-component-update"')
text = text.replace('--remote-debugging-port=9223', '--remote-debugging-port=9248')
text = text.replace('"window.__JARVIS_DESKTOP__ = true;"',
                    '"window.__JARVIS_DESKTOP__ = true; window.__JARVIS_LINK__ = true;"')
text = text.replace('            web.CoreWebView2.Navigate(Server);', '''            var snapshot = Path.Combine(root, "data", "desktop", "local-storage.json");
            if (File.Exists(snapshot)) {
                var saved = new JavaScriptSerializer().Serialize(File.ReadAllText(snapshot));
                await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                    "if(!localStorage.getItem('openjarvis-settings')){try{"
                    + "const s=JSON.parse(" + saved + ");for(const k in s)localStorage.setItem(k,s[k]);}catch(e){}}"
                );
            }
            web.CoreWebView2.Navigate(Server);''', 1)
text = text.replace('web.CoreWebView2.WebMessageReceived += delegate(',
                    'web.CoreWebView2.WebMessageReceived += async delegate(')
needle = '                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "language")'
text = text.replace(needle, '''                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "restart-backend") {
                        await RestartBackend(); return;
                    }
                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "quit") {
                        await Quit(); return;
                    }
''' + needle)
text = text.replace('        await StopListening();\n        exiting = true;',
                    '        await SavePreferences();\n        await StopListening();\n        await StopBackend();\n        exiting = true;')
insert = '''
    private async Task StartBackend()
    {
        Directory.CreateDirectory(Path.Combine(root, "logs"));
        Directory.CreateDirectory(Path.Combine(root, "data"));
        var ready = Path.Combine(root, "data", "client-ready.json");
        File.WriteAllText(ready, "{}");
        var python = Path.Combine(root, "runtimes", "python", "python.exe");
        var helper = Path.Combine(root, "scripts", "portable_backend.py");
        if (!File.Exists(python) || !File.Exists(helper))
            throw new Exception("完整运行时缺失，请重新解压软件包。");
        var start = new ProcessStartInfo(python,
            "\\\"" + helper + "\\\" --root \\\"" + root.TrimEnd('\\\\') + "\\\" --ready \\\"" + ready + "\\\"") {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        start.EnvironmentVariables["PYTHONUTF8"] = "1";
        start.EnvironmentVariables.Remove("PYTHONHOME");
        start.EnvironmentVariables.Remove("PYTHONPATH");
        start.EnvironmentVariables.Remove("VIRTUAL_ENV");
        backend = new Process { StartInfo = start };
        backend.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Log(e.Data); };
        backend.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Log(e.Data); };
        backend.Start(); backend.BeginOutputReadLine(); backend.BeginErrorReadLine();
        var serializer = new JavaScriptSerializer();
        for (int attempt = 0; attempt < 600; attempt++) {
            if (backend.HasExited) throw new Exception("后端启动失败，请查看 logs\\\\desktop.log。");
            try {
                var data = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(ready));
                if (data.ContainsKey("url")) { Server = Convert.ToString(data["url"]); return; }
            } catch (IOException) { } catch (ArgumentException) { }
            await Task.Delay(200);
        }
        throw new Exception("后端启动超时，请查看 logs\\\\desktop.log。");
    }
    private async Task StopBackend()
    {
        if (backend == null) return;
        try {
            if (!backend.HasExited) {
                var stop = new ProcessStartInfo("taskkill.exe", "/PID " + backend.Id + " /T /F") {
                    UseShellExecute = false, CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                using (var process = Process.Start(stop)) await Task.Run(() => process.WaitForExit(10000));
            }
        } catch { }
        backend.Dispose(); backend = null;
    }
    private async Task RestartBackend()
    {
        if (restarting || exiting) return;
        restarting = true;
        web.Visible = false; loading.Visible = true; loading.BringToFront();
        loading.Text = "正在应用模型配置…";
        try {
            await SavePreferences(); await StopListening(); await StopBackend(); await StartBackend();
            var saved = new JavaScriptSerializer().Serialize(File.ReadAllText(
                Path.Combine(root, "data", "desktop", "local-storage.json")));
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "if(!localStorage.getItem('openjarvis-settings')){try{"
                + "const s=JSON.parse(" + saved + ");for(const k in s)localStorage.setItem(k,s[k]);}catch(e){}}"
            );
            web.CoreWebView2.Navigate(Server);
            web.Visible = true; loading.Visible = false; web.BringToFront();
        } catch (Exception error) { loading.Text = error.Message; Log(error.ToString()); }
        restarting = false;
    }
    private async Task SavePreferences()
    {
        if (web.CoreWebView2 == null) return;
        var result = await web.CoreWebView2.ExecuteScriptAsync(
            "JSON.stringify(Object.fromEntries(Object.keys(localStorage).map(k=>[k,localStorage.getItem(k)])))");
        var value = new JavaScriptSerializer().Deserialize<string>(result);
        Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));
        File.WriteAllText(Path.Combine(root, "data", "desktop", "local-storage.json"), value);
    }
'''
text = text.replace('    private void Log(string message)', insert + '\n    private void Log(string message)')
text = text.replace('new JavaScriptSerializer().Serialize(',
                    'new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Serialize(')
text = text.replace('new JavaScriptSerializer().Deserialize<string>(',
                    'new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Deserialize<string>(')
text += '''
internal static class InstanceKey
{
    public static readonly string Value = Create();
    private static string Create()
    {
        using (var hash = System.Security.Cryptography.SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(
                AppDomain.CurrentDomain.BaseDirectory.ToLowerInvariant()))).Replace("-", "").Substring(0, 16);
    }
}
'''
(root / "launcher/LinkDesktop.cs").write_text(text, encoding="utf-8-sig")
