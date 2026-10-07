using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// Both optional speech installation and removal stay local to one installation.
internal static class MaintenanceProgram {
    [STAThread] private static void Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        bool uninstall=Path.GetFileName(Application.ExecutablePath).Contains("Uninstall");
        bool finish=args.Length==3 && args[0]=="--finish";
        if(finish) {root=Path.GetFullPath(args[1]).TrimEnd('\\');uninstall=true;}
        try {
            ValidateRoot(root,uninstall);
            var selected=args.Length==2 && args[0]=="--speech" ? args[1].Split(',') : new string[0];
            using(var form=new MaintenanceWindow(root,uninstall,selected,finish,finish && args[2]=="delete-data")) {
                Application.Run(form); Environment.ExitCode=form.Completed?0:1;
            }
        } catch(Exception ex) {MessageBox.Show(ex.Message,"JARVIS",MessageBoxButtons.OK,MessageBoxIcon.Error);Environment.ExitCode=1;}
    }
    internal static void ValidateRoot(string root,bool uninstall) {
        if(root==Path.GetPathRoot(root).TrimEnd('\\') || !File.Exists(Path.Combine(root,"package-manifest.json")) || !File.Exists(Path.Combine(root,"app-version.json"))) throw new Exception("请选择完整的 JARVIS 安装目录。");
        if(uninstall && (Directory.Exists(Path.Combine(root,"src",".git")) || File.Exists(Path.Combine(root,"src",".git")) || Directory.Exists(Path.Combine(root,".git")) || File.Exists(Path.Combine(root,".git")) || File.Exists(Path.Combine(root,"development-runtime.json")))) throw new Exception("此卸载向导仅用于朋友版安装目录，不能卸载开发仓库或共享运行环境。");
        for(var dir=new DirectoryInfo(root);dir!=null;dir=dir.Parent) if((dir.Attributes & FileAttributes.ReparsePoint)!=0) throw new Exception("安装目录包含链接路径，无法安全执行维护。");
    }
    internal static string Under(string root,string relative) {
        if(Path.IsPathRooted(relative) || relative.Split('/','\\').Any(p=>p==".." || p==".")) throw new Exception("安装清单路径无效。");
        string path=Path.GetFullPath(Path.Combine(root,relative));
        if(!path.StartsWith(root+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("安装清单路径超出安装目录。");
        string current=path;
        while(current!=root) {
            if((File.Exists(current)||Directory.Exists(current)) && (File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0) throw new Exception("检测到链接，已停止移除："+current);
            current=Path.GetDirectoryName(current);
        }
        return path;
    }
    internal static async Task StopOwned(string root) {
        // A portable runtime is private to this install. Never select by name alone.
        foreach(var process in Process.GetProcesses()) using(process) {
            try {
                if(process.Id==Process.GetCurrentProcess().Id) continue;
                string path=process.MainModule.FileName;
                bool owned=path.Equals(Path.Combine(root,"JARVIS.exe"),StringComparison.OrdinalIgnoreCase)
                    || path.Equals(Path.Combine(root,"JARVIS-Desktop.exe"),StringComparison.OrdinalIgnoreCase)
                    || path.StartsWith(root+"\\src\\.venv\\",StringComparison.OrdinalIgnoreCase)
                    || path.StartsWith(root+"\\runtimes\\",StringComparison.OrdinalIgnoreCase);
                if(owned) {process.Kill();await Task.Run((Action)(()=>process.WaitForExit(10000)));}
            } catch(System.ComponentModel.Win32Exception) {} catch(InvalidOperationException) {}
        }
    }
    internal static void RemoveTree(string path) {
        // Do not recurse through junctions, even if they were introduced after review.
        if((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) throw new Exception("不能删除链接目录："+path);
        foreach(string child in Directory.GetDirectories(path)) RemoveTree(child);
        foreach(string file in Directory.GetFiles(path)) {
            if((File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0) throw new Exception("不能删除链接文件："+file);
            File.SetAttributes(file,FileAttributes.Normal);File.Delete(file);
        }
        Directory.Delete(path);
    }
    internal static void CheckTree(string root,string path) {
        Under(root,path.Substring(root.Length+1));
        foreach(string entry in Directory.GetFileSystemEntries(path)) {
            Under(root,entry.Substring(root.Length+1));
            if(Directory.Exists(entry))CheckTree(root,entry);
        }
    }
    internal static async Task Uninstall(string root,bool deleteData,Action<string> log) {
        ValidateRoot(root,true);
        var manifest=new JavaScriptSerializer {MaxJsonLength=16*1024*1024}.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(root,"package-manifest.json"),Encoding.UTF8));
        var targets=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var value in (System.Collections.IEnumerable)manifest["files"]) {
            string relative=Convert.ToString(((Dictionary<string,object>)value)["path"]);
            // These categories are state, even if a legacy package declared them.
            if(relative.StartsWith("data/") || relative=="config.toml" || relative=="credentials.toml") continue;
            targets.Add(Under(root,relative));
        }
        string[] trees=deleteData ? new[]{"src", "runtimes", "models", "cache", "data", "logs", "tools", "learning", "skills", "skill-cache", "skill-index", "operators", "templates", "prompts", "digests", "workspace", "runtime", "claude_code_runner"} : new[]{"src", "runtimes", "models", "cache", "tools"};
        if(deleteData) {
            foreach(string name in new[]{"config.toml","credentials.toml","cloud-keys.env","voice-preferences.json","USER.md","MEMORY.md","SOUL.md","memory_facts.jsonl","anon_id",".vault_key"}) targets.Add(Under(root,name));
            foreach(string name in new[]{"memory.db","telemetry.db","traces.db","audit.db","sessions.db","optimize.db","agents.db","digest.db","approvals.db","knowledge.db","work-jobs.sqlite3"})
                foreach(string suffix in new[]{"","-wal","-shm","-journal"}) targets.Add(Under(root,name+suffix));
            foreach(string path in Directory.GetFiles(root,"config.before-setup-*.toml")) targets.Add(Under(root,Path.GetFileName(path)));
        }
        // Preflight every path before stopping the app or removing the first file.
        foreach(string tree in trees) {
            string path=Under(root,tree);
            if(Directory.Exists(path))CheckTree(root,path);
        }
        log("停止此安装目录的桌面和后台服务…");await StopOwned(root);
        foreach(string tree in trees) {string path=Under(root,tree);if(Directory.Exists(path)) {log("移除 "+tree);RemoveTree(path);}}
        foreach(string target in targets) if(File.Exists(target)) File.Delete(target);
        foreach(string file in new[]{"package-manifest.json","install-complete.json",".installer.lock","speech-install-result.json"}) {string path=Under(root,file);if(File.Exists(path))File.Delete(path);}
        // Remove only shortcuts pointing to this exact installation.
        try {
            var type=Type.GetTypeFromProgID("WScript.Shell");var shell=Activator.CreateInstance(type);
            foreach(string name in new[]{"JARVIS.lnk","卸载 JARVIS.lnk"}) {
                foreach(string location in new[]{root,Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory)}) {
                    string path=Path.Combine(location,name);
                    if(!File.Exists(path))continue;
                    var link=type.InvokeMember("CreateShortcut",System.Reflection.BindingFlags.InvokeMethod,null,shell,new object[]{path});
                    string target=Convert.ToString(link.GetType().InvokeMember("TargetPath",System.Reflection.BindingFlags.GetProperty,null,link,null));
                    if(target.StartsWith(root+"\\",StringComparison.OrdinalIgnoreCase))File.Delete(path);
                }
            }
        } catch {log("快捷方式清理未完成，可手动删除快捷方式。");}
        // Unknown user files are always retained. Remove root only when empty.
        foreach(string dir in Directory.GetDirectories(root)) if(!Directory.EnumerateFileSystemEntries(dir).Any()) Directory.Delete(dir);
        if(!Directory.EnumerateFileSystemEntries(root).Any())Directory.Delete(root);
    }
}

internal sealed class MaintenanceWindow : Form {
    readonly string root; readonly bool uninstall,finish; bool running;
    readonly Button action=new Button();readonly CheckBox deleteData=new CheckBox();
    readonly CheckedListBox choices=new CheckedListBox();readonly TextBox output=new TextBox();
    readonly ProgressBar progress=new ProgressBar();readonly Label status=new Label();
    readonly string[] keys={"asr-zh","asr-en","tts","piper","clone"};
    public bool Completed {get;private set;}
    public MaintenanceWindow(string installation,bool remove,string[] selected,bool worker,bool delete) {
        root=installation;uninstall=remove;finish=worker;
        Text=remove?"JARVIS · 卸载向导":"JARVIS · 语音资源";
        Font=new Font("Microsoft YaHei UI",10);AutoScaleMode=AutoScaleMode.Dpi;ClientSize=new Size(760,620);MinimumSize=Size;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;BackColor=Color.FromArgb(244,247,252);
        var title=new Label{Text=remove?"卸载 JARVIS":"让 JARVIS 听见你，也回应你",Left=30,Top=24,Width=700,Height=48,Font=new Font(Font.FontFamily,22,FontStyle.Bold),ForeColor=Color.FromArgb(24,47,74)};
        var info=new Label{Left=32,Top=82,Width=696,Height=110,Text=remove?"安装位置："+root+"\r\n\r\n将移除程序、已下载模型、运行环境和下载缓存。共享的系统 WebView2 会保留。未识别的其他文件会保留。":"按需选择语音输入、播报或录音创建音色。下载可断点续传，完成后自动重新打开主界面。\r\n录音创建音色约需 3 GB 下载及 8 GB 磁盘空间，建议 16 GB 内存；CPU 首次生成可能需要数分钟。"};
        choices.SetBounds(32,194,696,158);choices.BorderStyle=BorderStyle.None;choices.BackColor=Color.White;choices.CheckOnClick=true;
        string[] names={"中文语音输入 · SenseVoice","英文语音输入 · Whisper","语音播报 · Kokoro 中英文音色","Piper · 导入 ONNX 模型的运行引擎","录音创建音色 · Qwen3-TTS 本地模型"};
        for(int i=0;i<keys.Length;i++)choices.Items.Add(names[i],selected.Contains(keys[i]));
        deleteData.SetBounds(32,202,696,56);deleteData.Text="同时删除配置、API 密钥、聊天记录、长期记忆、个人音色及日志";deleteData.Checked=delete;deleteData.Visible=remove;
        choices.Visible=!remove;
        status.SetBounds(32,368,696,40);status.Text=remove?"默认保留个人数据，以后可重新安装使用。":"请选择要安装的语音资源。";
        progress.SetBounds(32,416,696,12);progress.Visible=false;progress.Style=ProgressBarStyle.Marquee;
        output.SetBounds(32,444,696,100);output.Multiline=true;output.ReadOnly=true;output.ScrollBars=ScrollBars.Vertical;output.BorderStyle=BorderStyle.None;output.BackColor=Color.White;
        action.SetBounds(526,566,202,36);action.Text=remove?"开始卸载":"下载并安装";action.FlatStyle=FlatStyle.Flat;action.FlatAppearance.BorderSize=0;action.BackColor=Color.FromArgb(29,87,191);action.ForeColor=Color.White;
        Controls.AddRange(new Control[]{title,info,choices,deleteData,status,progress,output,action});
        action.Click+=async delegate {if(Completed){Close();return;}await Run();};
        FormClosing+=delegate(object sender,FormClosingEventArgs e){if(running){e.Cancel=true;MessageBox.Show("正在执行维护，请等待完成。下载失败后可重试，断点会保留。", "JARVIS");}};
        if(finish)Shown+=async delegate{await Run();};
    }
    void Log(string text) {if(IsDisposed)return;if(InvokeRequired){BeginInvoke((Action)(()=>Log(text)));return;}output.AppendText(text+Environment.NewLine);output.SelectionStart=output.TextLength;output.ScrollToCaret();}
    async Task Run() {
        if(running)return;
        var selected=choices.CheckedIndices.Cast<int>().Select(i=>keys[i]).ToArray();
        if(!uninstall && selected.Length==0){status.Text="请至少选择一项。";return;}
        if(uninstall && !finish) {
            if(MessageBox.Show("确认卸载此目录的 JARVIS？\r\n"+root+"\r\n"+(deleteData.Checked?"个人数据也将永久删除。":"个人配置、聊天、记忆和音色将保留。"),"确认卸载",MessageBoxButtons.YesNo,MessageBoxIcon.Warning)!=DialogResult.Yes)return;
            string temp=Path.Combine(Path.GetTempPath(),"Jarvis-Uninstall-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(temp);
            if(temp.StartsWith(root+"\\",StringComparison.OrdinalIgnoreCase)) {
                Directory.Delete(temp);
                temp=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Temp","Jarvis-Uninstall-"+Guid.NewGuid().ToString("N"));
                if(temp.StartsWith(root+"\\",StringComparison.OrdinalIgnoreCase))throw new Exception("临时目录位于安装目录中，无法安全卸载。");
                Directory.CreateDirectory(temp);
            }
            string exe=Path.Combine(temp,"JARVIS-Uninstall.exe");File.Copy(Application.ExecutablePath,exe);
            Process.Start(new ProcessStartInfo(exe,"--finish \""+root+"\" "+(deleteData.Checked?"delete-data":"preserve-data")){UseShellExecute=true});Completed=true;Close();return;
        }
        running=true;action.Enabled=false;choices.Enabled=false;deleteData.Enabled=false;progress.Visible=true;status.Text=uninstall?"正在卸载…":"正在下载并安装…";
        try {
            if(uninstall)await Task.Run(async()=>await MaintenanceProgram.Uninstall(root,deleteData.Checked,Log));
            else {
                var start=new ProcessStartInfo("powershell.exe","-NoLogo -NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,"install-speech.ps1")+"\" -Root \""+root+"\" -Choices \""+String.Join(",",selected)+"\""){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=new UTF8Encoding(false),StandardErrorEncoding=new UTF8Encoding(false),WorkingDirectory=root};
                using(var process=Process.Start(start)) {
                    process.OutputDataReceived+=delegate(object sender,DataReceivedEventArgs e){if(e.Data!=null)Log(e.Data);};process.ErrorDataReceived+=delegate(object sender,DataReceivedEventArgs e){if(e.Data!=null)Log(e.Data);};process.BeginOutputReadLine();process.BeginErrorReadLine();await Task.Run((Action)process.WaitForExit);
                    if(process.ExitCode!=0)throw new Exception("安装尚未完成，请查看以上日志后重试；已下载内容会保留。");
                }
            }
            Completed=true;action.Text="完成";status.Text=uninstall?(deleteData.Checked?"JARVIS 已卸载。未识别的其他文件已保留。":"JARVIS 已卸载，个人数据保留在原安装目录。"):"语音资源已安装，点击完成返回主界面。";
        } catch(Exception ex){status.Text="未完成："+ex.Message;Log(ex.Message);action.Text="重试";}
        finally{running=false;action.Enabled=true;progress.Visible=false;}
    }
}
