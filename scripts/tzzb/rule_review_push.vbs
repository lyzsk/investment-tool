' rule_review_push.vbs - rule review on demand: --watch 19:00-24:00 (user sends 'gui ze' on WeChat -> next 2 rules). ASCII only.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c C:\Users\admin\anaconda3\python.exe -X utf8 scripts\tzzb\rule_review_push.py --watch >> scripts\temp\rule_review_push.log 2>&1", 0, False
