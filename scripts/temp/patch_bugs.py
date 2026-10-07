import io
p = r"C:\Users\admin\dev\dev-notes\bugs\bugs.md"
s = io.open(p, encoding="utf-8").read()
old = """解决: 复刻原始 argv 手动起 gateway:

```
start "" "C:\Users\admin\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" "C:\Users\admin\AppData\Local\hermes\hermes-agent\hermes_cli\main.py" gateway run
```

gateway.log 出现 "Gateway housekeeping started" + weixin inbound 恢复即通"""
new = """解决: 复刻原始 argv 手动起 gateway. step1: Win+R 输入 cmd 回车 (powershell 也行, 任意目录); step2: 粘贴下面这行回车:

```
start "" "C:\Users\admin\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" "C:\Users\admin\AppData\Local\hermes\hermes-agent\hermes_cli\main.py" gateway run
```

step3: 会弹出一个**新的黑色控制台窗口**, gateway 就活在这个窗口里, 日志在里面滚 —— **别关这个窗口**, 关了 gateway 就又死了; step4: 验证=微信 ClawBot 那行小字消失/发条消息有回复, 或者 tail gateway.log 看到 "Gateway housekeeping started" + weixin inbound"""
assert old in s, "old not found"
io.open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("patched ok")
