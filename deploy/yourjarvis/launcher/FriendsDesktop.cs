using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

internal static class LinkProgram
{
    [STAThread]
    private static void Main(string[] args)
    {
        string key;
        using (var sha = SHA256.Create()) key = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(AppDomain.CurrentDomain.BaseDirectory.ToLowerInvariant()))).Replace("-", "").Substring(0, 16);
        using (var mutex = new Mutex(false, "Local\\JarvisLink_" + key)) {
            bool owns;
            try { owns = mutex.WaitOne(0); } catch (AbandonedMutexException) { owns = true; }
            if (!owns) { MessageBox.Show("JARVIS Link 已经打开，请切换到它的窗口。", "JARVIS Link"); return; }
            try {
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new LinkWindow(Array.IndexOf(args, "--debug") >= 0));
            } finally { mutex.ReleaseMutex(); }
        }
    }
}

internal sealed class LinkWindow : Form
{
    private const string Home = "https://jarvis-link.local/home.html";
    private const string Chat = "https://jarvis-link.local/chat.html";
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
    private readonly WebView2 web = new WebView2();
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly Panel bar = new Panel();
    private readonly Label caption = new Label();
    private readonly Button homeButton = new Button();
    private readonly Button updateButton = new Button();
    private readonly Label loading = new Label();
    private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
    private CancellationTokenSource chatCancel;
    private CancellationTokenSource startCancel;
    private Process ollama;
    private string ollamaUrl = "";
    private string allowedBase = Home;
    private string pendingToken = "";
    private string paletteCss = "";
    private bool starting;
    private bool closing;
    private bool checkingUpdate;
    private readonly bool debug;
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr hwnd);

    public LinkWindow(bool enableDebug)
    {
        debug = enableDebug; Text = "JARVIS Link";
        AutoScaleMode = AutoScaleMode.Dpi; Size = new Size(1120, 800);
        MinimumSize = new Size(800, 620); StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(242, 248, 252); Font = new Font("Microsoft YaHei UI", 10);
        bar.Dock = DockStyle.Top; bar.Height = 44; bar.BackColor = Color.White;
        caption.Text = "JARVIS Link · 选择使用方式"; caption.ForeColor = Color.FromArgb(21, 49, 74);
        caption.Dock = DockStyle.Fill; caption.TextAlign = ContentAlignment.MiddleLeft; caption.Padding = new Padding(18, 0, 0, 0);
        homeButton.Text = "使用方式"; homeButton.Dock = DockStyle.Right; homeButton.Width = 112;
        homeButton.FlatStyle = FlatStyle.Flat; homeButton.FlatAppearance.BorderSize = 0;
        homeButton.BackColor = bar.BackColor; homeButton.ForeColor = Color.FromArgb(8, 123, 153);
        homeButton.Click += delegate { if (chatCancel != null) chatCancel.Cancel(); ShowHome(); };
        updateButton.Text = "检查更新"; updateButton.Dock = DockStyle.Right; updateButton.Width = 112;
        updateButton.FlatStyle = FlatStyle.Flat; updateButton.FlatAppearance.BorderSize = 0;
        updateButton.BackColor = bar.BackColor; updateButton.ForeColor = Color.FromArgb(8, 123, 153);
        updateButton.Click += async delegate { await CheckForUpdates(true); };
        bar.Controls.Add(caption); bar.Controls.Add(updateButton); bar.Controls.Add(homeButton);
        web.Dock = DockStyle.Fill; loading.Dock = DockStyle.Fill;
        loading.ForeColor = caption.ForeColor; loading.TextAlign = ContentAlignment.MiddleCenter; loading.Text = "正在打开 JARVIS Link…";
        Controls.Add(web); Controls.Add(loading); Controls.Add(bar);
        Shown += async delegate {
            var area = Screen.FromHandle(Handle).WorkingArea; double scale = GetDpiForWindow(Handle) / 96.0;
            Size = new Size((int)Math.Min(area.Width * 0.94, 1100 * scale), (int)Math.Min(area.Height * 0.94, 760 * scale));
            CenterToScreen(); await Initialize();
        };
        FormClosing += async delegate(object sender, FormClosingEventArgs e) {
            if (closing) return;
            e.Cancel = true; closing = true; lifetime.Cancel(); if (chatCancel != null) chatCancel.Cancel(); if (startCancel != null) startCancel.Cancel();
            await StopOllama(); Close();
        };
    }

    private async Task Initialize()
    {
        try {
            string runtime = Path.Combine(root, "runtimes", "webview2");
            if (!File.Exists(Path.Combine(runtime, "msedgewebview2.exe"))) throw new Exception("包内 WebView2 运行时缺失，请重新解压完整软件包。");
            if (Environment.OSVersion.Version.Build < 22000) {
                foreach (string sid in new string[] {"*S-1-15-2-2", "*S-1-15-2-1"}) {
                    var permissions = new ProcessStartInfo("icacls.exe", "\"" + runtime + "\" /grant \"" + sid + ":(OI)(CI)(RX)\"") { UseShellExecute = false, CreateNoWindow = true };
                    using (var process = Process.Start(permissions)) { await Task.Run(() => process.WaitForExit(10000)); if (!process.HasExited || process.ExitCode != 0) throw new Exception("无法设置包内浏览器读取权限，请将应用解压到自己的可写目录。"); }
                }
            }
            Directory.CreateDirectory(Path.Combine(root, "data", "webview"));
            var options = new CoreWebView2EnvironmentOptions("--disable-background-networking --disable-component-update --disable-domain-reliability" + (debug ? " --remote-debugging-port=9247" : ""));
            var environment = await CoreWebView2Environment.CreateAsync(runtime, Path.Combine(root, "data", "webview"), options);
            await web.EnsureCoreWebView2Async(environment);
            web.CoreWebView2.SetVirtualHostNameToFolderMapping("jarvis-link.local", Path.Combine(root, "client"), CoreWebView2HostResourceAccessKind.DenyCors);
            web.CoreWebView2.Settings.AreDevToolsEnabled = debug; web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            web.CoreWebView2.Settings.IsPasswordAutosaveEnabled = false; web.CoreWebView2.Settings.IsGeneralAutofillEnabled = false;
            web.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!Allowed(e.Uri)) e.Cancel = true; };
            web.CoreWebView2.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) { e.Handled = true; };
            web.CoreWebView2.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) { e.State = CoreWebView2PermissionState.Deny; };
            web.CoreWebView2.WebMessageReceived += async delegate(object sender, CoreWebView2WebMessageReceivedEventArgs e) {
                if (!e.Source.StartsWith("https://jarvis-link.local/", StringComparison.OrdinalIgnoreCase)) return;
                string failure = null; bool ownsStart = false;
                try {
                    var data = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); string action = Convert.ToString(data["action"]);
                    if (action == "theme") { ApplyTheme(data); return; }
                    if (action == "ready") { await SetAddress(); return; }
                    if (action == "cancel") { if (chatCancel != null) chatCancel.Cancel(); if (startCancel != null) startCancel.Cancel(); return; }
                    if (action == "chat" && e.Source == Chat) { await SendChat(data); return; }
                    if (starting) return;
                    if (action == "local" || action == "remote") {
                        ownsStart = true; starting = true; homeButton.Enabled = false;
                        if (action == "local") await StartLocal();
                        else await ConnectRemote(Convert.ToString(data["address"]), Convert.ToString(data["token"]));
                    }
                } catch (Exception error) { failure = error is OperationCanceledException ? "已停止。" : error.Message; }
                finally { if (!closing && ownsStart) { starting = false; homeButton.Enabled = true; } }
                if (failure != null && !closing) await Status(failure, true);
            };
            web.CoreWebView2.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                if (closing) return;
                try {
                    if (!e.IsSuccess) { pendingToken = ""; ShowHome(); return; }
                    if (pendingToken.Length == 0 || !Allowed(web.Source.AbsoluteUri) || web.Source.Host == "jarvis-link.local") return;
                    string token = pendingToken; pendingToken = "";
                    string css = File.ReadAllText(Path.Combine(root, "client", "chat.css"), Encoding.UTF8) + File.ReadAllText(Path.Combine(root, "client", "chat-layout.css"), Encoding.UTF8) + paletteCss;
                    await web.ExecuteScriptAsync("(()=>{document.title='JARVIS Link';document.querySelector('h1 span').textContent='主机聊天';document.querySelector('footer').textContent='JARVIS Link';const sheet=new CSSStyleSheet();sheet.replaceSync(" + json.Serialize(css) + ");document.adoptedStyleSheets=[sheet];const input=document.getElementById('token');const form=document.getElementById('login-form');if(input&&form){input.value=" + json.Serialize(token) + ";form.requestSubmit();}})()");
                } catch { pendingToken = ""; ShowHome(); }
            };
            loading.Visible = false; web.BringToFront(); ShowHome(); await CheckForUpdates(false);
        } catch (Exception error) { loading.Text = "JARVIS Link 无法打开。\n" + error.Message; }
    }

    private bool Allowed(string address)
    {
        Uri uri, expected;
        if (!Uri.TryCreate(address, UriKind.Absolute, out uri) || !Uri.TryCreate(allowedBase, UriKind.Absolute, out expected)) return false;
        if (uri.GetLeftPart(UriPartial.Authority) != expected.GetLeftPart(UriPartial.Authority)) return false;
        return expected.Host == "jarvis-link.local" || uri.AbsolutePath.StartsWith(expected.AbsolutePath.TrimEnd('/') + "/", StringComparison.Ordinal) || uri.AbsolutePath == expected.AbsolutePath.TrimEnd('/');
    }
    private static string ValidateAddress(string address)
    {
        Uri uri;
        if (!Uri.TryCreate(address.Trim(), UriKind.Absolute, out uri) || (uri.Scheme != "http" && uri.Scheme != "https") || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0 || uri.Host == "jarvis-link.local") throw new Exception("请输入 HTTP(S) 主机地址，不要在地址里填写令牌或密码。");
        IPAddress ip; bool privateAddress = uri.IsLoopback;
        if (IPAddress.TryParse(uri.Host, out ip) && ip.AddressFamily == AddressFamily.InterNetwork) { byte[] b = ip.GetAddressBytes(); privateAddress = privateAddress || b[0] == 10 || (b[0] == 192 && b[1] == 168) || (b[0] == 172 && b[1] >= 16 && b[1] <= 31); }
        if (uri.Scheme != "https" && !privateAddress) throw new Exception("远程主机请使用 HTTPS；本机或局域网测试可以使用 HTTP。");
        return uri.AbsoluteUri.TrimEnd('/');
    }
    private async Task ConnectRemote(string address, string token)
    {
        string endpoint = ValidateAddress(address);
        if (token.Length == 0 || token.Length > 256 || token.IndexOfAny(new char[] {'\r', '\n'}) >= 0) throw new Exception("请输入有效的邀请令牌。");
        await Status("正在验证主机与邀请令牌…", false);
        using (var handler = new HttpClientHandler { AllowAutoRedirect = false, UseProxy = !new Uri(endpoint).IsLoopback })
        using (var http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(15) })
        using (var request = new HttpRequestMessage(HttpMethod.Get, endpoint + "/api/friends/config")) {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
            using (var response = await http.SendAsync(request, lifetime.Token)) {
                if (response.StatusCode == HttpStatusCode.Unauthorized) throw new Exception("邀请令牌无效或已撤销，请向主机主人确认。");
                if (!response.IsSuccessStatusCode) throw new Exception("主机不可用，或该地址不是共享服务入口。");
                var data = json.Deserialize<Dictionary<string, object>>(await response.Content.ReadAsStringAsync());
                if (!data.ContainsKey("member") || !data.ContainsKey("model")) throw new Exception("该地址不是兼容的 JARVIS 共享服务。");
            }
        }
        Directory.CreateDirectory(Path.Combine(root, "data")); File.WriteAllText(Path.Combine(root, "data", "host-address.txt"), endpoint, Encoding.UTF8);
        if (chatCancel != null) chatCancel.Cancel(); await StopOllama();
        pendingToken = token; allowedBase = endpoint; caption.Text = "JARVIS Link · 主机聊天 · " + new Uri(endpoint).Host;
        web.CoreWebView2.Navigate(endpoint + "/");
    }

    private async Task StartLocal()
    {
        Exception failure = null;
        using (startCancel = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token)) {
            try {
                await Status("正在检查包内模型，完全离线启动…", false);
                string manifest = Path.Combine(root, "models", "ollama", "manifests", "registry.ollama.ai", "library", "qwen2.5", "0.5b");
                if (!File.Exists(manifest)) throw new Exception("包内模型缺失，请重新解压完整安装包；不会自动联网下载。");
                if (ollama == null || ollama.HasExited) {
                    string exe = Path.Combine(root, "runtimes", "ollama", "ollama.exe");
                    if (!File.Exists(exe)) throw new Exception("CPU 运行时缺失，请重新解压软件包。");
                    var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(); int port = ((IPEndPoint)listener.LocalEndpoint).Port; listener.Stop();
                    ollamaUrl = "http://127.0.0.1:" + port;
                    var info = new ProcessStartInfo(exe, "serve") { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
                    info.EnvironmentVariables["OLLAMA_MODELS"] = Path.Combine(root, "models", "ollama"); info.EnvironmentVariables["OLLAMA_HOST"] = ollamaUrl;
                    info.EnvironmentVariables["OLLAMA_NO_CLOUD"] = "1"; info.EnvironmentVariables["OLLAMA_VULKAN"] = "false";
                    info.EnvironmentVariables["CUDA_VISIBLE_DEVICES"] = "-1"; info.EnvironmentVariables["HIP_VISIBLE_DEVICES"] = "-1";
                    info.EnvironmentVariables["OLLAMA_NUM_PARALLEL"] = "1"; info.EnvironmentVariables["OLLAMA_MAX_LOADED_MODELS"] = "1";
                    info.EnvironmentVariables["HTTP_PROXY"] = ""; info.EnvironmentVariables["HTTPS_PROXY"] = ""; info.EnvironmentVariables["ALL_PROXY"] = ""; info.EnvironmentVariables["NO_PROXY"] = "127.0.0.1,localhost";
                    Directory.CreateDirectory(Path.Combine(root, "logs"));
                    ollama = new Process { StartInfo = info };
                    DataReceivedEventHandler log = delegate(object sender, DataReceivedEventArgs e) { if (!String.IsNullOrEmpty(e.Data)) { try { lock (json) File.AppendAllText(Path.Combine(root, "logs", "local-model.log"), e.Data + Environment.NewLine, Encoding.UTF8); } catch { } } };
                    ollama.OutputDataReceived += log; ollama.ErrorDataReceived += log;
                    ollama.Start(); ollama.BeginOutputReadLine(); ollama.BeginErrorReadLine();
                }
                using (var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(2) }) {
                    bool healthy = false;
                    for (int i = 0; i < 60; i++) {
                        startCancel.Token.ThrowIfCancellationRequested(); if (ollama.HasExited) throw new Exception("本地模型服务退出，请查看 logs/local-model.log。");
                        try { using (var response = await http.GetAsync(ollamaUrl + "/api/tags", startCancel.Token)) {
                            if (response.IsSuccessStatusCode) { string models = await response.Content.ReadAsStringAsync(); if (!models.Contains("qwen2.5:0.5b")) throw new InvalidDataException("包内模型文件不完整，请重新解压。"); healthy = true; break; }
                        } } catch (HttpRequestException) { } catch (TaskCanceledException) { startCancel.Token.ThrowIfCancellationRequested(); }
                        await Task.Delay(300, startCancel.Token);
                    }
                    if (!healthy) throw new Exception("本地模型启动超时，请查看日志后重试。");
                }
                startCancel.Token.ThrowIfCancellationRequested(); allowedBase = Chat;
                caption.Text = "JARVIS Link · 本机 CPU · Qwen2.5 0.5B"; web.CoreWebView2.Navigate(Chat);
            } catch (Exception error) { failure = error; }
        }
        startCancel = null;
        if (failure != null) { await StopOllama(); throw failure; }
    }

    private async Task SendChat(Dictionary<string, object> data)
    {
        string id = Convert.ToString(data["id"]);
        if (chatCancel != null) { await Reply(id, "", "上一条还在处理，请稍候。", true); return; }
        var messages = new List<Dictionary<string, string>>(); int size = 0; string failure = null;
        try {
            foreach (var item in (IEnumerable)data["messages"]) {
                var message = item as Dictionary<string, object>; if (message == null) throw new Exception("无效消息。");
                string role = Convert.ToString(message["role"]), content = Convert.ToString(message["content"]);
                if ((role != "user" && role != "assistant") || content.Length == 0 || content.Length > 4000) throw new Exception("消息过长或格式不正确。");
                messages.Add(new Dictionary<string, string> { {"role", role}, {"content", content} }); size += content.Length;
            }
            if (messages.Count == 0 || messages.Count > 12 || size > 8000 || messages[messages.Count - 1]["role"] != "user") throw new Exception("对话上下文过长，请新建对话。");
            messages.Insert(0, new Dictionary<string, string> { {"role", "system"}, {"content", "你是 JARVIS，用户的本地聊天助手。默认使用简体中文，回答自然、直接、简洁。你没有文件、桌面或工具权限，不要编造现实操作结果。通常回答一至三句话。"} });
            using (var timeout = new CancellationTokenSource(180000))
            using (var cancel = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token, timeout.Token)) {
                chatCancel = cancel;
                var body = new Dictionary<string, object> { {"model", "qwen2.5:0.5b"}, {"stream", true}, {"messages", messages}, {"options", new Dictionary<string, object> { {"num_gpu", 0}, {"num_ctx", 2048}, {"num_predict", 256}, {"temperature", 0.3} }} };
                using (var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = Timeout.InfiniteTimeSpan })
                using (var request = new HttpRequestMessage(HttpMethod.Post, ollamaUrl + "/api/chat") { Content = new StringContent(json.Serialize(body), Encoding.UTF8, "application/json") })
                using (var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancel.Token)) {
                    if (!response.IsSuccessStatusCode) throw new Exception("本地模型请求失败，请重新打开本机聊天。");
                    using (cancel.Token.Register(() => response.Dispose()))
                    using (var reader = new StreamReader(await response.Content.ReadAsStreamAsync(), Encoding.UTF8)) {
                        string line; bool done = false; int output = 0;
                        while ((line = await reader.ReadLineAsync()) != null) {
                            cancel.Token.ThrowIfCancellationRequested(); var chunk = json.Deserialize<Dictionary<string, object>>(line);
                            if (chunk.ContainsKey("error")) throw new Exception("本地模型生成失败，请查看日志后重试。");
                            if (chunk.ContainsKey("message")) {
                                var message = (Dictionary<string, object>)chunk["message"]; string content = Convert.ToString(message["content"]);
                                output += content.Length; if (output > 16000) throw new Exception("回复过长，已停止。");
                                await Reply(id, content, "", false);
                            }
                            if (chunk.ContainsKey("done") && Convert.ToBoolean(chunk["done"])) { done = true; break; }
                        }
                        if (!done) throw new Exception("连接中断，回复未完成。");
                        await Reply(id, "", "", true);
                    }
                }
            }
        } catch (Exception error) { failure = (chatCancel != null && chatCancel.IsCancellationRequested) ? "已停止或请求超时。" : error.Message; }
        finally { chatCancel = null; }
        if (failure != null) await Reply(id, "", failure, true);
    }

    private Task Reply(string id, string content, string error, bool done)
    {
        if (closing || web.Source == null || web.Source.AbsoluteUri != Chat) return Task.FromResult(0);
        return web.ExecuteScriptAsync("window.linkReply(" + json.Serialize(new { id, content, error, done }) + ")");
    }
    private async Task StopOllama()
    {
        if (ollama == null) return;
        try {
            if (!ollama.HasExited) {
                var stop = new ProcessStartInfo("taskkill.exe", "/PID " + ollama.Id + " /T /F") { UseShellExecute = false, CreateNoWindow = true };
                using (var process = Process.Start(stop)) await Task.Run(() => process.WaitForExit(5000));
            }
        } catch { }
        finally { ollama.Dispose(); ollama = null; }
    }
    private Task Status(string message, bool failed)
    {
        if (closing || web.CoreWebView2 == null || web.Source == null || web.Source.AbsoluteUri != Home) return Task.FromResult(0);
        return web.ExecuteScriptAsync("window.friendStatus&&window.friendStatus(" + json.Serialize(message) + "," + (failed ? "true" : "false") + ")");
    }
    private async Task SetAddress()
    {
        string file = Path.Combine(root, "data", "host-address.txt");
        if (web.Source.AbsoluteUri == Home && File.Exists(file)) await web.ExecuteScriptAsync("window.friendAddress(" + json.Serialize(File.ReadAllText(file, Encoding.UTF8)) + ")");
    }
    private void ShowHome()
    {
        if (closing || web.CoreWebView2 == null) return;
        pendingToken = ""; allowedBase = Home; caption.Text = "JARVIS Link · 选择使用方式"; web.CoreWebView2.Navigate(Home);
    }
    private async Task CheckForUpdates(bool interactive)
    {
        if (checkingUpdate || closing) return;
        checkingUpdate = true; updateButton.Enabled = false;
        try {
            JarvisUpdateInfo update = await JarvisUpdateChecker.CheckAsync(root);
            if (update.IsAvailable) {
                string message = "当前版本：" + update.CurrentVersion + "\n最新版本：" + update.LatestVersion;
                if (!String.IsNullOrWhiteSpace(update.Notes)) message += "\n\n" + update.Notes;
                var answer = MessageBox.Show(message + "\n\n现在打开下载页面吗？", "JARVIS Link 有新版本",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (answer == DialogResult.Yes) await DownloadUpdate(update);
            } else if (interactive) {
                MessageBox.Show("当前已是最新版本：" + update.CurrentVersion, "JARVIS Link",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        } catch (Exception error) {
            if (interactive) MessageBox.Show("暂时无法检查更新。\n" + error.Message, "JARVIS Link",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { checkingUpdate = false; updateButton.Enabled = true; }
    }
    private async Task DownloadUpdate(JarvisUpdateInfo update)
    {
        updateButton.Enabled = false;
        try {
            var progress = new Progress<int>(value => updateButton.Text = value + "%");
            string path = await JarvisUpdateChecker.DownloadAsync(root, update, progress);
            MessageBox.Show("更新包已下载到：\n" + path + "\n\n请关闭 JARVIS Link 后解压覆盖程序文件；data、models 和 logs 目录请保留。", "JARVIS Link 更新", MessageBoxButtons.OK, MessageBoxIcon.Information);
        } catch (Exception error) {
            MessageBox.Show("更新下载失败：\n" + error.Message, "JARVIS Link", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        } finally { updateButton.Text = "检查更新"; updateButton.Enabled = true; }
    }
    private void ApplyTheme(Dictionary<string, object> data)
    {
        var colors = new Dictionary<string, string>();
        foreach (string name in new string[] {"bg", "surface", "text", "secondary", "accent", "onAccent"}) {
            string value = Convert.ToString(data[name]); if (!System.Text.RegularExpressions.Regex.IsMatch(value, "^#[0-9a-fA-F]{6}$")) return; colors[name] = value;
        }
        BackColor = ColorTranslator.FromHtml(colors["bg"]); bar.BackColor = ColorTranslator.FromHtml(colors["surface"]);
        caption.ForeColor = ColorTranslator.FromHtml(colors["text"]); homeButton.BackColor = bar.BackColor; homeButton.ForeColor = ColorTranslator.FromHtml(colors["accent"]);
        updateButton.BackColor = bar.BackColor; updateButton.ForeColor = ColorTranslator.FromHtml(colors["accent"]);
        paletteCss = ":root{color-scheme:" + (colors["onAccent"] == "#ffffff" ? "light" : "dark") + ";--bg:" + colors["bg"] + ";--surface:" + colors["surface"] + ";--text:" + colors["text"] + ";--muted:" + colors["secondary"] + ";--accent:" + colors["accent"] + ";--on-accent:" + colors["onAccent"] + ";}";
    }
}
