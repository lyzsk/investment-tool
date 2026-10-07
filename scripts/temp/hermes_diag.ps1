Get-CimInstance Win32_Process -Filter "Name='hermes.exe'" | ForEach-Object {
  "PID {0}" -f $_.ProcessId
  "  path: " + $_.ExecutablePath
  "  cmd:  " + $(if ($_.CommandLine) { $_.CommandLine.Substring(0,[Math]::Min(200,$_.CommandLine.Length)) } else { "<null>" })
}
"--- hermes 监听端口:"
netstat -ano | Select-String "31636"
