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
        // Automated extraction exercises the identical path used by the UI.
        if(args.Length==2 && args[0]=="--extract-only") { try { Extract(args[1],delegate(int value){}); } catch(Exception e) { Console.Error.WriteLine(e.Message); Environment.ExitCode=1; } return; }
        Application.Run(new SetupWindow());
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
                if(relative=="config.toml" || relative=="credentials.toml" || relative.StartsWith("data/") || relative.StartsWith("models/")) throw new Exception("程序包不能覆盖个人数据。");
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
    internal SetupWindow() {
        Text="JARVIS 0.1.3 安装"; Font=new Font("Microsoft YaHei UI",10); ClientSize=new Size(680,320); AutoScaleMode=AutoScaleMode.Dpi; StartPosition=FormStartPosition.CenterScreen; MaximizeBox=false;
        var title=new Label {Text="安装或升级 JARVIS",Left=24,Top=24,Width=620,Height=44,Font=new Font(Font.FontFamily,21,FontStyle.Bold)};
        var hint=new Label {Text="选择安装位置后，自动准备程序并打开中文安装向导。\r\n升级请选原来的 JARVIS-Share 文件夹，现有配置和数据会保留。",Left=26,Top=86,Width=624,Height=60};
        folder.SetBounds(26,158,490,30); folder.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"JARVIS");
        var browse=new Button {Text="选择目录…",Left=528,Top=156,Width=126,Height=34}; browse.Click+=delegate {using(var picker=new FolderBrowserDialog {SelectedPath=folder.Text}) if(picker.ShowDialog(this)==DialogResult.OK) folder.Text=picker.SelectedPath;};
        status.SetBounds(26,204,620,32); bar.SetBounds(26,242,452,24); next.SetBounds(502,236,152,40); next.Text="继续安装";
        Controls.AddRange(new Control[]{title,hint,folder,browse,status,bar,next});
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
}
