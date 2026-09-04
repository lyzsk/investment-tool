---
name: pc2-remote-screen
description: "Use when 从PC1远程查看PC2桌面窗口内容(东财等)。SSH+cua-driver截图+RapidOCR。"
---

# PC2 远程截屏识图流程

从 PC1（中枢）远程读取 PC2 桌面窗口内容（只读快照，可配点击）。PC2 笔记本合盖不影响。

## 前提（已配好，2026-08-23）
- PC2 = 100.111.59.0，SSH 用户 Administrator，免密已通
- PC2 已装 cua-driver（`%LOCALAPPDATA%\Programs\Cua\cua-driver\bin\cua-driver.exe`），自启任务 `cua-driver-serve` 常驻交互会话（合盖可用）
- ⚠️ 盖盖子后物理屏幕关闭：UIA 文字树可读，但像素截屏依赖窗口处于**非最小化**状态

## 步骤

1. **找窗口**：
   ```bash
   ssh Administrator@100.111.59.0 "%LOCALAPPDATA%\Programs\Cua\cua-driver\bin\cua-driver.exe call list_windows"
   ```
   记下目标窗口的 pid + window_id（东财主程序 mainfree.exe，标题"东方财富终端"）。

2. **若窗口最小化**（bounds x≈-32000 即最小化）：daemon 的 bring_to_front 会被拒（合盖无前台）。用计划任务在用户会话里还原：
   - PC1 写好 restore ps1（按 pid 取 MainWindowHandle → user32 ShowWindow(hwnd,9)），scp 到 PC2 C:\Temp\
   - `ssh ... schtasks /create /tn pc2restore /tr "powershell -ExecutionPolicy Bypass -File C:\Temp\restore_em.ps1" /sc once /st 00:00 /ru Administrator /it /f && schtasks /run /tn pc2restore`
   - 参考脚本：investment-tool/strategy/scripts/restore_em.ps1（FindWindow 按标题可能失败，按 PID 取 MainWindowHandle 更稳）

3. **截屏**：
   ```bash
   ssh Administrator@100.111.59.0 "...cua-driver.exe call get_window_state \"{\\\"pid\\\": PID, \\\"window_id\\\": WID, \\\"max_elements\\\": 5}\""
   ```
   返回 JSON 里 `screenshot_png_b64` 即整窗截图（base64）。东财是自绘界面，elements 通常为空（degraded=true 正常），只用截图。

4. **OCR**：**用 RapidOCR，不要用后端 Tesseract**（东财小字 Tesseract 全乱码）：
   ```bash
   uv run --with rapidocr-onnxruntime python -c "from rapidocr_onnxruntime import RapidOCR; r,_=RapidOCR()(图片路径); [print(t) for b,t,s in r if s>0.5]"
   ```

## 坑
- `cua-driver mcp`（Hermes computer_use 走的路径）在 SSH 的 Session 0 里起不来；但 `cua-driver call` 直接连默认管道 \\.\pipe\cua-driver 可以用 —— 远程操作用 call，不走 PC2 的 Hermes
- 计划任务恢复窗口需要用户处于登录状态（锁屏/注销后失效）
- 东财的持仓/委托/成交在「交易(E)/F12快速交易」模块，默认行情界面看不到，需要用户先登录券商交易端
