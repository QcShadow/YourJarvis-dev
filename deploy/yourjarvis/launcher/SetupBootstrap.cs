using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class SetupBootstrap {
    [STAThread] private static void Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length >= 3 && args[0] == "--update") {
            try { RunAutomaticUpdate(args[1], Int32.Parse(args[2])); }
            catch(Exception e) { MessageBox.Show("自动更新未完成：\n" + e.Message, "JARVIS 更新", MessageBoxButtons.OK, MessageBoxIcon.Error); Environment.ExitCode=1; }
            return;
        }
        // Automated extraction exercises the identical path used by the UI.
        if(args.Length==2 && args[0]=="--extract-only") { try { Extract(args[1],delegate(int value){}); } catch(Exception e) { Console.Error.WriteLine(e.Message); Environment.ExitCode=1; } return; }
        Application.Run(new SetupWindow());
    }
    private static void RunAutomaticUpdate(string destination, int parentPid) {
        destination = Path.GetFullPath(destination).TrimEnd('\\');
        try {
            using(var parent = Process.GetProcessById(parentPid)) {
                if(parent.Id != Process.GetCurrentProcess().Id && !parent.WaitForExit(120000))
                    throw new TimeoutException("正在等待 JARVIS 退出，超时后未执行覆盖。请关闭旧窗口后重试。");
            }
        } catch(ArgumentException) { }
        Extract(destination, delegate(int value){});
        string installer = Path.Combine(destination, "JARVIS-Install.exe");
        if(!File.Exists(installer)) throw new FileNotFoundException("更新包缺少安装向导。", installer);
        Process.Start(new ProcessStartInfo(installer, "--auto-update") {
            WorkingDirectory = destination, UseShellExecute = true,
        });
    }
    internal static void Extract(string destination,Action<int> progress) {
        destination=Path.GetFullPath(destination).TrimEnd('\\'); Directory.CreateDirectory(destination);
        using(var payload=Assembly.GetExecutingAssembly().GetManifestResourceStream("package.zip"))
        using(var zip=new ZipArchive(payload,ZipArchiveMode.Read)) {
            int done=0; foreach(var entry in zip.Entries) {
                string relative=entry.FullName.Replace('\\','/');
                if(!relative.StartsWith("JARVIS-Share/",StringComparison.Ordinal)) throw new Exception("安装包结构无效。");
                relative=relative.Substring("JARVIS-Share/".Length); if(relative.Length==0) continue;
                foreach(string segment in relative.Split('/')) if(segment==".." || segment==".") throw new Exception("安装包路径无效。");
                string target=Path.GetFullPath(Path.Combine(destination,relative));
                if(!target.StartsWith(destination+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("安装包路径无效。");
                if(entry.FullName.EndsWith("/")) { Directory.CreateDirectory(target); continue; }
                bool personal = relative=="config.toml" || relative=="credentials.toml" || relative.StartsWith("data/") || relative.StartsWith("models/");
                // Fresh installs need the bundled lightweight model. During an
                // upgrade, existing config/data/models are user state and must
                // survive untouched.
                if(personal && File.Exists(target)) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using(var input=entry.Open()) using(var output=File.Create(target)) input.CopyTo(output);
                progress(++done*100/zip.Entries.Count);
            }
        }
        // Remove only known obsolete entry files, never folders or user state.
        foreach(string obsolete in new[]{"bootstrap.cmd","bootstrap.ps1","download-speech.cmd","download-speech.ps1","scripts/download_speech_assets.py"}) {
            string file=Path.Combine(destination,obsolete); if(File.Exists(file)) File.Delete(file);
        }
    }
}
internal sealed class SetupWindow : Form {
    private readonly TextBox folder=new TextBox(); private readonly Button next=new Button(); private readonly ProgressBar bar=new ProgressBar(); private readonly Label status=new Label(); private bool busy;
    private readonly Color ink = Color.FromArgb(31, 43, 61), muted = Color.FromArgb(91, 106, 126), accent = Color.FromArgb(34, 111, 204);
    internal SetupWindow() {
        Text="JARVIS 0.1.5 安装"; Font=new Font("Microsoft YaHei UI",10); ClientSize=new Size(720,390); AutoScaleMode=AutoScaleMode.Dpi; StartPosition=FormStartPosition.CenterScreen; MaximizeBox=false; BackColor=Color.FromArgb(246,249,253);
        var header=new Panel {Left=0,Top=0,Width=720,Height=112,BackColor=Color.FromArgb(18,39,69)};
        var mark=new Label {Text="J",Left=28,Top=22,Width=52,Height=52,TextAlign=ContentAlignment.MiddleCenter,BackColor=accent,ForeColor=Color.White,Font=new Font(Font.FontFamily,26,FontStyle.Bold)};
        var title=new Label {Text="安装或升级 JARVIS",Left=94,Top=20,Width=580,Height=38,ForeColor=Color.White,Font=new Font(Font.FontFamily,21,FontStyle.Bold)};
        var subtitle=new Label {Text="一次准备好运行环境，升级时自动保留你的配置与数据",Left=96,Top=63,Width=580,Height=24,ForeColor=Color.FromArgb(198,215,235)};
        var card=new Panel {Left=24,Top=132,Width=672,Height=184,BackColor=Color.White};
        var hint=new Label {Text="选择安装位置后，向导会自动准备程序并打开中文安装界面。\r\n升级请选原来的安装文件夹，现有配置、记忆和模型会保留。",Left=22,Top=18,Width=620,Height=48,ForeColor=muted};
        folder.SetBounds(22,82,482,32); folder.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"JARVIS"); folder.BorderStyle=BorderStyle.FixedSingle;
        var browse=new Button {Text="选择目录…",Left=520,Top=79,Width=126,Height=38}; StyleButton(browse, false); browse.Click+=delegate {using(var picker=new FolderBrowserDialog {SelectedPath=folder.Text}) if(picker.ShowDialog(this)==DialogResult.OK) folder.Text=picker.SelectedPath;};
        status.SetBounds(24,326,390,28); status.ForeColor=muted; bar.SetBounds(24,360,430,8); bar.Style=ProgressBarStyle.Continuous; next.SetBounds(526,344,170,42); next.Text="继续安装"; StyleButton(next, true);
        card.Controls.AddRange(new Control[]{hint,folder,browse}); Controls.AddRange(new Control[]{header,mark,title,subtitle,card,status,bar,next});
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {if(busy) e.Cancel=true;};
        next.Click+=async delegate {
            try {
                string target=Path.GetFullPath(folder.Text.Trim()); if(target.TrimEnd('\\').Length<4) throw new Exception("请选择专用安装文件夹。");
                foreach(string name in new[]{"JARVIS","JARVIS-Desktop"}) foreach(var process in Process.GetProcessesByName(name)) { try {if(Path.GetDirectoryName(process.MainModule.FileName).Equals(target,StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("请先从托盘退出此目录的 JARVIS，再继续升级。");} catch(System.ComponentModel.Win32Exception){} }
                busy=true; next.Enabled=folder.Enabled=browse.Enabled=false; status.Text="正在准备程序文件…";
                var progress=new Progress<int>(value=>bar.Value=value);
                await Task.Run(()=>SetupBootstrap.Extract(target,value=>((IProgress<int>)progress).Report(value)));
                Process.Start(new ProcessStartInfo(Path.Combine(target,"JARVIS-Install.exe")){WorkingDirectory=target,UseShellExecute=true}); busy=false; Close();
            } catch(Exception ex) {busy=false;next.Enabled=folder.Enabled=browse.Enabled=true;status.Text="准备未完成，可以重试。";MessageBox.Show(this,ex.Message,"JARVIS 安装",MessageBoxButtons.OK,MessageBoxIcon.Warning);}
        };
    }
    private void StyleButton(Button button, bool primary) { button.FlatStyle=FlatStyle.Flat; button.FlatAppearance.BorderSize=primary?0:1; button.BackColor=primary?accent:Color.White; button.ForeColor=primary?Color.White:ink; button.Font=new Font(Font.FontFamily,10,FontStyle.Bold); button.Cursor=Cursors.Hand; }
}
