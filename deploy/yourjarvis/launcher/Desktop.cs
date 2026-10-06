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
        using (var instance = new Mutex(false, "Local\\JarvisDesktop"))
        {
            bool owns = false;
            try { owns = instance.WaitOne(0); }
            catch (AbandonedMutexException) { owns = true; }
            if (!owns)
            {
                try { using (var signal = EventWaitHandle.OpenExisting("Local\\JarvisDesktopActivate")) signal.Set(); }
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
    private const string Server = "http://127.0.0.1:8000";
    private const int Hotkey = 0x4A56;
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    private readonly WebView2 web = new WebView2();
    private readonly Label loading = new Label();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly ToolStripMenuItem showItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem pauseItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem updateItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem quitItem = new ToolStripMenuItem();
    private readonly EventWaitHandle activate = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\JarvisDesktopActivate");
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
        Text = "JARVIS";
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
        tray.Text = "JARVIS";
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
    private static bool IsLocal(string address)
    {
        Uri uri;
        return Uri.TryCreate(address, UriKind.Absolute, out uri)
            && uri.Scheme == "http" && uri.Host == "127.0.0.1" && uri.Port == 8000;
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
            if (!File.Exists(Path.Combine(root, "config.toml")))
            {
                var setup = new ProcessStartInfo(Path.Combine(root, "setup-jarvis.cmd")) {
                    WorkingDirectory = root, UseShellExecute = true
                };
                using (var configuration = Process.Start(setup))
                    await Task.Run((Action)configuration.WaitForExit);
                if (!File.Exists(Path.Combine(root, "config.toml")))
                    throw new Exception("请先运行 setup-jarvis.cmd 完成模型配置。");
            }
            var start = new ProcessStartInfo("powershell.exe",
                "-NoLogo -NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(root, "start-gui.ps1") + "\" -NoBrowser") {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            using (var process = Process.Start(start))
            {
                await Task.Run((Action)process.WaitForExit);
                if (process.ExitCode != 0) throw new Exception(
                    "Backend startup failed. See logs\\gui-server.stderr.log.");
            }
            Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));
            var env = await CoreWebView2Environment.CreateAsync(null,
                Path.Combine(root, "data", "desktop", "webview2"),
                new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required"
                    + (debug ? " --remote-debugging-port=9223" : "")));
            await web.EnsureCoreWebView2Async(env);
            Log("DPI: " + GetDpiForWindow(Handle) + "; PerMonitorV2="
                + AreDpiAwarenessContextsEqual(GetWindowDpiAwarenessContext(Handle), new IntPtr(-4)));
            web.ZoomFactor = 1.0;
            Log("WebView2 ready: " + web.CoreWebView2.Environment.BrowserVersionString);
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "window.__JARVIS_DESKTOP__ = true;"
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
            web.CoreWebView2.WebMessageReceived += delegate(object sender, CoreWebView2WebMessageReceivedEventArgs e) {
                if (!IsLocal(e.Source)) return;
                try {
                    var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
                    if (data.ContainsKey("type") && Convert.ToString(data["type"]) == "language")
                        SetLanguage(data.ContainsKey("language") && Convert.ToString(data["language"]) == "en-US");
                } catch { }
            };
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
        checkingUpdate = true; updateItem.Enabled = false;
        try {
            JarvisUpdateInfo update = await JarvisUpdateChecker.CheckAsync(root);
            if (update.IsAvailable) {
                string message = (english ? "Installed: " : "当前版本：") + update.CurrentVersion
                    + "\n" + (english ? "Latest: " : "最新版本：") + update.LatestVersion;
                if (!String.IsNullOrWhiteSpace(update.Notes)) message += "\n\n" + update.Notes;
                if (interactive) {
                    var answer = MessageBox.Show(message + "\n\n" + (english ? "Download now?" : "现在下载吗？"),
                        "JARVIS", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                    if (answer == DialogResult.Yes) await DownloadUpdate(update);
                } else {
                    tray.BalloonTipTitle = english ? "JARVIS update available" : "JARVIS 有新版本";
                    tray.BalloonTipText = (english ? "Version " : "版本 ") + update.LatestVersion
                        + (english ? " is ready. Click to download." : " 已发布，点击下载。");
                    tray.BalloonTipClicked += async delegate { await DownloadUpdate(update); };
                    tray.ShowBalloonTip(10000);
                }
            } else if (interactive) {
                MessageBox.Show((english ? "You are using the latest version: " : "当前已是最新版本：")
                    + update.CurrentVersion, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        } catch (Exception error) {
            Log("Update check: " + error.Message);
            if (interactive) MessageBox.Show((english ? "Could not check for updates.\n" : "暂时无法检查更新。\n")
                + error.Message, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { checkingUpdate = false; updateItem.Enabled = true; }
    }
    private async Task DownloadUpdate(JarvisUpdateInfo update)
    {
        updateItem.Enabled = false;
        try {
            var progress = new Progress<int>(value => tray.BalloonTipText = (english ? "Downloading... " : "正在下载… ") + value + "%");
            string path = await JarvisUpdateChecker.DownloadAsync(root, update, progress);
            MessageBox.Show((english ? "Update downloaded to:\n" : "更新包已下载到：\n") + path
                + (english ? "\n\nClose JARVIS, then extract it over the program files. Keep data, models and logs." : "\n\n请关闭 JARVIS 后解压覆盖程序文件；保留 data、models 和 logs。"),
                "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Information);
        } catch (Exception error) {
            MessageBox.Show((english ? "Update download failed:\n" : "更新下载失败：\n") + error.Message,
                "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { updateItem.Enabled = true; }
    }
    private async Task Quit()
    {
        await StopListening();
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
