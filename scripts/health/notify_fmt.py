# -*- coding: utf-8 -*-
"""notify_fmt.py — 巡检 / 对账类微信推送的统一排版(10/23 用户令: 对账推送原来是纯日志流, 微信上很乱)

格式(手机 / 电脑微信都好读: 短行、不用表格、只展开非常规项):
  【对账 · 行情库】10/22 周四 23:50
  ✅ 33 项正常 · 🔧 1 项已自动修复 · ⚠️ 0 项需注意 · ❌ 0 项失败
  ——
  🔧 10-21 分时线 已自动修复：1820 → 1950 只
  ⚠️ 卢本圆 有 5 条视频没进 md
     影响：这几天的观点没进蒸馏
     打算：…
用法: from notify_fmt import render; render("对账 · 行情库", when, items)  items = [{"st": ok|fixed|warn|fail, "title": "...", "lines": [...]}]
"""
import datetime as dt

ICON = {"ok": "✅", "fixed": "🔧", "warn": "⚠️", "fail": "❌"}
WEEK = "一二三四五六日"


def render(title, when, items, foot=""):
    if isinstance(when, str):
        when = dt.datetime.fromisoformat(when)
    c = {k: sum(1 for x in items if x["st"] == k) for k in ICON}
    L = [f"【{title}】{when:%m/%d} 周{WEEK[when.weekday()]} {when:%H:%M}",
         f"✅ {c['ok']} 项正常 · 🔧 {c['fixed']} 项已自动修复 · ⚠️ {c['warn']} 项需注意 · ❌ {c['fail']} 项失败"]
    odd = [x for x in items if x["st"] != "ok"]
    if odd:
        L.append("——")
        for x in sorted(odd, key=lambda x: ["fail", "warn", "fixed"].index(x["st"])):
            L.append(f"{ICON[x['st']]} {x['title']}")
            L += [f"   {ln}" for ln in x.get("lines") or []]
    else:
        L.append("全部正常, 没有要处理的")
    if foot:
        L += ["", foot]
    return "\n".join(L)
