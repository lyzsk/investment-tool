# em.ps1 — 东财终端只读快照·统一入口(hermes / Claude 调用)
#
# 用途: 读取本机已登录的东方财富终端(进程 mainfree, 交易窗口标题"东方财富证券"),
#       输出窗口截图 PNG, 供 AI 读图得到 资金/持仓/当日成交 等实时账户信息。
#
# 用法(在 scripts/dfcf/ 下):
#   powershell -File em.ps1 -Action probe                # 找东财进程与交易窗口, 输出 JSON
#   powershell -File em.ps1 -Action read                 # 一条龙: 找窗口→截图资金持仓页→(原本隐藏则还原)→JSON
#   powershell -File em.ps1 -Action read -Page 当日成交 -RealClick   # 翻到指定页再截(资金持仓/当日成交/当日委托/历史成交/历史委托/资金流水/交割单)
#   powershell -File em.ps1 -Action snapshot -Name hold  # 只截图(不还原隐藏)
#   powershell -File em.ps1 -Action click -X 60 -Y 230   # 后台点击窗口客户区坐标(仅用于左侧菜单翻页!)
#   powershell -File em.ps1 -Action hide                 # 重新隐藏交易窗口
#
# 铁律(只读原则):
#   1. 绝不输入密码; 登录/重登是用户本人手动动作
#   2. click 只允许用于左侧菜单导航(持仓/当日成交/历史成交/交割单),
#      【买入】【卖出】【撤单】区及其确认按钮一律禁止点击
#   3. 不抢焦点: 默认全程 ShowWindow(SW_SHOWNA), 用户不在电脑前也能跑
#   4. 【用户指令 2026-09-19】用户在场时禁止运行本脚本! 截图必须先把窗口 SW_SHOWNA 显示出来,
#      窗口会在用户屏幕上闪现 —— 只有用户明确说"我不在/可以读"时才允许调用。
#
# !! 翻页的重要警告(2026-09-19 实测) !!
#   东财 DirectUI 忽略一切合成消息(PostMessage/SendMessage 的 WM_LBUTTON* 全部无效)。
#   -RealClick 注入真实鼠标事件(SendInput)是有效的(已在【查询】展开器上验证),
#   但会物理移动光标约 1 秒并把窗口激活到前台 → 仅限用户不在电脑前时使用。
#   不加 -RealClick 时 -Page 静默无效(只截当前页); 默认页就是【资金持仓】, 最常用, 不需要点击。
#   注意: 账号掉线状态下(页面值显示 "--")点击查询页/tab 无响应(服务端会话缺失, 非输入问题),
#   用户重新登录后 -Page -RealClick 翻页待复验。
#
# 已验证的技术事实(2026-09-19):
#   - 窗口被 SW_HIDE 后 PrintWindow 返回全黑 → 截图前必须 SW_SHOWNA 使其可见(不可见≠最小化)
#   - 固定尺寸窗口 SetWindowPos 无法改大小, MoveWindow 可以
#   - UIA 读不到控件文本(DirectUI 自绘) → 只能截图+读图/OCR
#   - 截图输出目录 snapshots/ 已加入 .gitignore(资产隐私)
param(
  [ValidateSet("probe","snapshot","click","hide","read")]
  [string]$Action = "read",
  [ValidateSet("","资金持仓","当日成交","当日委托","历史成交","历史委托","资金流水","交割单")]
  [string]$Page = "",                  # snapshot/read 时先翻到此页再截(需 -RealClick 才真正生效)
  [int]$X = 0,
  [int]$Y = 0,
  [string]$Name = "snap",
  [switch]$KeepShown,
  [switch]$RealClick                   # 用真实鼠标注入翻页(光标会物理移动, 仅无人值守时用)
)

$ErrorActionPreference = "Stop"
$OutDir = Join-Path $PSScriptRoot "snapshots"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Drawing;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class EM {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool repaint);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, out POINT p);
    public struct POINT { public int X, Y; }
    // 截图 PNG 坐标(含标题栏) → 客户区坐标(PostMessage 用) 的偏移量
    public static int[] ClientOrigin(IntPtr h) {
        POINT p; ClientToScreen(h, out p);
        RECT r; GetWindowRect(h, out r);
        return new int[]{ p.X - r.Left, p.Y - r.Top };
    }
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder sb, int max);
    // 交易主窗口特征: 子窗口类名带 "_DC" 后缀(CElementFrameWnd_DC/ContainerWnd_DC), 登录工具条窗口没有
    public static bool HasDcChild(IntPtr h) {
        bool found = false;
        EnumChildWindows(h, (w, l) => {
            var sb = new StringBuilder(64); GetClassName(w, sb, 64);
            if (sb.ToString().EndsWith("_DC")) { found = true; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
    [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr h, IntPtr dc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int w, int h);
    [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr dc);
    public struct RECT { public int Left, Top, Right, Bottom; }

    // ---- 真实鼠标注入(东财忽略 PostMessage/SendMessage 合成点击, 只能走 SendInput) ----
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] inputs, int cb);
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT { public uint type; public MOUSEINPUT mi; }
    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT { public int dx, dy, mouseData; public uint dwFlags, time; public IntPtr dwExtraInfo; }
    // 在窗口 PNG 坐标 (pngX,pngY) 处做一次真实左键单击; 光标去回, 点击前临时置顶(不激活)保证命中本窗口
    public static void RealClick(IntPtr h, int pngX, int pngY) {
        RECT r; GetWindowRect(h, out r);
        int sx = r.Left + pngX, sy = r.Top + pngY;
        POINT saved; GetCursorPos(out saved);
        SetWindowPos(h, new IntPtr(-1), 0, 0, 0, 0, 0x0013); // HWND_TOPMOST | NOMOVE|NOSIZE|NOACTIVATE
        SetCursorPos(sx, sy);
        System.Threading.Thread.Sleep(150);
        INPUT[] seq = new INPUT[2];
        seq[0].type = 0; seq[0].mi.dwFlags = 0x0002; // LEFTDOWN
        seq[1].type = 0; seq[1].mi.dwFlags = 0x0004; // LEFTUP
        SendInput(2, seq, Marshal.SizeOf(typeof(INPUT)));
        System.Threading.Thread.Sleep(120);
        SetCursorPos(saved.X, saved.Y);
        SetWindowPos(h, new IntPtr(-2), 0, 0, 0, 0, 0x0013); // HWND_NOTOPMOST
    }

    public static List<string> WinsOfPid(uint wantPid) {
        var list = new List<string>();
        EnumWindows((h, l) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == wantPid) {
                var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
                list.Add(h.ToInt64() + "|" + IsWindowVisible(h) + "|" + sb.ToString());
            }
            return true;
        }, IntPtr.Zero);
        return list;
    }
    public static string Capture(IntPtr h, string file) {
        RECT r; GetWindowRect(h, out r);
        int w = r.Right - r.Left, hh = r.Bottom - r.Top;
        IntPtr scr = GetDC(IntPtr.Zero);
        IntPtr mem = CreateCompatibleDC(scr);
        IntPtr bmp = CreateCompatibleBitmap(scr, w, hh);
        SelectObject(mem, bmp);
        bool ok = PrintWindow(h, mem, 2); // PW_RENDERFULLCONTENT
        using (var img = Image.FromHbitmap(bmp)) img.Save(file, System.Drawing.Imaging.ImageFormat.Png);
        DeleteObject(bmp); DeleteDC(mem); ReleaseDC(IntPtr.Zero, scr);
        return ok + "|" + w + "x" + hh;
    }
}
'@ -ReferencedAssemblies System.Drawing

function Find-TradeWindow {
    # 返回 @{Pid; Hwnd; Visible; Title} 或 $null
    # 注意: 标题"东方财富证券"的窗口有多个(登录工具条 vs 交易主窗口), 类名#32770/尺寸/子窗口数都无法区分,
    #       交易主窗口的子控件类名带 "_DC" 后缀(CElementFrameWnd_DC) → 以此识别
    $proc = Get-Process -Name "mainfree" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $proc) { return $null }
    foreach ($line in [EM]::WinsOfPid([uint32]$proc.Id)) {
        $p = $line -split "\|", 3
        if ($p[2] -match "东方财富证券") {
            $h = [IntPtr][long]$p[0]
            if ([EM]::HasDcChild($h)) {
                return @{ Pid = $proc.Id; Hwnd = $h; Visible = ($p[1] -eq "True"); Title = $p[2] }
            }
        }
    }
    return @{ Pid = $proc.Id; Hwnd = [IntPtr]::Zero; Visible = $false; Title = "(未找到交易主窗口, 可能未登录)" }
}

# 左侧"查询"菜单翻页坐标(按 1600x950 截图 PNG 上的像素位置校准, 2026-09-19)
# PNG 含标题栏, 而 PostMessage 用客户区坐标 → 点击前必须用 ClientOrigin 换算, 否则会点到上一行菜单
# 若东财改版布局变化需重新校准: 截一张 1600x950 全图读菜单位置
$PageXY = @{
  "资金持仓" = @(128,331); "当日成交" = @(128,379); "当日委托" = @(128,427)
  "历史成交" = @(128,475); "历史委托" = @(128,523); "资金流水" = @(128,571); "交割单" = @(128,620)
}

function Click-Menu {
    # PNG 坐标点击左侧菜单。东财忽略合成消息, -Real 时才真正生效(真实鼠标注入, 仅无人值守用)
    param([IntPtr]$Hwnd, [int]$PngX, [int]$PngY, [switch]$Real)
    if ($Real) {
        [EM]::RealClick($Hwnd, $PngX, $PngY)
    } else {
        $off = [EM]::ClientOrigin($Hwnd)
        $cx = $PngX - $off[0]; $cy = $PngY - $off[1]
        $lp = [IntPtr](($cy -shl 16) -bor ($cx -band 0xFFFF))
        [void][EM]::PostMessage($Hwnd, 0x0201, [IntPtr]1, $lp)   # WM_LBUTTONDOWN(实测被东财忽略, 留作无害默认)
        Start-Sleep -Milliseconds 60
        [void][EM]::PostMessage($Hwnd, 0x0202, [IntPtr]0, $lp)   # WM_LBUTTONUP
    }
    Start-Sleep -Milliseconds 800                                # 等页面切换+数据刷新
}

switch ($Action) {
    "probe" {
        $proc = Get-Process -Name "mainfree" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $proc) { @{ ok = $false; error = "mainfree 进程不存在(东财未启动)" } | ConvertTo-Json -Compress; break }
        $wins = @()
        foreach ($line in [EM]::WinsOfPid([uint32]$proc.Id)) {
            $p = $line -split "\|", 3
            $wins += @{ hwnd = [long]$p[0]; visible = ($p[1] -eq "True"); title = $p[2] }
        }
        $tw = Find-TradeWindow
        @{ ok = $true; pid = $proc.Id; tradeHwnd = $(if ($tw) { [long]$tw.Hwnd } else { 0 }); windows = $wins } | ConvertTo-Json -Compress -Depth 3
    }
    "snapshot" {
        $tw = Find-TradeWindow
        if (-not $tw -or $tw.Hwnd -eq [IntPtr]::Zero) { @{ ok = $false; error = "交易窗口未找到(东财未启动或未登录交易账号)" } | ConvertTo-Json -Compress; break }
        [void][EM]::ShowWindow($tw.Hwnd, 8)              # SW_SHOWNA: 可见但不抢焦点(隐藏窗口截图为黑, 必须先显示)
        [void][EM]::MoveWindow($tw.Hwnd, 50, 50, 1600, 950, $true)
        Start-Sleep -Milliseconds 400
        if ($Page -and $PageXY.ContainsKey($Page)) {
            Click-Menu $tw.Hwnd $PageXY[$Page][0] $PageXY[$Page][1] -Real:$RealClick
        }
        $tag = $(if ($Page) { $Page } else { $Name })
        $file = Join-Path $OutDir ("em_{0}_{1:yyyyMMdd_HHmmss}.png" -f $tag, (Get-Date))
        $cap = [EM]::Capture($tw.Hwnd, $file) -split "\|"
        if (-not $tw.Visible -and -not $KeepShown) { [void][EM]::ShowWindow($tw.Hwnd, 0) }  # 原本隐藏则还原
        @{ ok = ($cap[0] -eq "True"); file = $file; size = $cap[1]; pid = $tw.Pid; hwnd = [long]$tw.Hwnd;
           page = $Page; wasVisible = $tw.Visible; restored = (-not $tw.Visible -and -not $KeepShown) } | ConvertTo-Json -Compress
    }
    "click" {
        # 仅允许左侧菜单导航! 买入/卖出/撤单区禁止. -RealClick 时才真实生效
        $tw = Find-TradeWindow
        if (-not $tw -or $tw.Hwnd -eq [IntPtr]::Zero) { @{ ok = $false; error = "交易窗口未找到" } | ConvertTo-Json -Compress; break }
        if ($RealClick) {
            [void][EM]::ShowWindow($tw.Hwnd, 8)
            Start-Sleep -Milliseconds 300
            [EM]::RealClick($tw.Hwnd, $X, $Y)
            @{ ok = $true; clicked = "$X,$Y"; real = $true; hwnd = [long]$tw.Hwnd; warn = "click 仅限菜单导航, 禁止交易区" } | ConvertTo-Json -Compress
        } else {
            $lp = [IntPtr](($Y -shl 16) -bor ($X -band 0xFFFF))
            [void][EM]::PostMessage($tw.Hwnd, 0x0201, [IntPtr]1, $lp)   # WM_LBUTTONDOWN
            Start-Sleep -Milliseconds 60
            [void][EM]::PostMessage($tw.Hwnd, 0x0202, [IntPtr]0, $lp)   # WM_LBUTTONUP
            @{ ok = $true; clicked = "$X,$Y"; real = $false; hwnd = [long]$tw.Hwnd; warn = "合成点击被东财忽略, 需 -RealClick; click 仅限菜单导航, 禁止交易区" } | ConvertTo-Json -Compress
        }
    }
    "hide" {
        $tw = Find-TradeWindow
        if (-not $tw -or $tw.Hwnd -eq [IntPtr]::Zero) { @{ ok = $false; error = "交易窗口未找到" } | ConvertTo-Json -Compress; break }
        [void][EM]::ShowWindow($tw.Hwnd, 0)              # SW_HIDE
        @{ ok = $true; hwnd = [long]$tw.Hwnd } | ConvertTo-Json -Compress
    }
    "read" {
        # hermes 主调用: 一次拿到 窗口状态 + 目标页截图
        $tw = Find-TradeWindow
        if (-not $tw) { @{ ok = $false; error = "mainfree 进程不存在(东财未启动)" } | ConvertTo-Json -Compress; break }
        if ($tw.Hwnd -eq [IntPtr]::Zero) { @{ ok = $false; error = "交易窗口未找到(可能未登录交易账号)" } | ConvertTo-Json -Compress; break }
        [void][EM]::ShowWindow($tw.Hwnd, 8)
        [void][EM]::MoveWindow($tw.Hwnd, 50, 50, 1600, 950, $true)
        Start-Sleep -Milliseconds 400
        if ($Page -and $PageXY.ContainsKey($Page)) {
            Click-Menu $tw.Hwnd $PageXY[$Page][0] $PageXY[$Page][1] -Real:$RealClick
        }
        $tag = $(if ($Page) { $Page } else { "read" })
        $file = Join-Path $OutDir ("em_{0}_{1:yyyyMMdd_HHmmss}.png" -f $tag, (Get-Date))
        $cap = [EM]::Capture($tw.Hwnd, $file) -split "\|"
        if (-not $tw.Visible -and -not $KeepShown) { [void][EM]::ShowWindow($tw.Hwnd, 0) }
        @{ ok = ($cap[0] -eq "True"); file = $file; size = $cap[1]; pid = $tw.Pid; hwnd = [long]$tw.Hwnd;
           page = $Page; realClick = [bool]$RealClick; wasVisible = $tw.Visible; restored = (-not $tw.Visible -and -not $KeepShown);
           pageNote = $(if ($Page -and -not $RealClick) { "警告: 未加 -RealClick, 合成点击被东财忽略, 截图仍是当前页" } else { "" });
           hint = "用 Read 工具查看此 PNG 得到资金/持仓/成交; 换页用 -Page 资金持仓|当日成交|当日委托|历史成交|交割单 -RealClick" } | ConvertTo-Json -Compress
    }
}
