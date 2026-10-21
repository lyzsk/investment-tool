' session_rollover_start.vbs — 交易日 07:58 由计划任务 ClaudeSessionRollover 无窗口启动 session_rollover.py(10/20 用户批 T1; wscript //B)
' 非交易日由脚本自己判断后退出; 脚本会有意打开一个新的 Claude 主窗口(零弹窗立法的例外, 用户 10/20 批)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\hermes\session_rollover.py >> scripts\temp\session_rollover.out 2>&1", 0, False
