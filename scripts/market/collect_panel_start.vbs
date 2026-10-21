' collect_panel_start.vbs — 工作日 07:30 由计划任务 PanelCollect 无窗口启动多指数面板采集(10/20 建; wscript //B, 零弹窗立法)
' 非工作日 / 不在时段 / 已在跑 / 开关 PANEL_COLLECT 未开 由 collect_panel.py --ensure 自己判断后退出; 启动时先回补 A50 / 小纳指隔夜分钟线
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c scripts\venv\Scripts\python.exe -X utf8 scripts\market\collect_panel.py --ensure >> scripts\temp\collect_panel.log 2>&1", 0, False
