Get-Process hermes -ErrorAction SilentlyContinue | ForEach-Object { "hermes.exe PID {0} path: {1}" -f $_.Id, $_.Path }
Get-CimInstance Win32_Process -Filter "Name='hermes.exe'" | ForEach-Object { "cmd: " + $_.CommandLine }
"--- WeChat 系进程:"
Get-Process | Where-Object { $_.Name -match 'WeChat|Weixin' } | Select-Object Name, Id | Format-Table -AutoSize
