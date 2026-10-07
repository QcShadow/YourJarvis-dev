using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

internal static class DesktopProgram
{
    [STAThread]
    private static void Main(string[] args)
    {
        using (var instance = new Mutex(false, "Local\\JarvisLinkFull-" + InstanceKey.Value))
        {
            bool owns = false;
            try { owns = instance.WaitOne(0); }
            catch (AbandonedMutexException) { owns = true; }
            if (!owns)
            {
                try { using (var signal = EventWaitHandle.OpenExisting("Local\\JarvisLinkFullActivate-" + InstanceKey.Value)) signal.Set(); }
                catch (WaitHandleCannotBeOpenedException) { }
                return;
            }
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new JarvisWindow(Array.IndexOf(args, "--hidden") >= 0,
                    Array.IndexOf(args, "--debug") >= 0));
            }
            finally { instance.ReleaseMutex(); }
        }
    }
}

internal sealed class JarvisWindow : Form
{
    private string Server;
    private Process backend;
    private bool restarting;
    private const int Hotkey = 0x4A56;
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    private readonly WebView2 web = new WebView2();
    private readonly Label loading = new Label();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly ToolStripMenuItem showItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem pauseItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem updateItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem quitItem = new ToolStripMenuItem();
    private readonly EventWaitHandle activate = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\JarvisLinkFullActivate-" + InstanceKey.Value);
    private readonly HttpClient http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
    private bool exiting;
    private bool checkingUpdate;
    private bool english;
    private readonly bool startHidden;
    private readonly bool debug;

    [DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr hwnd, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hwnd, int id);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern IntPtr GetWindowDpiAwarenessContext(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);

    public JarvisWindow(bool hidden, bool enableDebug)
    {
        startHidden = hidden;
        debug = enableDebug;
        Text = "JARVIS Link";
        AutoScaleDimensions = new SizeF(96F, 96F);
        AutoScaleMode = AutoScaleMode.Dpi;
        Size = new Size(1280, 800);
        MinimumSize = new Size(900, 600);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(17, 19, 24);
        try { Icon = new Icon(Path.Combine(root, "src", "frontend", "src-tauri", "icons", "icon.ico")); }
        catch { Icon = SystemIcons.Application; }
        web.Dock = DockStyle.Fill;
        web.Visible = false;
        loading.Dock = DockStyle.Fill;
        loading.TextAlign = ContentAlignment.MiddleCenter;
        loading.ForeColor = Color.FromArgb(218, 224, 232);
        loading.Font = new Font("Microsoft YaHei UI", 12);
        loading.Text = "正在启动贾维斯…";
        Controls.Add(web);
        Controls.Add(loading);
        var menu = new ContextMenuStrip();
        menu.Items.AddRange(new ToolStripItem[] { showItem, pauseItem, updateItem, new ToolStripSeparator(), quitItem });
        showItem.Click += delegate { ShowAssistant(); };
        pauseItem.Click += async delegate { await PauseConversation(); };
        updateItem.Click += async delegate { await CheckForUpdates(true); };
        quitItem.Click += async delegate { await Quit(); };
        tray.Icon = Icon;
        tray.Text = "JARVIS Link";
        tray.ContextMenuStrip = menu;
        tray.Visible = true;
        tray.DoubleClick += delegate { ShowAssistant(); };
        SetLanguage(false);
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (!exiting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }
        };
        Shown += async delegate {
            // Size is expressed in physical pixels by the legacy compiler;
            // choose a usable logical workspace while respecting this monitor.
            var area = Screen.FromHandle(Handle).WorkingArea;
            var scale = GetDpiForWindow(Handle) / 96.0;
            Size = new Size((int)Math.Min(area.Width * 0.94, 1280 * scale),
                (int)Math.Min(area.Height * 0.92, 800 * scale));
            CenterToScreen();
            if (startHidden) Hide();
            await StartAssistant();
            await CheckForUpdates(false);
        };
        var activationThread = new Thread(delegate() {
            while (!exiting) {
                if (activate.WaitOne(1000) && !exiting && IsHandleCreated)
                    BeginInvoke((Action)ShowAssistant);
            }
        });
        activationThread.IsBackground = true;
        activationThread.Start();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        RegisterHotKey(Handle, Hotkey, 0x0002 | 0x0004 | 0x4000, 0x20);
    }
    protected override void OnHandleDestroyed(EventArgs e)
    {
        UnregisterHotKey(Handle, Hotkey);
        base.OnHandleDestroyed(e);
    }
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x0312 && m.WParam.ToInt32() == Hotkey) ShowAssistant();
        base.WndProc(ref m);
    }
    private void ShowAssistant()
    {
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
    }
    private void SetLanguage(bool useEnglish)
    {
        english = useEnglish;
        showItem.Text = english ? "Open JARVIS" : "打开贾维斯";
        pauseItem.Text = english ? "Pause listening" : "暂停语音接听";
        updateItem.Text = english ? "Check for updates" : "检查更新";
        quitItem.Text = english ? "Quit JARVIS" : "退出贾维斯";
    }
    private bool IsLocal(string address)
    {
        Uri uri;
        return Uri.TryCreate(address, UriKind.Absolute, out uri)
            && Server != null && uri.GetLeftPart(UriPartial.Authority) == Server;
    }
    private static void OpenLink(string address)
    {
        Uri uri;
        if (Uri.TryCreate(address, UriKind.Absolute, out uri) && (uri.Scheme == "http" || uri.Scheme == "https"))
            Process.Start(new ProcessStartInfo(address) { UseShellExecute = true });
    }
    private async Task StartAssistant()
    {
        try
        {
            await StartBackend();
            var runtime = Path.Combine(root, "runtimes", "webview2");
            if (Environment.OSVersion.Version.Build < 22000) {
                foreach (string sid in new string[] {"*S-1-15-2-2", "*S-1-15-2-1"}) {
                    var permissions = new ProcessStartInfo("icacls.exe", "\"" + runtime + "\" /grant \"" + sid + ":(OI)(CI)(RX)\"") {
                        UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
                    };
                    using (var process = Process.Start(permissions)) {
                        await Task.Run(() => process.WaitForExit(10000));
                        if (!process.HasExited || process.ExitCode != 0) throw new Exception("无法设置包内浏览器读取权限，请解压到自己的可写目录。");
                    }
                }
            }
            Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));
            var env = await CoreWebView2Environment.CreateAsync(Path.Combine(root, "runtimes", "webview2"),
                Path.Combine(root, "data", "desktop", "webview2"),
                new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required --disable-background-networking --disable-component-update"
                    + (debug ? " --remote-debugging-port=9248" : "")));
            await web.EnsureCoreWebView2Async(env);
            Log("DPI: " + GetDpiForWindow(Handle) + "; PerMonitorV2="
                + AreDpiAwarenessContextsEqual(GetWindowDpiAwarenessContext(Handle), new IntPtr(-4)));
            web.ZoomFactor = 1.0;
            Log("WebView2 ready: " + web.CoreWebView2.Environment.BrowserVersionString);
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "window.__JARVIS_DESKTOP__ = true; window.__JARVIS_LINK__ = true;"
                + "if(location.origin==='" + Server + "' && navigator.serviceWorker"
                + " && !sessionStorage.getItem('jarvis-fresh-"
                + File.GetLastWriteTimeUtc(Application.ExecutablePath).Ticks + "')) {"
                + "sessionStorage.setItem('jarvis-fresh-"
                + File.GetLastWriteTimeUtc(Application.ExecutablePath).Ticks + "','1');"
                + "navigator.serviceWorker.getRegistrations().then(async rs=>{"
                + "if(rs.length && navigator.serviceWorker.controller){"
                + "await Promise.all(rs.map(r=>r.unregister()));location.reload();}});}"
            );
            web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            web.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                if (!IsLocal(e.Uri)) { e.Cancel = true; OpenLink(e.Uri); }
            };
            web.CoreWebView2.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                Log("Navigation: " + (e.IsSuccess ? "ready" : e.WebErrorStatus.ToString()));
            };
            web.CoreWebView2.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true; OpenLink(e.Uri);
            };
            web.CoreWebView2.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) {
                if (IsLocal(e.Uri) && e.PermissionKind == CoreWebView2PermissionKind.Microphone)
                    e.State = CoreWebView2PermissionState.Allow;
            };
            web.CoreWebView2.WebMessageReceived += async delegate(object sender, CoreWebView2WebMessageReceivedEventArgs e) {
                if (!IsLocal(e.Source)) return;
                try {
                    var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "restart-backend") {
                        await RestartBackend(); return;
                    }
                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "quit") {
                        await Quit(); return;
                    }
                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "language")
                        SetLanguage(data.ContainsKey("language") && Convert.ToString(data["language"]) == "en-US");
                } catch { }
            };
            var snapshot = Path.Combine(root, "data", "desktop", "local-storage.json");
            if (File.Exists(snapshot)) {
                var saved = new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Serialize(File.ReadAllText(snapshot));
                await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                    "if(!localStorage.getItem('openjarvis-settings')){try{"
                    + "const s=JSON.parse(" + saved + ");for(const k in s)localStorage.setItem(k,s[k]);}catch(e){}}"
                );
            }
            web.CoreWebView2.Navigate(Server);
            web.Visible = true;
            loading.Visible = false;
            web.BringToFront();
        }
        catch (Exception error)
        {
            Log("Startup error: " + error.ToString());
            loading.Text = (english ? "JARVIS could not start.\n" : "贾维斯启动失败。\n") + error.Message
                + "\n" + Path.Combine(root, "logs", "gui-server.stderr.log");
        }
    }

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
            "\"" + helper + "\" --root \"" + root.TrimEnd('\\') + "\" --ready \"" + ready + "\"") {
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
            if (backend.HasExited) throw new Exception("后端启动失败，请查看 logs\\desktop.log。");
            try {
                var data = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(ready));
                if (data.ContainsKey("url")) { Server = Convert.ToString(data["url"]); return; }
            } catch (IOException) { } catch (ArgumentException) { }
            await Task.Delay(200);
        }
        throw new Exception("后端启动超时，请查看 logs\\desktop.log。");
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
            var saved = new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Serialize(File.ReadAllText(
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
        var value = new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.Deserialize<string>(result);
        Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));
        File.WriteAllText(Path.Combine(root, "data", "desktop", "local-storage.json"), value);
    }

    private void Log(string message)
    {
        try {
            Directory.CreateDirectory(Path.Combine(root, "logs"));
            File.AppendAllText(Path.Combine(root, "logs", "desktop.log"),
                DateTime.Now.ToString("s") + " " + message + Environment.NewLine);
        } catch { }
    }
    private async Task PauseConversation()
    {
        try { await http.PostAsync(Server + "/v1/voice/standby", new StringContent("{}", System.Text.Encoding.UTF8, "application/json")); }
        catch { }
        if (web.CoreWebView2 != null)
            await web.CoreWebView2.ExecuteScriptAsync("window.dispatchEvent(new Event('jarvis-pause-listening'));");
    }
    private async Task StopListening()
    {
        try { await http.PostAsync(Server + "/v1/voice/stop", new StringContent("{}", System.Text.Encoding.UTF8, "application/json")); }
        catch { }
    }
    private async Task CheckForUpdates(bool interactive)
    {
        if (checkingUpdate || exiting) return;
        checkingUpdate = true;
        updateItem.Enabled = false;
        try {
            JarvisUpdateInfo update = await JarvisUpdateChecker.CheckAsync(root);
            if (update.IsAvailable) {
                string title = english ? "JARVIS Link update available" : "JARVIS Link 有新版本";
                string message = (english ? "Installed: " : "当前版本：") + update.CurrentVersion
                    + "\n" + (english ? "Latest: " : "最新版本：") + update.LatestVersion;
                if (!String.IsNullOrWhiteSpace(update.Notes)) message += "\n\n" + update.Notes;
                if (interactive) {
                    var answer = MessageBox.Show(message + "\n\n"
                        + (english ? "Download and restart now?" : "现在下载并重启更新吗？"),
                        title, MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                    if (answer == DialogResult.Yes) await DownloadUpdate(update);
                } else {
                    tray.BalloonTipTitle = title;
                    tray.BalloonTipText = (english ? "Version " : "版本 ") + update.LatestVersion
                        + (english ? " is ready. Click to download." : " 已发布，点击前往下载。");
                    tray.BalloonTipClicked += async delegate { await DownloadUpdate(update); };
                    tray.ShowBalloonTip(10000);
                }
            } else if (interactive) {
                MessageBox.Show((english ? "You are using the latest version: " : "当前已是最新版本：")
                    + update.CurrentVersion, "JARVIS Link", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }
        catch (Exception error) {
            Log("Update check: " + error.Message);
            if (interactive) MessageBox.Show((english ? "Could not check for updates.\n" : "暂时无法检查更新。\n")
                + error.Message, "JARVIS Link", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { checkingUpdate = false; updateItem.Enabled = true; }
    }
    private async Task DownloadUpdate(JarvisUpdateInfo update)
    {
        updateItem.Enabled = false;
        try {
            tray.BalloonTipTitle = "JARVIS Link 更新";
            tray.BalloonTipText = "正在下载 " + update.LatestVersion + "…";
            var progress = new Progress<int>(value => tray.BalloonTipText = "正在下载 " + update.LatestVersion + "… " + value + "%");
            string path = await JarvisUpdateChecker.DownloadAsync(root, update, progress);
            var answer = MessageBox.Show("更新包已下载完成。现在重启 JARVIS Link 并自动应用更新吗？", "JARVIS Link 更新", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
            if (answer == DialogResult.Yes) {
                await SavePreferences(); await StopListening();
                JarvisUpdateChecker.LaunchAutomaticUpdate(path, root);
                exiting = true; tray.Visible = false; Close();
            } else {
                MessageBox.Show("稍后可从这里手动运行更新包：\n" + path, "JARVIS Link 更新", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        } catch (Exception error) {
            MessageBox.Show("更新下载失败：\n" + error.Message, "JARVIS Link", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { updateItem.Enabled = true; }
    }
    private async Task Quit()
    {
        await SavePreferences();
        await StopListening();
        await StopBackend();
        exiting = true;
        tray.Visible = false;
        Close();
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { exiting = true; tray.Dispose(); http.Dispose(); web.Dispose(); }
        base.Dispose(disposing);
    }
}

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
