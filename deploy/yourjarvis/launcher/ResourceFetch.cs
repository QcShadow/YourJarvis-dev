using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

// Runs before Python exists. The bundled, immutable manifest pins every byte.
internal static class ResourceFetch
{
    private static string Hash(string file) { using (var s=File.OpenRead(file)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant(); }
    private static string Under(string root, string relative) {
        if(Path.IsPathRooted(relative)) throw new Exception("资源路径无效。");
        foreach(string segment in relative.Split('/','\\')) if(segment==".." || segment==".") throw new Exception("资源路径无效。");
        string path=Path.GetFullPath(Path.Combine(root,relative));
        if (!path.StartsWith(Path.GetFullPath(root).TrimEnd('\\')+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("资源路径无效。");
        for(string current=path;current!=null;current=Path.GetDirectoryName(current)) {
            if((File.Exists(current)||Directory.Exists(current)) && (File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0) throw new Exception("资源目录包含链接，请使用独立安装目录。");
            if(current.Equals(Path.GetFullPath(root).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase))break;
        }
        return path;
    }
    private static bool Valid(string file, Dictionary<string,object> item) {
        return File.Exists(file) && new FileInfo(file).Length==Convert.ToInt64(item["bytes"]) && Hash(file)==(string)item["sha256"];
    }
    private static async Task Fetch(string folder, Dictionary<string,object> item, IList<string> bases) {
        string name=(string)item["name"], target=Under(folder,name), partial=target+".part";
        if(Valid(target,item)) { Console.WriteLine("复用已校验资源："+name); return; }
        long length=Convert.ToInt64(item["bytes"]);
        if(File.Exists(partial) && new FileInfo(partial).Length==length) {
            if(Hash(partial)==(string)item["sha256"]) { File.Copy(partial,target,true); File.Delete(partial); return; }
            File.Delete(partial);
        }
        var urls=new List<string>();
        if(item.ContainsKey("urls")) foreach(var value in (IEnumerable)item["urls"]) urls.Add((string)value);
        else foreach(string baseUrl in bases) urls.Add(baseUrl.TrimEnd('/')+"/"+Uri.EscapeDataString(name));
        foreach(string url in urls) for(int attempt=0;attempt<2;attempt++) {
            try {
                var uri=new Uri(url);
                if(uri.Scheme!="https" && !uri.IsLoopback) throw new Exception("资源下载只支持 HTTPS。");
                Console.WriteLine("下载来源："+uri.Host+" · "+name+"（支持断点续传）");
                using(var client=new HttpClient { Timeout=TimeSpan.FromSeconds(40) })
                using(var request=new HttpRequestMessage(HttpMethod.Get,uri)) {
                    long offset=File.Exists(partial)?new FileInfo(partial).Length:0;
                    if(offset>length) { File.Delete(partial); offset=0; }
                    if(offset>0) request.Headers.Range=new RangeHeaderValue(offset,null);
                    using(var response=await client.SendAsync(request,HttpCompletionOption.ResponseHeadersRead)) {
                        response.EnsureSuccessStatusCode();
                        bool append=response.StatusCode==HttpStatusCode.PartialContent && offset>0;
                        if(append && (response.Content.Headers.ContentRange==null || response.Content.Headers.ContentRange.From!=offset)) throw new Exception("续传响应无效。");
                        if(!append) offset=0;
                        using(var input=await response.Content.ReadAsStreamAsync())
                        using(var output=new FileStream(partial,append?FileMode.Append:FileMode.Create,FileAccess.Write,FileShare.Read)) {
                            var buffer=new byte[128*1024]; var last=DateTime.MinValue;
                            while(true) {
                                var read=input.ReadAsync(buffer,0,buffer.Length);
                                if(await Task.WhenAny(read,Task.Delay(30000))!=read) throw new TimeoutException("下载连续 30 秒没有数据，切换来源。");
                                int count=await read; if(count==0) break;
                                if(offset+count>length) throw new Exception("资源大小超出清单。");
                                await output.WriteAsync(buffer,0,count); offset+=count;
                                if((DateTime.Now-last).TotalSeconds>=2) { Console.WriteLine("下载进度："+name+" "+(offset*100/length)+"% · "+(offset/1048576)+" / "+(length/1048576)+" MB"); last=DateTime.Now; }
                            }
                        }
                    }
                }
                if(new FileInfo(partial).Length!=length) throw new Exception("下载未完成，将从断点继续。");
                if(Hash(partial)!=(string)item["sha256"]) { File.Delete(partial); throw new Exception("资源校验失败，重新下载。"); }
                File.Copy(partial,target,true); File.Delete(partial); return;
            } catch(Exception ex) { Console.WriteLine("当前来源失败："+ex.Message+"；准备重试或切换来源。"); }
        }
        throw new Exception("资源下载失败："+name+"。请重试，已下载部分会保留。也可把发布页同名资源放入 cache\\downloads 后重试。");
    }
    internal static void Extract(string file,string root) {
        using(var zip=ZipFile.OpenRead(file)) foreach(var entry in zip.Entries) {
            string target=Under(root,entry.FullName);
            if(entry.FullName.EndsWith("/")) { Directory.CreateDirectory(target); continue; }
            // Packs must never contain user state. This also guards malformed archives.
            string rel=entry.FullName.Replace('\\','/');
            if(!(rel.StartsWith("src/.venv/",StringComparison.Ordinal) || rel.StartsWith("runtimes/",StringComparison.Ordinal) || rel.StartsWith("models/",StringComparison.Ordinal) || rel.StartsWith("cache/huggingface/",StringComparison.Ordinal) || rel.StartsWith("cache/installers/",StringComparison.Ordinal))) throw new Exception("资源包包含不允许覆盖的文件。");
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            using(var input=entry.Open()) using(var output=File.Create(target)) input.CopyTo(output);
        }
    }
    private static void Relocate(string root,string home) {
        string environment=Path.Combine(root,"src", ".venv"); if(!Directory.Exists(environment)) return;
        // uv's Windows redirector embeds the builder's absolute Python path.
        // Use CPython's relocatable venv redirectors, which consult pyvenv.cfg.
        string pythonHome=Path.GetFullPath(Path.Combine(root,home));
        foreach(string name in new[]{"python.exe","pythonw.exe"}) {
            string launcher=Path.Combine(pythonHome,"Lib","venv","scripts","nt",name);
            if(!File.Exists(launcher)) throw new Exception("Python 资源缺少可迁移启动器，请重新下载 Python 资源。");
            Directory.CreateDirectory(Path.Combine(environment,"Scripts"));
            File.Copy(launcher,Path.Combine(environment,"Scripts",name),true);
        }
        File.WriteAllText(Path.Combine(environment,"pyvenv.cfg"),"home = "+Path.Combine(root,home)+"\r\nimplementation = CPython\r\nversion_info = 3.12.14\r\ninclude-system-site-packages = false\r\n",new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(environment,"Lib","site-packages","_editable_impl_openjarvis.pth"),Path.Combine(root,"src","src")+Environment.NewLine,new UTF8Encoding(false));
    }
    private static async Task Install(string root,string manifestPath,string packName,string channel) {
        var json=new JavaScriptSerializer { MaxJsonLength=16*1024*1024 };
        var manifest=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(manifestPath,Encoding.UTF8));
        var packs=(Dictionary<string,object>)manifest["packs"];
        if(!packs.ContainsKey(packName)) throw new Exception("这个版本尚未提供资源包："+packName);
        var pack=(Dictionary<string,object>)packs[packName];
        var bases=new List<string>(); foreach(var value in (IEnumerable)(pack.ContainsKey("baseUrls")?pack["baseUrls"]:manifest["baseUrls"])) bases.Add((string)value);
        if(channel=="github") bases.Reverse();
        string folder=Path.Combine(root,"cache","downloads"); Directory.CreateDirectory(folder);
        if(pack.ContainsKey("files")) {
            foreach(var value in (IEnumerable)pack["files"]) {
                var file=(Dictionary<string,object>)value;
                string relative=Convert.ToString(file["path"]).Replace('\\','/');
                if(!relative.StartsWith("models/",StringComparison.Ordinal)) throw new Exception("模型下载路径无效。");
                string destination=Under(root,relative);
                if(Valid(destination,file)) continue;
                await Fetch(folder,file,bases);
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                string staging=destination+".installing";
                File.Copy(Under(folder,(string)file["name"]),staging,true);
                if(File.Exists(destination)) File.Delete(destination);
                File.Move(staging,destination);
            }
            Console.WriteLine("模型资源准备完成："+packName); return;
        }
        var parts=new List<Dictionary<string,object>>(); foreach(var part in (IEnumerable)pack["parts"]) parts.Add((Dictionary<string,object>)part);
        foreach(var part in parts) await Fetch(folder,part,bases);
        string archive=Path.Combine(folder,packName+".zip");
        if(!Valid(archive,pack)) using(var output=File.Create(archive)) foreach(var part in parts) using(var input=File.OpenRead(Under(folder,(string)part["name"]))) input.CopyTo(output);
        if(!Valid(archive,pack)) throw new Exception("资源包完整校验失败。");
        Console.WriteLine("资源校验通过，正在安装："+packName);
        Extract(archive,root); Relocate(root,(string)manifest["pythonHome"]);
        Console.WriteLine("资源准备完成："+packName);
    }
    private static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false); ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
        try { if(args.Length<3) throw new Exception("需要安装目录、清单和资源名称。"); Install(Path.GetFullPath(args[0]),args[1],args[2],args.Length>3?args[3]:"gitee").GetAwaiter().GetResult(); return 0; }
        catch(Exception ex) { Console.WriteLine("JARVIS_ERROR|"+ex.Message); return 1; }
    }
}
