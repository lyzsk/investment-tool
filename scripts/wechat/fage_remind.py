# -*- coding: utf-8 -*-
"""fage_remind.py — 交易日 08:05 发哥提醒(10/15 建, 零 token)
起因: 0915 链 10/16 起 08:15 开跑, 就是为了让发哥(07:17~08:02 发文)进 facts; 发现层=用户人工贴链接,
     到 08:05 还没贴 → 微信提醒一次(走 hermes send, 不经 LLM)。已贴/非交易日 → 静默退出。
计划任务 FageRemind 工作日 08:05 经 wscript //B fage_remind.vbs 无窗口起(零弹窗立法)。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/wechat/fage_remind.py [--dry]
"""
import datetime as dt, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERMES = r"C:\Users\admin\AppData\Local\hermes\hermes-agent\bin\hermes.exe"
NOWIN = 0x08000000


def main():
    d = dt.date.today()
    md = ROOT / "md" / f"{d.year}S{(d.month + 2) // 3}" / f"{d.isoformat()}.md"
    if not md.exists():
        return "非交易日(无当天 md), 不提醒"
    if (ROOT / "downloads" / "wechat" / "fage" / d.isoformat() / "meta.json").exists():
        return "发哥今日已入库, 不提醒"
    msg = (f"【提醒 {dt.datetime.now():%H:%M}】发哥今天的盘前推演还没贴。paper 0915 链 08:05 开跑建资讯包, "
           "08:05 前把公众号链接发给 hermes(或在 Claude Code 里贴), 链才看得到发哥。")
    if "--dry" in sys.argv:
        return "DRY: " + msg
    for t in range(3):
        r = subprocess.run([HERMES, "send", "--to", "weixin", msg], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        if r.returncode == 0:
            return "已提醒"
    return f"微信发送失败: {(r.stdout + r.stderr)[-200:]}"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} {main()}")
