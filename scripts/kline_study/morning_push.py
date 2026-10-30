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


def latest_imgs(code, T):
    """每只持仓 = 日 K + 五日(或分时)各两张: 原衔接画法, _v2_1 = 两日组合概率最高 / _v2_2 = 次高(10/30 用户最终口径); 取截止 ≤T 最新一份截图的续画"""
    got = {}
    for st in sorted((ROOT / "results" / "kline").glob("20*/_status.json")):
        if st.parent.name.replace(".", "-") > T:
            continue
        try:
            im = json.loads(st.read_text(encoding="utf-8")).get("images") or {}
        except (OSError, ValueError):
            continue
        for k, v in im.items():
            if not str(v.get("case") or "").startswith(code + "@"):
                continue
            ty = "日K" if "日K" in str(v.get("类型")) else "五日" if str(v.get("类型")) in ("五日", "分时") else None
            if not ty:
                continue
            g = [ROOT / x.replace("\\", "/") for x in ((v.get("预测") or {}).get("图") or []) if "_v2_1" in x or "_v2_2" in x]
            g = [x for x in g if x.exists()]
            if g:
                got[ty] = sorted(g)[:2]
    return got


def compose(code, nm, got, T):
    """一只票一张图: 上 = 日 K 概率最高 | 次高, 下 = 五日 概率最高 | 次高(缺哪行就少哪行); 每张缩到 1000 宽"""
    from PIL import Image
    rows = []
    for ty in ("日K", "五日"):
        ims = [Image.open(x).convert("RGB") for x in got.get(ty) or []]
        if not ims:
            continue
        ims = [im.resize((1000, int(im.height * 1000 / im.width))) for im in ims]
        h = max(im.height for im in ims)
        row = Image.new("RGB", (1000 * len(ims), h), (17, 20, 24))
        for i, im in enumerate(ims):
            row.paste(im, (1000 * i, 0))
        rows.append(row)
    if not rows:
        return None
    W, H = max(r.width for r in rows), sum(r.height for r in rows)
    cv = Image.new("RGB", (W, H), (17, 20, 24))
    y = 0
    for r in rows:
        cv.paste(r, (0, y))
        y += r.height
    out = ROOT / "results" / "kline" / "_morning" / f"{code}_{T}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv.save(out, quality=85)
    return out


def lines(c, nm, d):
    """10/29 晚用户改口径: 持仓 K 线预测只给概率最高 + 次高两种(两日组合 top1 / top2), 不再给正例 / 反例 / 涨跌平合计"""
    if not d:
        return f"{nm}: 预测没跑出来(特征表没到昨天?)"
    t2 = (d.get("top3_两日") or d.get("两日top3") or [])[:2]   # scen_v2 实时输出 = top3_两日(对象); 截图状态 = 两日top3(字符串)
    if t2:
        parts = [f"{x['名']} {float(x['概率']):.1f}%" if isinstance(x, dict) else str(x) for x in t2]
        cal = ""
        try:   # 预测核销账本: 本票型两日 top1 的事前命中(样本 <10 不显示)
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import forecast_ledger as FL
            lc = FL.db()
            r = FL.calib(lc, "kline_v2", "two_day_top1", f"票型:{d.get('票型') or '未知'}")
            lc.close()
            if r["n"] >= 10 and r["hit"] is not None:
                cal = f" · 本类事前top1 {r['hit']:.0%}(基线 {r['baseline']:.0%},n={r['n']})"
        except Exception:   # noqa: BLE001
            pass
        return f"{nm}: ①{parts[0]}" + (f" ②{parts[1]}" if len(parts) > 1 else "") + (f"(置信 {d.get('置信')})" if d.get("置信") else "") + cal
    allw = d.get("全部走法%") or {}
    up = ("涨停", "单边上涨", "深V")
    dn = ("跌停", "单边下跌", "冲高A杀", "高开低走")
    f = lambda xs: round(sum(float(v["模型"] if isinstance(v, dict) else v) for w, v in allw.items() if w in xs), 0)   # noqa: E731
    u, dw = f(up), f(dn)
    return f"{nm}: 涨 {u:.0f}% / 跌 {dw:.0f}% / 平 {100 - u - dw:.0f}% → 偏{'涨' if u > dw else '跌'}(方向命中参考 44%, 基线 43%)"


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
        got = latest_imgs(c, T)   # 10/30 用户最终确认: 原衔接画法, 但选图改为两日组合概率 top1 / top2
        im = compose(c, nm, got, T) if got else None
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
        wx_send.send(f"MEDIA:{im} {nm} 上 = 日K 概率最高 | 次高 · 下 = 五日 概率最高 | 次高(原衔接画法)", src="morning_kline", raw=True, wait=300, force=True)
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
