' run_hidden.vbs <script.mjs> [args...] — 以完全隐藏窗口方式启动 node(计划任务用, 防控制台闪现)
Dim fso, shell, root, cmd, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "node """ & root & "\" & WScript.Arguments(0) & """"
For i = 1 To WScript.Arguments.Count - 1
  cmd = cmd & " " & WScript.Arguments(i)
Next
shell.CurrentDirectory = root
shell.Run cmd, 0, False
