using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("AI好友")]
[assembly: AssemblyProduct("AI好友")]
[assembly: AssemblyDescription("AI好友本地启动器")]
[assembly: AssemblyVersion("0.4.0.0")]
internal static class Launcher {
    [STAThread]
    private static void Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string action = args.Length > 0 && args[0] == "--maintenance" ? "Maintain" :
                args.Length > 0 && args[0] == "--background" ? "Background" : "Start";
            string script = Path.Combine(root, "installer", "launch.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException("找不到启动文件，请保留 runtime 文件夹并联系维护者修复。");
            string shell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            var start = new ProcessStartInfo(shell, "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\" -Action " + action);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WorkingDirectory = root;
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show(error.Message, "AI好友", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
