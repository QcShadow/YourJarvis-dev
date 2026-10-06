using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

// Detached services receive only file-backed standard handles. They must never
// inherit the desktop's or installer's capture pipes through PowerShell.
internal static class JarvisSpawn {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct Startup { public int size; public string reserved, desktop, title; public int x,y,cx,cy,xchars,ychars,fill,flags; public short show,reserved2; public IntPtr reservedPtr,input,output,error; }
    [StructLayout(LayoutKind.Sequential)] private struct StartupEx { public Startup info; public IntPtr attributes; }
    [StructLayout(LayoutKind.Sequential)] private struct ProcessInfo { public IntPtr process,thread; public int pid,tid; }
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,int flags,ref IntPtr bytes);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,IntPtr attribute,IntPtr value,IntPtr bytes,IntPtr previous,IntPtr returned);
    [DllImport("kernel32.dll")] private static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool SetHandleInformation(IntPtr handle,int mask,int flags);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] private static extern IntPtr CreateFile(string path,uint access,uint share,IntPtr security,uint disposition,uint attributes,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] private static extern bool CreateProcess(string application,StringBuilder command,IntPtr processSecurity,IntPtr threadSecurity,bool inherit,uint flags,IntPtr environment,string directory,ref StartupEx startup,out ProcessInfo process);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    private static string Quote(string argument) {
        var text=new StringBuilder("\""); int slashes=0;
        foreach(char c in argument) {
            if(c=='\\') {slashes++;continue;}
            if(c=='"') text.Append('\\',slashes*2+1); else text.Append('\\',slashes);
            text.Append(c); slashes=0;
        }
        text.Append('\\',slashes*2); return text.Append('"').ToString();
    }
    private static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        IntPtr list=IntPtr.Zero,handles=IntPtr.Zero,input=IntPtr.Zero; bool initialized=false;
        try {
            if(args.Length<4) throw new Exception("需要目录、程序和日志路径。");
            using(var output=new FileStream(args[2],FileMode.Create,FileAccess.Write,FileShare.ReadWrite))
            using(var error=new FileStream(args[3],FileMode.Create,FileAccess.Write,FileShare.ReadWrite)) {
                input=CreateFile("NUL",0x80000000,3,IntPtr.Zero,3,0,IntPtr.Zero);
                if(input==new IntPtr(-1)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                IntPtr[] standard={input,output.SafeFileHandle.DangerousGetHandle(),error.SafeFileHandle.DangerousGetHandle()};
                foreach(var handle in standard) if(!SetHandleInformation(handle,1,1)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                IntPtr bytes=IntPtr.Zero; InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref bytes);
                list=Marshal.AllocHGlobal(bytes);
                if(!InitializeProcThreadAttributeList(list,1,0,ref bytes)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                initialized=true; handles=Marshal.AllocHGlobal(IntPtr.Size*standard.Length); Marshal.Copy(standard,0,handles,standard.Length);
                if(!UpdateProcThreadAttribute(list,0,new IntPtr(0x20002),handles,new IntPtr(IntPtr.Size*standard.Length),IntPtr.Zero,IntPtr.Zero)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                var startup=new StartupEx {attributes=list, info=new Startup {size=Marshal.SizeOf(typeof(StartupEx)),flags=0x100,input=standard[0],output=standard[1],error=standard[2]}};
                var command=new StringBuilder(Quote(args[1])); for(int i=4;i<args.Length;i++) command.Append(' ').Append(Quote(args[i]));
                ProcessInfo process;
                if(!CreateProcess(args[1],command,IntPtr.Zero,IntPtr.Zero,true,0x08080000,IntPtr.Zero,args[0],ref startup,out process)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                CloseHandle(process.process); CloseHandle(process.thread);
                Console.WriteLine(new JavaScriptSerializer().Serialize(new {pid=process.pid}));
            }
            return 0;
        } catch(Exception error) {Console.Error.WriteLine("后台进程启动失败："+error.Message);return 1;}
        finally {if(initialized) DeleteProcThreadAttributeList(list); if(list!=IntPtr.Zero) Marshal.FreeHGlobal(list);if(handles!=IntPtr.Zero) Marshal.FreeHGlobal(handles);if(input!=IntPtr.Zero && input!=new IntPtr(-1)) CloseHandle(input);}
    }
}
