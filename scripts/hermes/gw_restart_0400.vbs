' gw_restart_0400.vbs - HermesGwRestart0400 (daily 04:00). ASCII only: VBScript misreads UTF-8 Chinese comments
' 2026-10-27: scan Claude jsonl + re-push missed WeChat replies BEFORE restart, restart gateway, then flush outbox (drain_pending.py)
' the restart itself is inside drain_pending.py (same command as gw_restart.vbs); 11:31 / 15:01 still use gw_restart.vbs
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\hermes\drain_pending.py --mode hermes0400 --restart >> scripts\temp\drain_pending.out 2>&1", 0, False
