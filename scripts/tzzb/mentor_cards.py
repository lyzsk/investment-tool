# -*- coding: utf-8 -*-
"""mentor_cards.py — 导师名片: 从真实成交机械统计风格 / 业绩 / 风险, 带"截至哪天、近多少天"(10/18 用户定; 零 token, 只读)

为什么: 原来每天给所有链看的"导师信号速览"标题(登记表 short)和各 chain.md 的能力圈是人/agent 写死的快照
        (如"日均+1.10%""无止损反面教材""常见簇=电力/通信设备"), 不会随导师变化而变, 带短期倾向, 还左右链的判断。
做法: 全部改成机械统计, 每天重算, 写明窗口和截至日; 评价也可以有, 但必须是算出来的(如"60日最大回撤 −35%""仓位均值 180%=两融")
口径(as-of: 只用 < D 的数据):
  窗口 = 该导师账本最近 WIN(60) 个有净值的交易日
  打法  = cases_auto.jsonl 新开仓买入的 play 标签分布(窗口内), 取前 2
  板块  = 新开仓买入代码的板块分布(主板/创业/科创/北交/ETF/转债), 取前 2
  持股  = day_positions 里同一只票连续在持的交易日数, 取中位
  仓位  = day_positions sum_pct 的均值(>100% = 用了两融)
  业绩  = 近 30 日净值收益、窗口内最大回撤; 胜率 = 新开仓次日收益 > 0 的占比
  常买  = 窗口内买入次数最多的 3 只
  B站 UP: 没有账本, 只写"B站 UP(视频披露)"; 对照组不出名片
产物: scripts/tzzb/mentor_cards/<D>.json(机器读) + docs/mentor_cards.md(给你看, 每次覆盖为最新)
消费: facts.mjs 导师信号速览的节标题(名字 + 机械标签 + 截至日); 之后 chain.md 能力圈也改读这里(周末和模板化一起做)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/mentor_cards.py [--date D]
"""
import argparse
import collections
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors as M  # noqa: E402

TZ = ROOT / "downloads" / "tzzb"
OUT = Path(__file__).with_name("mentor_cards")
DOC = ROOT / "docs" / "mentor_cards.md"
WIN, RET_WIN = 60, 30


def board(code):
    c = str(code)
    if c.startswith(("11", "12")):
        return "转债"
    if c.startswith(("15", "16", "18", "51", "52", "56", "58")):
        return "ETF"
    if c.startswith("688"):
        return "科创"
    if c.startswith(("30",)):
        return "创业"
    if c.startswith(("8", "4", "92")):
        return "北交"
    return "主板"


def top(counter, k, n):
    tot = sum(counter.values()) or 1
    return [f"{x} {v / tot:.0%}" for x, v in counter.most_common(k)]


def card(lid, D):
    d8 = D.replace("-", "")
    try:
        il = json.loads((TZ / lid / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        nav = [(str(x["date"]), float(x["index"])) for x in il if float(x.get("index") or 0) > 0 and str(x["date"]) < d8]
    except Exception:   # noqa: BLE001
        nav = []
    if len(nav) < 10:
        return None
    w = nav[-WIN:]
    lo, hi = w[0][0], w[-1][0]
    r30 = nav[-1][1] / nav[-(RET_WIN + 1)][1] - 1 if len(nav) > RET_WIN else None
    peak, mdd = 0.0, 0.0
    for _, v in w:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    plays, boards, names, wins = collections.Counter(), collections.Counter(), collections.Counter(), []
    cf = ROOT / "skills" / f"{lid}-skill" / "persona" / "cases_auto.jsonl"
    if cf.exists():
        for line in cf.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(line)
            except ValueError:
                continue
            dd = str(c.get("date", "")).replace("-", "")
            if c.get("side") != "买" or not (lo <= dd <= hi):
                continue
            names[c.get("name") or c.get("code")] += 1
            if c.get("new_open"):
                plays[c.get("play") or "未分类"] += 1
                boards[board(c.get("code"))] += 1
                rn = (c.get("result") or {}).get("r_next")
                if rn is not None:
                    wins.append(rn > 0)
    hold, pos = [], []
    try:
        dp = json.loads((TZ / lid / "day_positions.json").read_text(encoding="utf-8"))
        days = sorted(k for k in dp if lo <= k <= hi)
        run = {}
        for k in days:
            rec = dp[k] or {}
            pos.append(float(rec.get("sum_pct") or 0) * 100)   # sum_pct 是小数(0.999=99.9%)
            held = {str(x.get("code")) for x in rec.get("list") or [] if float(x.get("position_percent") or 0) > 0}
            for cde in list(run):
                if cde not in held:
                    hold.append(run.pop(cde))
            for cde in held:
                run[cde] = run.get(cde, 0) + 1
        hold += list(run.values())
    except Exception:   # noqa: BLE001
        pass
    avg_pos = st.mean(pos) if pos else None
    for junk in ("数据缺失", "未分类"):
        plays.pop(junk, None)
    tags = top(plays, 2, 0)
    tags += [b for b in top(boards, 2, 0) if b.split()[0] not in {x.split()[0] for x in tags}]   # 打法和板块同名(转债)只留一个
    if hold:
        tags.append(f"持股中位 {st.median(hold):.0f} 天")
    if avg_pos is not None:
        tags.append(f"仓位均值 {avg_pos:.0f}%" + ("(两融)" if avg_pos > 105 else ""))
    perf = []
    if r30 is not None:
        perf.append(f"近{RET_WIN}日 {r30:+.0%}")
    perf.append(f"{len(w)}日最大回撤 {mdd:.0%}")
    if len(wins) >= 5:
        perf.append(f"新开仓次日胜率 {sum(wins) / len(wins):.0%}")
    return {"window": [f"{lo[:4]}-{lo[4:6]}-{lo[6:]}", f"{hi[:4]}-{hi[4:6]}-{hi[6:]}"], "n_days": len(w), "asof": f"{hi[4:6]}-{hi[6:]}",
            "style": tags, "perf": perf, "top_names": [n for n, _ in names.most_common(3)], "new_buys": sum(plays.values()),
            "ret30": r30, "mdd": round(mdd, 4), "avg_pos": avg_pos}


def up_pool(uid):
    """10/19 用户: UP 没有账本, 风格靠"常讲股票池" —— skills/<id>-skill/persona/stock_pool.md(POOL / THEME 行) +
    md/rules.md(桃哥 2025-08~09 整理的半导体 / AI 硬件细分表, 去年口径, 今年资金惯性方向有变, 只作参考) 里这些票所在的细分 → 衍生板块"""
    f = ROOT / "skills" / f"{uid}-skill" / "persona" / "stock_pool.md"
    if not f.exists():
        return None
    import re
    t = f.read_text(encoding="utf-8")
    m, th = re.search(r"^POOL: ([\d,]+)", t, re.M), re.search(r"^THEME: (.+)$", t, re.M)
    codes = m.group(1).split(",") if m else []
    names = dict(re.findall(r"^\| ([^|（(]+?)(?:（[^）]*）)? \| (\d{6}) \|", t, re.M))
    names = {v: k.strip() for k, v in names.items()} if names else {}
    secs = collections.Counter()
    try:
        rt = (ROOT / "md" / "rules.md").read_text(encoding="utf-8")
        cur, big = None, None
        for line in rt.splitlines():
            if line.startswith("## "):
                big = line[3:].strip()
            elif line.startswith("### "):
                cur = f"{big}/{line[4:].strip()}" if big in ("半导体", "AI 硬件") else None
            elif cur and line.startswith("|"):
                cell = line.strip("|").split("|")[0].strip()
                if cell and any(cell == n or cell in n or n in cell for n in names.values()):
                    secs[cur] += 1
    except OSError:
        pass
    return {"theme": th.group(1).strip() if th else "", "codes": codes, "names": [names.get(c, c) for c in codes],
            "sectors": [s for s, _ in secs.most_common(8)], "src": f"skills/{uid}-skill/persona/stock_pool.md + md/rules.md(桃哥 2025 细分表, 参考)"}


def title(e, c):
    """facts 节标题: 名字(机械标签; 业绩风险; 截至 MM-DD 近 N 日) —— 名字在最前, 驱动器按名字切小节(MENTOR_HEAD)不受影响"""
    head = M.head(e["id"])
    if e["type"] == "UP":
        pl = up_pool(e["id"])
        return f"{head}(B站 UP, 视频披露; 无账本" + (f"; 关注: {pl['theme']}" if pl and pl.get("theme") else "") + ")"
    if not c:
        return f"{head}(账本数据不足, 暂无机械标签)"
    return f"{head}({'·'.join(c['style'])}; {'·'.join(c['perf'])}; 截至 {c['asof']} 近 {c['n_days']} 个交易日)"


def build(D):
    res = {"date": D, "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "cards": {}}
    for e in M.all():
        if e["type"] == "对照":
            continue
        c = card(e["id"], D) if e["type"] == "tzzb" else None
        res["cards"][e["id"]] = {"name": e["name"], "type": e["type"], "online": e.get("online"), "card": c, "title": title(e, c)}
        if e["type"] == "UP" and up_pool(e["id"]):
            res["cards"][e["id"]]["pool"] = up_pool(e["id"])
    OUT.mkdir(exist_ok=True)
    (OUT / f"{D}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 导师名片（机械统计，{D} 之前的数据；每天自动重算）", "",
         "> 全部从真实成交算出来，不是人写的评价。窗口 = 各自账本最近 60 个有净值的交易日；业绩 = 近 30 日净值收益、窗口内最大回撤、新开仓次日胜率。",
         "> 生成脚本 `scripts/tzzb/mentor_cards.py`；每天给链看的\"导师信号速览\"标题就用这里的标签。", "",
         "| 导师 | 类型 | 上线日 | 风格（打法 / 板块 / 持股 / 仓位） | 业绩与风险 | 常买 | 窗口 |", "|---|---|---|---|---|---|---|"]
    for k, v in res["cards"].items():
        c = v["card"]
        if c:
            L.append(f"| {v['name']} | {v['type']} | {v.get('online') or ''} | {' · '.join(c['style'])} | {' · '.join(c['perf'])} | {'、'.join(c['top_names'])} | {c['window'][0][5:]}~{c['window'][1][5:]}({c['n_days']} 天, 新开仓 {c['new_buys']} 笔) |")
        else:
            pl = v.get("pool")
            if pl:   # 10/19: UP 常讲股票池 + 衍生板块(md/rules.md 细分表)
                L.append(f"| {v['name']} | {v['type']} | {v.get('online') or ''} | B站 UP，视频披露，无账本；关注 {pl['theme']}；衍生细分：{'、'.join(pl['sectors']) or '—'} | | {'、'.join(pl['names'][:8])}… | 股票池 |")
            else:
                L.append(f"| {v['name']} | {v['type']} | {v.get('online') or ''} | {'B站 UP，视频披露，无账本' if v['type'] == 'UP' else '数据不足'} | | | |")
    latest = max((p.stem for p in OUT.glob("20*-*-*.json")), default=D)
    if D < latest:   # 10/18: as-of 回放算历史某天的名片时不覆盖给你看的 md(md 只展示最新一天)
        return res
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    return res


def latest_titles(D):
    """facts.mjs 调: D 之前最近一份名片的标题 {id: title}; 没有就现算"""
    fs = sorted(p for p in OUT.glob("*.json") if p.stem <= D) if OUT.exists() else []
    res = json.loads(fs[-1].read_text(encoding="utf-8")) if fs else build(D)
    return {k: v["title"] for k, v in res["cards"].items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    res = build(a.date)
    for k, v in res["cards"].items():
        print(v["title"])
    print(f"→ {(OUT / (a.date + '.json')).relative_to(ROOT)} / {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
