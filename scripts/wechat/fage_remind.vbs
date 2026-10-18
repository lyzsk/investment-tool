' fage_remind.vbs — 交易日 08:05 由计划任务 FageRemind 无窗口起发哥提醒(10/15 建; wscript //B, 零弹窗立法)
' 非交易日/发哥已入库 由 fage_remind.py 自己判断后静默退出
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\wechat\fage_remind.py >> scripts\wechat\fage_remind.log 2>&1", 0, False
