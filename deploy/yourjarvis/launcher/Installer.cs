using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8")]
internal static class InstallProgram
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string id = Convert.ToBase64String(Encoding.UTF8.GetBytes(root.ToLowerInvariant())).Replace('/', '_').Replace('\\', '_');
        using (var mutex = new Mutex(false, "Local\\JarvisInstall_" + id))
        {
            bool owns = false;
            try { owns = mutex.WaitOne(0); } catch (AbandonedMutexException) { owns = true; }
            if (!owns) { MessageBox.Show("安装向导已打开，请切换到已有窗口。", "JARVIS 安装"); return; }
            try { using (var wizard = new InstallWizard(root, args)) { Application.Run(wizard); Environment.ExitCode = wizard.Completed ? 0 : 1; } }
            catch (Exception ex) { MessageBox.Show("无法打开安装向导：" + ex.Message, "JARVIS 安装", MessageBoxButtons.OK, MessageBoxIcon.Error); Environment.ExitCode = 1; }
            finally { mutex.ReleaseMutex(); }
        }
    }
}

internal sealed class InstallWizard : Form
{
    private readonly string source;
    private string root, secret = "", logPath;
    private readonly bool noLaunch;
    private readonly bool autoUpdate;
    private int page;
    private bool running, cancelled;
    private Process worker;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly Panel content = new Panel();
    private readonly Label heading = new Label(), subtitle = new Label(), status = new Label(), elapsed = new Label();
    private readonly Button back = new Button(), next = new Button(), close = new Button(), browse = new Button(), logs = new Button();
    private readonly TextBox directory = new TextBox(), model = new TextBox(), url = new TextBox(), key = new TextBox(), output = new TextBox();
    private readonly ComboBox profile = new ComboBox(), voice = new ComboBox(), channel = new ComboBox();
    private readonly CheckBox preserve = new CheckBox(), shortcut = new CheckBox(), startAfter = new CheckBox();
    private readonly Label hint = new Label(), summary = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly ListBox stages = new ListBox();
    private readonly string[] steps = { "检查安装包和磁盘", "安装 Python 与依赖", "安装桌面窗口组件", "下载模型 / 测试 API", "准备所选语音", "保存配置和应用自检", "完成并准备启动" };
    private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    private DateTime started;
    private readonly object logLock = new object();
    public bool Completed { get; private set; }

    public InstallWizard(string packageRoot, string[] args)
    {
        source = packageRoot; root = source; noLaunch = args.Contains("--no-launch"); autoUpdate = args.Contains("--auto-update");
        Text = "JARVIS 0.1.5 · 安装向导";
        Font = new Font("Microsoft YaHei UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(800, 650); MinimumSize = Size; MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen; BackColor = Color.FromArgb(244, 247, 252);
        heading.SetBounds(32, 24, 730, 42); heading.Font = new Font(Font.FontFamily, 22F, FontStyle.Bold);
        heading.ForeColor = Color.FromArgb(24, 47, 74);
        subtitle.SetBounds(34, 76, 726, 46); subtitle.ForeColor = Color.FromArgb(70, 83, 102);
        content.SetBounds(32, 132, 736, 420); content.BackColor = Color.White; content.Padding = new Padding(1);
        content.Paint += delegate(object sender, PaintEventArgs e) { using (var pen = new Pen(Color.FromArgb(221, 228, 238))) e.Graphics.DrawRectangle(pen, 0, 0, content.Width - 1, content.Height - 1); };
        back.Text = "上一步"; back.SetBounds(410, 590, 104, 38);
        next.Text = "下一步"; next.SetBounds(526, 590, 124, 38);
        close.Text = "退出"; close.SetBounds(662, 590, 104, 38);
        StyleButton(back, false); StyleButton(next, true); StyleButton(close, false);
        elapsed.SetBounds(34, 592, 360, 38);
        Controls.AddRange(new Control[] { heading, subtitle, content, back, next, close, elapsed });
        back.Click += delegate { if (!running) { page = Math.Max(0, page - 1); ShowPage(); } };
        next.Click += async delegate { await Advance(); };
        close.Click += delegate { Close(); };
        FormClosing += OnClosing;
        timer.Interval = 1000;
        timer.Tick += delegate { if (running) elapsed.Text = "正在安装 · 已用时 " + (DateTime.Now - started).ToString(@"hh\:mm\:ss"); };
        directory.Text = source; directory.SetBounds(24, 174, 564, 30);
        browse.Text = "选择目录…"; browse.SetBounds(600, 170, 112, 38);
        browse.Click += delegate { using (var picker = new FolderBrowserDialog { Description = "选择 JARVIS 安装目录（可新建空目录）", SelectedPath = directory.Text }) { if (picker.ShowDialog(this) == DialogResult.OK) directory.Text = picker.SelectedPath; } };
        preserve.Text = "保留此目录的现有配置，仅修复运行环境"; preserve.SetBounds(24, 242, 676, 30);
        directory.TextChanged += delegate { preserve.Checked = File.Exists(Path.Combine(directory.Text, "config.toml")); preserve.Enabled = preserve.Checked; };
        preserve.Checked = File.Exists(Path.Combine(source, "config.toml")); preserve.Enabled = preserve.Checked;
        shortcut.Text = "在桌面创建 JARVIS 快捷方式"; shortcut.SetBounds(24, 294, 680, 30); shortcut.Checked = true;
        channel.DropDownStyle=ComboBoxStyle.DropDownList; channel.SetBounds(160,346,550,32);
        channel.Items.AddRange(new object[]{"Gitee 优先 · 国内推荐，失败自动切换 GitHub", "GitHub 优先 · 失败自动切换 Gitee"}); channel.SelectedIndex=0;
        profile.DropDownStyle = ComboBoxStyle.DropDownList; profile.SetBounds(160, 28, 550, 32);
        profile.Items.AddRange(new object[] { "轻量本地模型 · 推荐，约 0.4 GB，提供国内镜像", "使用已安装的本机模型 · 请填写模型名称", "连接兼容 API · 填写服务商或远程服务提供的资料" }); profile.SelectedIndex = 0;
        model.SetBounds(160, 98, 550, 30); model.Text = "qwen2.5:0.5b";
        url.SetBounds(160, 160, 550, 30); key.SetBounds(160, 222, 550, 30); key.UseSystemPasswordChar = true;
        voice.DropDownStyle = ComboBoxStyle.DropDownList; voice.SetBounds(160, 284, 550, 32);
        voice.Items.AddRange(new object[] { "先使用文字 · 推荐，下载较少；以后可开启语音", "中文男声 · 自动下载识别与声音资源", "中文女声 · 自动下载识别与声音资源", "English · 自动下载英文识别与声音资源" }); voice.SelectedIndex = args.Contains("--voice") ? 1 : 0;
        hint.SetBounds(24, 338, 688, 64); hint.ForeColor = Color.FromArgb(75, 88, 103);
        profile.SelectedIndexChanged += delegate { model.Text = profile.SelectedIndex == 0 ? "qwen2.5:0.5b" : ""; SetFields(); };
        summary.SetBounds(24, 24, 688, 292);
        startAfter.Text = "安装成功后打开 JARVIS"; startAfter.SetBounds(24, 340, 650, 30); startAfter.Checked = !noLaunch;
        stages.SetBounds(24, 20, 688, 172); stages.BorderStyle = BorderStyle.None; stages.ItemHeight = 26; stages.Enabled = false;
        progress.SetBounds(24, 206, 688, 20); progress.Style = ProgressBarStyle.Marquee;
        status.SetBounds(24, 235, 688, 44);
        output.SetBounds(24, 284, 560, 114); output.Multiline = true; output.ReadOnly = true; output.ScrollBars = ScrollBars.Vertical; output.Font = new Font("Consolas", 9F);
        logs.Text = "打开日志"; logs.SetBounds(594, 284, 118, 36);
        logs.Click += delegate { if (!String.IsNullOrEmpty(logPath) && File.Exists(logPath)) Process.Start(new ProcessStartInfo("notepad.exe", Quote(logPath)) { UseShellExecute = true }); };
        if (autoUpdate) { directory.Text = source; preserve.Checked = true; preserve.Enabled = true; page = 2; }
        ShowPage();
        if (autoUpdate) Shown += async delegate { await Install(); };
    }

    private void StyleButton(Button button, bool primary)
    {
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = primary ? 0 : 1;
        button.FlatAppearance.BorderColor = Color.FromArgb(201, 211, 225);
        button.BackColor = primary ? Color.FromArgb(29, 87, 191) : Color.White;
        button.ForeColor = primary ? Color.White : Color.FromArgb(36, 53, 75);
        button.Font = new Font(Font.FontFamily, 10F, FontStyle.Bold);
        button.Cursor = Cursors.Hand;
    }

    private static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    private Label LabelAt(string text, int y) { return new Label { Text = text, Left = 24, Top = y, Width = 130, Height = 32, TextAlign = ContentAlignment.MiddleLeft }; }
    private void SetFields()
    {
        bool api = profile.SelectedIndex == 2;
        profile.Enabled = model.Enabled = voice.Enabled = !preserve.Checked;
        url.Enabled = key.Enabled = api && !preserve.Checked;
        hint.Text = preserve.Checked ? "修复将读取并保留现有模型、密钥、人物设置和记忆，不重建配置。" : api ? "地址示例：https://api.example.com/v1。模型名称由服务商提供。安装会发送一次短请求验证连接，可能产生极少量 API 用量。" : profile.SelectedIndex == 1 ? "请填写本机已安装的 Ollama 模型名称。自定义模型不包含国内资源镜像。" : "向导会自动安装 Ollama，并从发布地址下载轻量模型。文字模式至少预留 4 GB，语音模式建议预留 10 GB。";
    }
    private void ShowPage()
    {
        content.Controls.Clear(); back.Visible = page > 0 && page < 4; back.Enabled = !running;
        next.Enabled = !running; close.Text = running ? "取消安装" : "退出";
        if (page == 0)
        {
            heading.Text = "欢迎安装 JARVIS"; subtitle.Text = "1 选择安装位置  →  2 选择使用方案  →  3 确认  →  4 自动安装";
            var intro = new Label { Left = 24, Top = 24, Width = 688, Height = 118, Text = "只需跟着这个窗口操作，向导会按顺序完成安装。\r\n\r\n运行环境和默认模型从项目发布地址下载，支持断点续传。\r\n首次安装请保持联网，无需安装 Python 或输入命令。" };
            content.Controls.AddRange(new Control[] { intro, LabelAt("安装位置", 138), directory, browse, preserve, shortcut, LabelAt("下载来源",346), channel });
            next.Text = "下一步";
        }
        else if (page == 1)
        {
            heading.Text = "选择你的使用方案"; subtitle.Text = "不确定如何选择时，保持“轻量本地模型”和“先使用文字”即可。";
            content.Controls.AddRange(new Control[] { LabelAt("模型方案",28), profile, LabelAt("模型名称",98), model, LabelAt("API 地址",160), url, LabelAt("API 密钥",222), key, LabelAt("语音方案",284), voice, hint }); SetFields(); next.Text = "下一步";
        }
        else if (page == 2)
        {
            heading.Text = "确认后开始安装"; subtitle.Text = "安装期间窗口会显示当前步骤。失败后可以修改方案并重试。";
            summary.Text = "安装位置：\r\n" + root + "\r\n\r\n" + (preserve.Checked ? "配置：保留当前设置并修复环境" : "模型：" + model.Text.Trim() + "\r\n方案：" + profile.SelectedItem + "\r\n语音：" + voice.SelectedItem) + "\r\n\r\n安装顺序：\r\n检查文件 → Python 与依赖 → 桌面组件 → 模型连接\r\n→ 语音资源 → 保存配置与应用自检\r\n\r\n" + (File.Exists(Path.Combine(root,"config.toml")) && !preserve.Checked ? "重新配置会先备份原 config.toml；聊天记录和模型保留。" : "已下载的依赖和模型会在重试时复用。") + "\r\n" + (shortcut.Checked ? "将在桌面创建快捷方式。" : "");
            content.Controls.AddRange(new Control[] { summary, startAfter }); next.Text = "开始安装";
        }
        else
        {
            heading.Text = Completed ? "JARVIS 已准备就绪" : running ? "正在为你安装 JARVIS" : "安装尚未完成";
            subtitle.Text = Completed ? "安装与模型连接检查通过，可以开始使用。" : "下载时请保持网络连接。发生问题时，下方会显示原因。";
            content.Controls.AddRange(new Control[] { stages, progress, status, output, logs });
            next.Text = Completed ? (noLaunch ? "完成" : "启动 JARVIS") : "重试安装"; next.Enabled = !running;
            back.Visible = !running && !Completed; close.Text = running ? "取消安装" : "关闭";
        }
    }

    private async Task Advance()
    {
        if (running) return;
        try
        {
            if (Completed) { if (noLaunch) Close(); else Launch(); return; }
            if (page == 0)
            {
                root = Path.GetFullPath(directory.Text.Trim()).TrimEnd(Path.DirectorySeparatorChar);
                if (root.Length < 4) throw new Exception("请选择一个专用安装文件夹，不要选择磁盘根目录。");
                if (root.IndexOf('"') >= 0) throw new Exception("安装路径无效。");
                // A package must be fully extracted, never run out of Explorer's temp preview.
                if (!File.Exists(Path.Combine(source, "package-manifest.json"))) throw new Exception("请先完整解压整个 ZIP 安装包，再双击 JARVIS-Install.exe。");
                Directory.CreateDirectory(root);
                using (var probe = File.Create(Path.Combine(root, ".installer-write-" + Guid.NewGuid().ToString("N")), 1, FileOptions.DeleteOnClose)) { }
            }
            if (page == 1 && !preserve.Checked)
            {
                if (String.IsNullOrWhiteSpace(model.Text) || model.Text.Length > 256 || model.Text.Any(Char.IsControl)) throw new Exception("请填写有效的模型名称。");
                if (profile.SelectedIndex < 2 && !System.Text.RegularExpressions.Regex.IsMatch(model.Text.Trim(), @"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")) throw new Exception("本地模型名称包含无效字符。");
                Uri address;
                if (profile.SelectedIndex == 2 && (!Uri.TryCreate(url.Text.Trim(), UriKind.Absolute, out address) || (address.Scheme != "https" && address.Scheme != "http") || address.UserInfo != "" || address.Query != "" || address.Fragment != "")) throw new Exception("请填写有效的 http/https API 地址，密钥请填在密钥栏。");
            }
            if (page < 2) { page++; ShowPage(); return; }
            if (page > 2) { await Install(); return; }
            await Install();
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "请检查安装信息", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    private void Log(string line)
    {
        if (String.IsNullOrEmpty(line)) return;
        if (!String.IsNullOrEmpty(secret)) line = line.Replace(secret, "[密钥已隐藏]");
        lock (logLock) { if (logPath != null) File.AppendAllText(logPath, DateTime.Now.ToString("HH:mm:ss ") + line + Environment.NewLine, new UTF8Encoding(false)); }
        string safe = line;
        if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)delegate {
            if (safe.StartsWith("JARVIS_STEP|"))
            {
                string[] parts = safe.Split(new[] { '|' }, 3); int number;
                if (parts.Length == 3 && Int32.TryParse(parts[1], out number)) {
                    stages.Items.Clear(); for (int i=0;i<steps.Length;i++) stages.Items.Add((i+1 < number ? "✓  " : i+1 == number ? "→  " : "○  ") + (i+1) + ". " + steps[i]);
                    status.Text = parts[2];
                }
            }
            else { output.AppendText(safe.Replace("JARVIS_ERROR|", "") + Environment.NewLine); if (output.TextLength > 18000) output.Text = output.Text.Substring(output.TextLength - 12000); output.SelectionStart = output.TextLength; output.ScrollToCaret(); }
        });
    }
    private void CopyPackage()
    {
        if (String.Equals(source, root, StringComparison.OrdinalIgnoreCase)) return;
        var manifest = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(source, "package-manifest.json"), Encoding.UTF8));
        foreach (Dictionary<string, object> file in (System.Collections.IEnumerable)manifest["files"])
        {
            string relative = (string)file["path"];
            string from = Path.GetFullPath(Path.Combine(source, relative)), to = Path.GetFullPath(Path.Combine(root, relative));
            if (!from.StartsWith(source + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || !to.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("安装包清单包含无效路径。");
            Directory.CreateDirectory(Path.GetDirectoryName(to)); File.Copy(from, to, true);
        }
        File.Copy(Path.Combine(source, "package-manifest.json"), Path.Combine(root, "package-manifest.json"), true);
    }
    private async Task Install()
    {
        running = true; cancelled = false; Completed = false; secret = key.Text;
        page = 3; ShowPage(); progress.Style = ProgressBarStyle.Marquee; output.Clear();
        stages.Items.Clear(); for (int i=0;i<steps.Length;i++) stages.Items.Add("○  " + (i+1) + ". " + steps[i]);
        started = DateTime.Now; timer.Start();
        try
        {
            await Task.Run((Action)CopyPackage);
            Directory.CreateDirectory(Path.Combine(root, "logs")); logPath = Path.Combine(root, "logs", "installer-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log");
            var request = new Dictionary<string, object> { {"profile", new[] {"lite","custom-local","api"}[profile.SelectedIndex]}, {"model",model.Text.Trim()}, {"url",url.Text.Trim()}, {"key",key.Text}, {"voice",new[] {"text","zh","zh-female","en"}[voice.SelectedIndex]}, {"preserve",preserve.Checked}, {"shortcut",shortcut.Checked}, {"channel",channel.SelectedIndex==0?"gitee":"github"}, {"full_features", true} };
            var info = new ProcessStartInfo("powershell.exe", "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(Path.Combine(root,"install-worker.ps1")) + " -Root " + Quote(root)) { WorkingDirectory=root, UseShellExecute=false, CreateNoWindow=true, RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true, StandardOutputEncoding=new UTF8Encoding(false), StandardErrorEncoding=new UTF8Encoding(false) };
            worker = new Process { StartInfo=info };
            worker.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log(e.Data); };
            worker.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log(e.Data); };
            worker.Start(); worker.BeginOutputReadLine(); worker.BeginErrorReadLine();
            // UTF-8 bytes on stdin keep Chinese paths and secrets out of process arguments.
            byte[] bytes = Encoding.UTF8.GetBytes(json.Serialize(request)); worker.StandardInput.BaseStream.Write(bytes,0,bytes.Length); worker.StandardInput.Close();
            await Task.Run((Action)worker.WaitForExit);
            Completed = worker.ExitCode == 0 && !cancelled;
            if (!Completed) { Log(cancelled ? "已取消安装。完成的下载会保留，可以重试。" : "安装未完成，请查看上方具体原因。可点击上一步修改方案，或重试安装。"); }
            else if (shortcut.Checked) CreateShortcut();
        }
        catch (Exception ex) { Log("安装未完成：" + ex.Message + "。请确认目录可写，且其他 JARVIS 窗口已关闭。"); }
        finally { if (worker != null) { worker.Dispose(); worker = null; } running=false; timer.Stop(); progress.Style=ProgressBarStyle.Blocks; progress.Value=Completed ? 100 : 0; elapsed.Text="已用时 " + (DateTime.Now-started).ToString(@"hh\:mm\:ss"); ShowPage(); }
        if (Completed && startAfter.Checked && !noLaunch) Launch();
    }
    private void CreateShortcut()
    {
        try {
            // Late-bound COM avoids shipping extra assemblies.
            Type shellType = Type.GetTypeFromProgID("WScript.Shell"); object shell = Activator.CreateInstance(shellType);
            object link = shellType.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, shell, new object[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"JARVIS.lnk") });
            Type linkType=link.GetType();
            linkType.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, link,new object[] {Path.Combine(root,"JARVIS.exe")});
            linkType.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty,null,link,new object[] {root});
            linkType.InvokeMember("Save",System.Reflection.BindingFlags.InvokeMethod,null,link,null);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link); System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
        } catch { Log("安装已完成。桌面快捷方式未能创建，请在安装目录双击 JARVIS.exe。"); }
    }
    private void Launch() { try { Process.Start(new ProcessStartInfo(Path.Combine(root,"JARVIS.exe")) {WorkingDirectory=root,UseShellExecute=true}); Close(); } catch(Exception ex) { MessageBox.Show(this,"无法启动：" + ex.Message,"JARVIS"); } }
    private void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (!running) return;
        e.Cancel=true;
        if (worker == null) { MessageBox.Show(this,"正在准备文件，请稍候再取消。","JARVIS"); return; }
        if (MessageBox.Show(this,"取消当前安装？已完成的下载会保留，下次可以重试。","取消安装",MessageBoxButtons.YesNo,MessageBoxIcon.Question) != DialogResult.Yes) return;
        cancelled=true;
        try { using(var kill=Process.Start(new ProcessStartInfo("taskkill.exe","/PID " + worker.Id + " /T /F") {UseShellExecute=false,CreateNoWindow=true})) kill.WaitForExit(); } catch { }
    }
    protected override void Dispose(bool disposing) { if(disposing) { timer.Dispose(); } base.Dispose(disposing); }
}
