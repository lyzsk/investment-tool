# bg_tasks.ps1 — background tasks panorama (2026-10-08, popup-incident followup)
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bg_tasks.ps1            # list everything
#   powershell ... -File scripts\bg_tasks.ps1 -Stop TaskName    # disable a scheduled task
#   powershell ... -File scripts\bg_tasks.ps1 -KillPid 1234     # kill a process by pid
# Popup law (10/8): this script never creates windows itself; if ever scheduled, wrap via wscript //B.
param(
    [string]$Stop = "",
    [int]$KillPid = 0
)

if ($Stop) {
    Disable-ScheduledTask -TaskName $Stop | Out-Null
    Write-Output "DISABLED task: $Stop"
    exit 0
}
if ($KillPid -gt 0) {
    Stop-Process -Id $KillPid -Force
    Write-Output "KILLED pid: $KillPid"
    exit 0
}

Write-Output "================ SCHEDULED TASKS (non-Microsoft) ================"
Get-ScheduledTask | Where-Object { $_.TaskPath -notlike "\Microsoft\*" } | ForEach-Object {
    $t = $_
    $info = $t | Get-ScheduledTaskInfo
    $trig = ($t.Triggers | ForEach-Object {
        $ival = ""
        if ($_.Repetition.Interval) { $ival = " every " + $_.Repetition.Interval }
        $_.CimClass.CimClassName + $ival
    }) -join "; "
    $act = ($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join " && "
    if ($act.Length -gt 110) { $act = $act.Substring(0, 110) + "..." }
    $next = if ($info.NextRunTime -and $info.NextRunTime.Year -gt 2000) { $info.NextRunTime.ToString("MM-dd HH:mm") } else { "-" }
    "{0,-26} {1,-8} next={2}  [{3}]" -f $t.TaskName, $t.State, $next, $trig
    "    -> $act"
}

Write-Output ""
Write-Output "================ RESIDENT SCRIPT PROCESSES ================"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='node.exe' OR Name='wscript.exe' OR Name='java.exe'" |
ForEach-Object {
    $cl = $_.CommandLine
    if (-not $cl) { $cl = "(no cmdline)" }
    if ($cl.Length -gt 130) { $cl = $cl.Substring(0, 130) + "..." }
    "pid={0,-7} {1,-12} parent={2,-7} {3}" -f $_.ProcessId, $_.Name, $_.ParentProcessId, $cl
}

Write-Output ""
Write-Output "================ CLAUDE CRON (durable) ================"
$cronFiles = @(
    "C:\Users\admin\.claude\scheduled_tasks.json",
    "C:\Users\admin\dev\investment-tool\.claude\scheduled_tasks.json"
)
$found = $false
foreach ($f in $cronFiles) {
    if (Test-Path $f) {
        $found = $true
        Write-Output "--- $f"
        Get-Content $f -Raw
    }
}
if (-not $found) { Write-Output "(none)" }
