' live_watch_start.vbs — 交易日 09:10 由计划任务 LiveWatch 无窗口启动盘中盯盘(10/14 建; wscript //B, 零弹窗立法)
' 非交易日/已有实例在跑 由 live_watch.mjs 自己判断后退出; 关注票=scripts\dfcf\snapshots\live\watchlist.txt
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c node scripts\dfcf\live_watch.mjs >> scripts\dfcf\snapshots\live\watch.log 2>&1", 0, False
