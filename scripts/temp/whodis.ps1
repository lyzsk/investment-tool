Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Sort-Object WorkingSetSize -Descending | Select-Object -First 4 | ForEach-Object {
  "PID {0}: {1}" -f $_.ProcessId, $_.CommandLine.Substring(0, [Math]::Min(150, $_.CommandLine.Length))
}
"--- hermes:"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'hermes' } | ForEach-Object {
  "PID {0} [{1}]: {2}" -f $_.ProcessId, $_.Name, $_.CommandLine.Substring(0, [Math]::Min(180, $_.CommandLine.Length))
}
