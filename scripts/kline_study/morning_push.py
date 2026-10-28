# -*- coding: utf-8 -*-
"""morning_push.py — 盘前首跑收尾: 持仓 K 线预测(文字 + 主情景图) + 明日预案要点, 推微信(10/27 用户令: "盘前首跑结束后, 优先给我持仓的 K 线预测和对昨夜明日备案的核对"; 零 token)

持仓 = scripts/dfcf/snapshots 最近一份成交导出里 持仓数量 > 0 的代码(只取代码, 数量金额不出内存 —— 实盘隐私)
预测 = scen_v2.scen(代码, 上一交易日)(机械: 票型 × 走法概率, 近邻样本, 样本外命中) —— 要用 anaconda python(sklearn)
图   = results/kline/<日>/ 里这只票最新一张截图的续画(两日 top1), 没有截图就只给文字
预案 = results/_live/<D>/expect.md 的「明日聚焦」前 3 + 新口径阶段 + 种子池缺位 / 字辈(不当事实, 只给参考)
调用: paper_line/orchestrator.py 盘前汇总推完后调一次(D 当天只推一次, 标记 results/_live/<D>/morning_push.done); 手动: python morning_push.py --date D [--dry]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "results" / "_live"
ANA = r"C:/Users/admin/anaconda3/python.exe"
for _p in ("hermes", "dfcf/paper", "paper_line/tools"):
    sys.path.insert(0, str(ROOT / "scripts" / _p))


def holdings():
    """最近一份成交导出里 持仓数量 > 0 的 (代码, 名称)"""
    import t_bot as TB
    out = []
    for f in TB._snap_files()[-1:]:
        for l in f.read_text(encoding="utf-8").splitlines():
            w = l.split()
            if len(w) >= 5 and w[0].isdigit() and len(w[0]) <= 3 and len(w[1]) == 6 and w[1].isdigit():
                try:
                    if float(w[3]) > 0:
                        out.append((w[1], w[2]))
                except ValueError:
                    continue
    return out


def scen(code, T):
    r = subprocess.run([ANA, "-X", "utf8", str(ROOT / "scripts" / "kline_study" / "scen_v2.py"), code, T], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), cwd=str(ROOT))
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        return None


def latest_img(code, T):
    best = None
    for st in sorted((ROOT / "results" / "kline").glob("20*/_status.json")):
        if st.parent.name.replace(".", "-") > T:
            continue
        try:
            im = json.loads(st.read_text(encoding="utf-8")).get("images") or {}
        except (OSError, ValueError):
            continue
        for k, v in im.items():
            if str(v.get("case") or "").startswith(code + "@") and "日K" in str(v.get("类型")):
                g = [x for x in ((v.get("预测") or {}).get("图") or []) if "_v2_1" in x]
                if g:
                    best = ROOT / g[0].replace("\\", "/")
    return best if best and best.exists() else None


def lines(c, nm, d):
    if not d:
        return f"{nm}: 预测没跑出来(特征表没到昨天?)"
    t1, ex = d["top3_单日"], d["极端"]
    nb = t1[0]["近邻路径"]
    return (f"{nm} {d['票型']} 收 {d['收盘']} · {d['置信']}\n"
            f"  T+1: " + " / ".join(f"{x['名']} {x['概率']:.0f}%" for x in t1)
            + f" · 涨停 {ex['T+1']['涨停']['模型']:.0f}% 跌停 {ex['T+1']['跌停']['模型']:.0f}%"
            + f"\n  近邻 {nb['近邻n']} 例 T+1 高 P25/中/75 {nb['T+1高']} · 收 {nb['T+1收 P25/中位/P75']}")


def expect_brief(D):
    t = (LIVE / D / "expect.md").read_text(encoding="utf-8") if (LIVE / D / "expect.md").exists() else ""
    if not t:
        return ["明日预案: 没有(昨晚 check md 没跑出来)"]
    out = ["明日预案要点(参考, 不当事实):"]
    for m in re.finditer(r"^- \*\*(.+?)\*\*: 今天 (\d+) 家.*?\n  新口径阶段: \*\*(.+?)\*\* · (.+?)〔", t, re.M):
        out.append(f"· {m.group(1)}: {m.group(3)} · {m.group(4)[:80]}")
        if len(out) >= 4:
            break
    m = re.search(r"^- 连板梯队: (.+)$", t, re.M)
    if m:
        out.append("· 梯队 " + m.group(1)[:120])
    for m in re.finditer(r"^- 字辈 (\S+): 近 10 日涨停 (\d+) 只", t, re.M):
        out.append(f"· 字辈 {m.group(1)} 近 10 日 {m.group(2)} 只")
    return out


def run(D, dry=False):
    flag = LIVE / D / "morning_push.done"
    if flag.exists() and not dry:
        return "今天推过了"
    import expect as EXP
    days = sorted(p.name for p in (ROOT / "downloads" / "market").glob("20*") if p.name < D and (p / "kline_day.jsonl").exists())
    T = days[-1] if days else EXP.next_day(D)
    H = holdings()
    L = [f"盘前持仓 K 线预测 {D}(按 {T} 收盘; scen_v2 机械预测, 不是买卖建议)"]
    imgs = []
    for c, nm in H:
        if c.startswith(("204", "1318")):
            continue
        L.append(lines(c, nm, scen(c, T)))
        im = latest_img(c, T)
        if im:
            imgs.append((nm, im))
    L.append("")
    L += expect_brief(D)
    txt = "\n".join(L)
    print(txt)
    if dry:
        return "dry"
    import wx_send
    wx_send.send(txt, src="morning_kline", raw=True, wait=300, force=True)
    for nm, im in imgs[:4]:   # 图最多 4 张(微信额度)
        wx_send.send(f"MEDIA:{im} {nm} 两日 top1 续画", src="morning_kline", raw=True, wait=300, force=True)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(dt.datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    return "已推"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    print(run(a.date, a.dry))
