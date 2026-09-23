# install_tasks.ps1 - register taoge-paper scheduled tasks (run once, as current user)
# TaogePaperSentinel: Mon-Fri 09:12 -> sentinel.mjs (live polling, self-exits 15:10)
# TaogePaperSettle:   Mon-Fri 15:06 -> paper_settle.mjs (no args, defaults to today)
# Rehearsal note: wake.enabled in config.json stays false until headless claude is approved.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$vbs = Join-Path $root 'run_hidden.vbs'   # 经 wscript 隐藏启动, 计划任务不再闪控制台窗口

$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$a1 = New-ScheduledTaskAction -Execute $wscript -Argument "`"$vbs`" sentinel.mjs" -WorkingDirectory $root
$t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:12
Register-ScheduledTask -TaskName 'TaogePaperSentinel' -Action $a1 -Trigger $t1 -Settings $settings -Force |
  Out-Null

$a2 = New-ScheduledTaskAction -Execute $wscript -Argument "`"$vbs`" paper_settle.mjs" -WorkingDirectory $root
$t2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 15:06
Register-ScheduledTask -TaskName 'TaogePaperSettle' -Action $a2 -Trigger $t2 -Settings $settings -Force |
  Out-Null

Get-ScheduledTask -TaskName 'TaogePaper*' | Select-Object TaskName, State
Write-Host 'done. uninstall: Unregister-ScheduledTask -TaskName TaogePaperSentinel,TaogePaperSettle'
