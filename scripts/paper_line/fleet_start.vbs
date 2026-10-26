' fleet_start.vbs — 工作日 08:52 由计划任务 PaperLineFleet 无窗口拉起 paper v3 执行器(10/22 晚建; wscript //B, 零弹窗立法)
' 非交易日 / 不在时段 / 已在跑 / 开关 PAPER_FLEET 未开 由 fleet.py --ensure 自己判断后退出; 盘中崩溃重拉靠 check md --only mix 每 5 分钟
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\paper_line\fleet.py --ensure >> scripts\temp\line_fleet.log 2>&1", 0, False
