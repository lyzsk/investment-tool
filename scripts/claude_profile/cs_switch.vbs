' cs_switch.vbs - 10/29 user: 08:30 -> gravitex, 18:30 -> kimi-code; waits for the interactive CLI to be idle, sets settings.json, then types /model into the CLI (no restart)
' usage: wscript //B cs_switch.vbs <profile>
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\claude_profile\cs_switch.py " & WScript.Arguments(0) & " >> scripts\claude_profile\cs_switch.log 2>&1", 0, False
