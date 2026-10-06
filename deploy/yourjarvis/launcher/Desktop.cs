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
    internal static readonly string InstanceKey = GetInstanceKey();
    private static string GetInstanceKey() {
        using(var sha=System.Security.Cryptography.SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd('\\').ToUpperInvariant()))).Replace("-", "");
    }
    [STAThread]
    private static void Main(string[] args)
    {
        using (var instance = new Mutex(false, "Local\\JarvisDesktop-" + InstanceKey))
        {
            bool owns = false;
            try { owns = instance.WaitOne(0); }
            catch (AbandonedMutexException) { owns = true; }
            if (!owns)
            {
                try { using (var signal = EventWaitHandle.OpenExisting("Local\\JarvisDesktopActivate-" + DesktopProgram.InstanceKey)) signal.Set(); }
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
    private string Server = "";
    private string serverIdentity = "";
    private bool starting;
    private readonly System.Windows.Forms.Timer healthTimer = new System.Windows.Forms.Timer { Interval = 5000 };
    private const int Hotkey = 0x4A56;
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    private readonly WebView2 web = new WebView2();
    private readonly Label loading = new Label();
    private readonly FlowLayoutPanel recovery = new FlowLayoutPanel();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly ToolStripMenuItem showItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem pauseItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem updateItem = new ToolStripMenuItem();
    private readonly ToolStripMenuItem quitItem = new ToolStripMenuItem();
    private readonly EventWaitHandle activate = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\JarvisDesktopActivate-" + DesktopProgram.InstanceKey);
    private readonly HttpClient http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(8) };
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
        recovery.Dock=DockStyle.Bottom; recovery.Height=64; recovery.Padding=new Padding(24,12,0,0); recovery.Visible=false;
        var retry=new Button {Text="重试启动",Width=120,Height=36};
        var repair=new Button {Text="修复安装",Width=120,Height=36};
        var openLogs=new Button {Text="打开日志目录",Width=150,Height=36};
        retry.Click+=async delegate {await StartAssistant();};
        repair.Click+=async delegate {try {await RunInstaller();await StartAssistant();} catch(Exception ex) {loading.Text=ex.Message;}};
        openLogs.Click+=delegate {Directory.CreateDirectory(Path.Combine(root,"logs"));Process.Start(new ProcessStartInfo(Path.Combine(root,"logs")){UseShellExecute=true});};
        healthTimer.Tick += async delegate {
            if(starting || exiting || !web.Visible) return;
            try {
                using(var response=await http.GetAsync(Server + "/health")) {
                    IEnumerable<string> ids;
                    if(!response.IsSuccessStatusCode || !response.Headers.TryGetValues("X-Jarvis-Instance", out ids) || String.Join("",ids)!=serverIdentity)
                        throw new Exception("后台连接已中断。请点击重试启动，或修复安装。");
                }
            } catch(Exception error) { ShowFailure(error.Message); }
        };
        healthTimer.Start();
        recovery.Controls.AddRange(new Control[]{retry,repair,openLogs}); Controls.Add(recovery);
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
    private bool IsLocal(string address)
    {
        Uri uri;
        return Uri.TryCreate(address, UriKind.Absolute, out uri)
            && uri.Scheme == "http" && uri.Host == "127.0.0.1" && !String.IsNullOrEmpty(Server) && uri.Authority == new Uri(Server).Authority;
    }
    private static void OpenLink(string address)
    {
        Uri uri;
        if (Uri.TryCreate(address, UriKind.Absolute, out uri) && (uri.Scheme == "http" || uri.Scheme == "https"))
            Process.Start(new ProcessStartInfo(address) { UseShellExecute = true });
    }
    private async Task RunInstaller()
    {
        var info=new ProcessStartInfo(Path.Combine(root,"JARVIS-Install.exe"),"--no-launch") {WorkingDirectory=root,UseShellExecute=true};
        using(var process=Process.Start(info)) {await Task.Run((Action)process.WaitForExit);if(process.ExitCode!=0) throw new Exception("安装尚未完成。点击下方“修复安装”继续。");}
    }
    private async Task StartAssistant()
    {
        if(starting || exiting) return;
        starting=true;
        try
        {
            recovery.Visible=false; loading.Visible=true; web.Visible=false; loading.Text="正在启动贾维斯…";
            if (!File.Exists(Path.Combine(root, "config.toml"))
                || !File.Exists(Path.Combine(root, "src", ".venv", "Scripts", "python.exe"))
                || !File.Exists(Path.Combine(root,"install-complete.json")))
            {
                await RunInstaller();
            }
            var start = new ProcessStartInfo("powershell.exe",
                "-NoLogo -NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(root, "start-gui.ps1") + "\" -NoBrowser") {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput=true, RedirectStandardError=true,
                StandardOutputEncoding=new System.Text.UTF8Encoding(false), StandardErrorEncoding=new System.Text.UTF8Encoding(false)
            };
            using (var process = Process.Start(start))
            {
                var readOut=process.StandardOutput.ReadToEndAsync(); var readError=process.StandardError.ReadToEndAsync();
                await Task.Run((Action)process.WaitForExit); string detail=await readError; string normal=await readOut;
                Log("Backend startup: "+normal+Environment.NewLine+detail);
                if (process.ExitCode != 0) throw new Exception("后端启动未完成。点击“修复安装”重试，详细原因已保存到 desktop.log。\n"+(detail.Length>600?detail.Substring(detail.Length-600):detail));
            }
            var state=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(root,"logs","gui-runtime.json")));
            Server=Convert.ToString(state["url"]); serverIdentity=Convert.ToString(state["instance"]);
            Uri backend;
            if(Convert.ToString(state["root"]).TrimEnd('\\')!=root.TrimEnd('\\') || !Uri.TryCreate(Server,UriKind.Absolute,out backend) || backend.Scheme!="http" || backend.Host!="127.0.0.1" || String.IsNullOrEmpty(serverIdentity))
                throw new Exception("后台启动信息无效，请修复安装。");
            using(var response=await http.GetAsync(Server+"/health")) {
                IEnumerable<string> ids;
                if(!response.IsSuccessStatusCode || !response.Headers.TryGetValues("X-Jarvis-Instance",out ids) || String.Join("",ids)!=serverIdentity)
                    throw new Exception("无法连接本安装目录的后台，请重试启动。");
            }
            if(web.CoreWebView2==null) {
            Directory.CreateDirectory(Path.Combine(root, "data", "desktop"));
            var env = await CoreWebView2Environment.CreateAsync(null,
                Path.Combine(root, "data", "desktop", "webview2"),
                new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required --no-proxy-server"
                    + (debug ? " --remote-debugging-port=9223" : "")));
            await web.EnsureCoreWebView2Async(env);
            Log("DPI: " + GetDpiForWindow(Handle) + "; PerMonitorV2="
                + AreDpiAwarenessContextsEqual(GetWindowDpiAwarenessContext(Handle), new IntPtr(-4)));
            web.ZoomFactor = 1.0;
            Log("WebView2 ready: " + web.CoreWebView2.Environment.BrowserVersionString);
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "window.__JARVIS_DESKTOP__ = true;"
                + "if(location.hostname==='127.0.0.1' && navigator.serviceWorker"
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
                if(e.IsSuccess) { web.Visible=true; loading.Visible=false; recovery.Visible=false; web.BringToFront(); }
                else if(e.WebErrorStatus!=CoreWebView2WebErrorStatus.OperationCanceled)
                    ShowFailure("界面未能连接后台（"+e.WebErrorStatus+"）。请点击重试启动。");
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
            }
            web.CoreWebView2.Navigate(Server);
        }
        catch (Exception error)
        {
            Log("Startup error: " + error.ToString());
            ShowFailure(error.Message);
        }
        finally { starting=false; }
    }
    private void ShowFailure(string message) {
        web.Visible=false; loading.Visible=true;
        loading.Text=(english ? "JARVIS could not start.\n" : "贾维斯启动失败。\n")+message+"\n"+Path.Combine(root,"logs","desktop.log");
        recovery.Visible=true; recovery.BringToFront(); Log(message);
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
                + (english ? "\n\nClose JARVIS, run the installer, and choose the existing installation folder." : "\n\n请从托盘退出 JARVIS，运行下载的安装 EXE，选择原安装目录升级。现有配置和数据保留。"),
                "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Information);
        } catch (Exception error) {
            MessageBox.Show((english ? "Update download failed:\n" : "更新下载失败：\n") + error.Message,
                "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { updateItem.Enabled = true; }
    }
    private async Task Quit()
    {
        await StopListening();
        try {
            var stop=new ProcessStartInfo("powershell.exe","-NoLogo -NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,"stop-gui.ps1")+"\"") {WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden};
            using(var process=Process.Start(stop)) await Task.Run((Action)process.WaitForExit);
        } catch(Exception error) {Log("Backend shutdown: "+error.Message);}
        exiting = true;
        tray.Visible = false;
        Close();
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { exiting = true; healthTimer.Dispose(); activate.Dispose(); tray.Dispose(); http.Dispose(); web.Dispose(); }
        base.Dispose(disposing);
    }
}
