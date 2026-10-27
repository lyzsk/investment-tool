' gw_restart.vbs - hermes gateway scheduled restart (HermesGwRestart0400/1131/1501). ASCII only: VBScript misreads UTF-8 Chinese comments
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\admin\dev\investment-tool"
sh.Run "cmd /c echo [%date% %time%] restart >> scripts\temp\hermes_gw_restart.log & ""C:\Users\admin\AppData\Local\hermes\hermes-agent\bin\hermes.exe"" gateway restart >> scripts\temp\hermes_gw_restart.log 2>&1", 0, False
