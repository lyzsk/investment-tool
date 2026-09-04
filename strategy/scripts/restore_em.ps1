Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
  [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
"@
$h = [W32]::FindWindow($null, "东方财富终端")
if ($h -ne [IntPtr]::Zero) { [W32]::ShowWindow($h, 9) | Out-Null; Write-Output "restored $h" } else { Write-Output "window not found" }
