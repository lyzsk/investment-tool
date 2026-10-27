# -*- coding: utf-8 -*-
"""expect.py — 明日备案(10/26 晚用户令: "零散的知识和数据没整合成一个预期; 先要有备案, 盘前首跑是各 skill 分开视角, 不是整合项目的视角"; 零 token)

回答三件事(全部机械, 只用 ≤D 的数据; 每个结论带 n / 概率 / 不自信点):
  ① 情绪聚焦: D 及之前 5 天最活跃的题材 + 生命周期阶段(theme_life, 来源 md「涨停分析」1/15 起 ~185 天)
  ② 流转关系 + 明日聚焦: 历史上"今天这个阶段 / 家数档"的题材, 明天还有 ≥3 家涨停的概率(延续率); 今天强的题材, 历史上第二天带起哪些题材(流转 lift)
     → 明日聚焦分 = 延续概率 + 流转加分, 取前 6 个题材
  ③ 备案候选: 每个聚焦题材的梯队(近 5 天这个题材涨停过的票, 板数高的先)+ **题材套利债**(用户 10/26: 每个活跃题材都有一只可以套利的债):
     正股近 20 天在这个题材涨停 / 大涨过的转债, 按 D 当天转债成交额排(主线转债 = 成交额最大, taoge B95), 带溢价率 / 正股今天涨停没有
产物: results/_live/<D 的下一交易日>/expect.json + expect.md
消费: chain_steps.pool 候选池来源「备案·<题材>」(股票给拟人线, 转债给土豆线; 排在导师本人前) · 01 事实里「明日备案」一节(全线共用的项目视角)
用法: python expect.py [--date D(默认今天, 盘后口径含 D)] [--show]
"""
import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line" / "tools")]
import theme_life as TL  # noqa: E402

LIVE = ROOT / "results" / "_live"
MKT = ROOT / "downloads" / "market"
TOP_N, PER_THEME, CB_PER = 6, 4, 2


def next_day(D):
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        import trade_cal
        return trade_cal.next_trade_day(D)
    except Exception:   # noqa: BLE001
        d = dt.date.fromisoformat(D) + dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        return d.isoformat()


def _bucket(n):
    return "≥8" if n >= 8 else "4~7" if n >= 4 else "1~3"


def history(D):
    """历史(< D)每题材每天的涨停家数 → 延续率表 + 流转表"""
    rows = [r for r in TL.rows_canon() if r[0] <= D]
    days = sorted({r[0] for r in rows})
    cnt = defaultdict(lambda: defaultdict(int))   # d → theme → 涨停家数
    for r in rows:
        if r[5]:
            cnt[r[0]][r[1]] += 1
    cont = defaultdict(lambda: [0, 0])   # (家数档, 是否比前一天多) → [次日 ≥3 家次数, 样本]
    trans = defaultdict(lambda: defaultdict(int))   # A(今天 ≥4 家) → B(明天 ≥3 家)次数
    base = defaultdict(int)   # B 明天 ≥3 家的天数(基线)
    a_days = defaultdict(int)
    for i in range(1, len(days) - 1):
        d0, d1, dn = days[i - 1], days[i], days[i + 1]
        for th, n in cnt[d1].items():
            k = (_bucket(n), n > cnt[d0].get(th, 0))
            cont[k][1] += 1
            cont[k][0] += cnt[dn].get(th, 0) >= 3
        hot_tomorrow = {th for th, n in cnt[dn].items() if n >= 3}
        for th in hot_tomorrow:
            base[th] += 1
        for a, n in cnt[d1].items():
            if n >= 4:
                a_days[a] += 1
                for b in hot_tomorrow:
                    if b != a:
                        trans[a][b] += 1
    nd = max(1, len(days) - 2)
    return days, cnt, cont, trans, base, a_days, nd


def cb_by_stock(D):
    f = MKT / D / "cb_facts.jsonl"
    out = defaultdict(list)
    if f.exists():
        for l in f.open(encoding="utf-8"):
            try:
                x = json.loads(l)
            except ValueError:
                continue
            if x.get("phase") in ("到期", "强赎") or (x.get("days_to_expire") or 99) < 15:
                continue
            out[str(x.get("stock"))].append(x)
    return out


def _flag(k, d=""):
    try:
        for l in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            kk, _, v = l.split("#")[0].partition("=")
            if kk.strip() == k:
                return v.strip()
    except OSError:
        pass
    return d


def kw_theme(kw, D, look=60, n=12):
    """点名题材(10/26 用户: 固态电池进了明日看 → 列相关个股预案): 近 look 天涨停分析里 题材名或上涨逻辑含 kw 的票(同义表会把 固态电池 并进 锂电池, 所以按原文找)
    → [(代码, 名称, 出现次数, 最近日, 最高板)], 最近出现 + 次数多的在前"""
    days = sorted({r[0] for r in TL.rows_canon() if r[0] <= D})[-look:]
    code_of = {}
    for r in TL.rows_canon():
        if r[3]:
            code_of[r[2]] = r[3]
    agg = {}
    for r in TL.parse_md():
        if r[0] not in days or not (kw in (r[1] or "") or kw in (r[7] or "")):
            continue
        nm = str(r[2]).split("(")[0].split("（")[0].strip().replace("\\", "")
        c = r[3] or code_of.get(r[2]) or code_of.get(nm)
        if not c or c[:2] in ("92", "83", "87", "43"):   # 北交所不做
            continue
        a = agg.setdefault(c, {"名": nm, "次": 0, "最近": "", "板": 0})
        a["次"] += 1
        a["最近"] = max(a["最近"], r[0])
        a["板"] = max(a["板"], r[4] or 0)
    rk = sorted(agg.items(), key=lambda kv: (kv[1]["最近"], kv[1]["次"], kv[1]["板"]), reverse=True)[:n]
    return [(c, v["名"], v["次"], v["最近"], v["板"]) for c, v in rk]


def build(D):
    days, cnt, cont, trans, base, a_days, nd = history(D)
    if D not in cnt:
        return {"err": f"md 涨停分析里还没有 {D}(check md 跑完再算)"}
    today = cnt[D]
    prev = cnt[days[days.index(D) - 1]] if days.index(D) > 0 else {}
    # ② 明日聚焦分
    cand = set(today) | {t for d in days[-5:] for t in cnt[d]}
    score = {}
    for th in cand:
        n = today.get(th, 0)
        if n:
            c_ok, c_n = cont[(_bucket(n), n > prev.get(th, 0))]
            p_cont = c_ok / c_n if c_n else 0
        else:
            p_cont, c_n = 0.0, 0
        lift, src = 0.0, []
        for a, na in today.items():
            if na >= 4 and a != th and a_days[a] >= 5:
                pb = trans[a].get(th, 0) / a_days[a]
                p0 = base.get(th, 0) / nd
                if pb > p0 * 1.5 and trans[a].get(th, 0) >= 3:
                    lift = max(lift, pb - p0)
                    src.append(f"{a}→{th} {trans[a][th]}/{a_days[a]} 次(基线 {p0:.0%})")
        life = TL.life(th, D, after=True, rel=False)
        score[th] = {"题材": th, "今天涨停": n, "昨天涨停": prev.get(th, 0), "阶段": life.get("阶段"), "本波第几天": life.get("本波第几天"),
                     "明天≥3家·延续概率": round(p_cont, 2), "延续样本n": c_n, "流转加分": round(lift, 2), "流转依据": src[:3],
                     "分": round(p_cont + lift, 3)}
    focus = sorted(score.values(), key=lambda x: -x["分"])[:TOP_N]
    # ③ 梯队 + 套利债
    rows = [r for r in TL.rows_canon() if r[0] in days[-20:]]
    cbs = cb_by_stock(D)
    seeds_stock, seeds_cb = [], []
    for f_ in focus:
        th = f_["题材"]
        mem = defaultdict(lambda: {"板": 0, "最近": "", "名": ""})
        for r in rows:
            if r[1] == th and r[0] in days[-5:] and r[3]:
                m = mem[r[3]]
                m["板"], m["最近"], m["名"] = max(m["板"], r[4] or 0), max(m["最近"], r[0]), r[2]
        ladder = sorted(mem.items(), key=lambda kv: (-kv[1]["板"], kv[1]["最近"]), reverse=False)
        ladder = sorted(ladder, key=lambda kv: (-kv[1]["板"], -int(kv[1]["最近"].replace("-", ""))))[:PER_THEME]
        f_["梯队"] = [f"{v['名']}({c}) {v['板']}板 最近 {v['最近'][5:]}" for c, v in ladder]
        seeds_stock += [(c, th) for c, _ in ladder]
        # 套利债: 正股近 20 天在这个题材出现过
        stk20 = {r[3] for r in rows if r[1] == th and r[3]}
        cl = [x for s in stk20 for x in cbs.get(s, [])]
        cl.sort(key=lambda x: -(x.get("amount") or 0))
        f_["套利债"] = [f"{x['name']}({x['code']}) 正股 {x['stock_name']}{'(今天涨停)' if x.get('stock_limit_up') else ''} 成交额 {(x.get('amount') or 0) / 1e8:.1f} 亿 溢价率 {(x.get('premium') or 0) * 100:.0f}%"
                       for x in cl[:CB_PER]]
        seeds_cb += [(x["code"], th) for x in cl[:CB_PER]]
    # 点名题材(chain_flags EXPECT_FORCE=固态电池,…: 导师 / UP / 你说明天看的) + 今天首日且 ≥2 家涨停的新题材 → 个股预案 + 套利债
    force = [x.strip() for x in _flag("EXPECT_FORCE").split(",") if x.strip()]
    newt = [f["题材"] for f in score.values() if f["今天涨停"] >= 2 and str(f.get("阶段") or "").startswith("首日") and f["题材"] not in {x["题材"] for x in focus}]
    plans = []
    for kw in force + newt[:3]:
        st_ = kw_theme(kw, D)
        cl = sorted([x for c, *_ in st_ for x in cbs.get(c, [])], key=lambda x: -(x.get("amount") or 0))[:CB_PER]
        plans.append({"题材": kw, "来源": "点名(EXPECT_FORCE)" if kw in force else "今天新题材(首日 ≥2 家)",
                      "个股": [f"{nm}({c}) 近 60 天出现 {k} 次 · 最近 {d[5:]}" + (f" · 最高 {b} 板" if b else "") for c, nm, k, d, b in st_],
                      "套利债": [f"{x['name']}({x['code']}) 正股 {x['stock_name']}{'(今天涨停)' if x.get('stock_limit_up') else ''} 成交额 {(x.get('amount') or 0) / 1e8:.1f} 亿 溢价率 {(x.get('premium') or 0) * 100:.0f}%" for x in cl]})
        seeds_stock += [(c, kw) for c, *_ in st_[:5]]
        seeds_cb += [(x["code"], kw) for x in cl]
    nxt = next_day(D)
    out = {"D": D, "for": nxt, "built": dt.datetime.now().isoformat(timespec="seconds"), "样本天数": len(days),
           "情绪聚焦(近5日)": TL.top(D, after=True, n=10)["近 5 日最活跃题材"], "明日聚焦": focus,
           "题材预案": plans, "候选": {"股票": seeds_stock, "转债": seeds_cb},
           "不自信点": ["题材名来自 md 涨停分析的人工归类, 同一题材不同天叫法不同时靠同义表合并, 会漏", "延续率按 家数档 × 是否比前一天多 分组, 没分主线 / 非主线, 也没看大盘",
                    "流转只看'今天 ≥4 家的题材 → 明天 ≥3 家', 样本 ~185 天, 题材少的组 n 很小", "套利债按'正股近 20 天在这个题材涨停 / 大涨过'认, 不是题材成分股全集"]}
    d_ = LIVE / nxt
    d_.mkdir(parents=True, exist_ok=True)
    (d_ / "expect.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (d_ / "expect.md").write_text(render(out), encoding="utf-8")
    return out


def render(o):
    L = [f"## 明日备案({o['for']}; 按 {o['D']} 收盘 + md 涨停分析 {o['样本天数']} 天历史机械算, 全线共用的项目视角)", "",
         "### 情绪聚焦(近 5 日)"] + [f"- {x}" for x in o["情绪聚焦(近5日)"][:8]] + ["", "### 明日聚焦(延续概率 + 流转; 分高在前)"]
    for f in o["明日聚焦"]:
        L.append(f"- **{f['题材']}**: 今天 {f['今天涨停']} 家(昨天 {f['昨天涨停']}) · {f['阶段']} · 本波第 {f['本波第几天']} 天 · 明天 ≥3 家概率 {f['明天≥3家·延续概率']:.0%}(同档历史 n={f['延续样本n']})"
                 + (f" · 流转: {'; '.join(f['流转依据'])}" if f["流转依据"] else ""))
        if f.get("梯队"):
            L.append(f"  梯队: {' / '.join(f['梯队'])}")
        if f.get("套利债"):
            L.append(f"  套利债: {' / '.join(f['套利债'])}")
    if o.get("题材预案"):
        L += ["", "### 题材预案(点名题材 / 今天新题材; 个股 = 近 60 天涨停分析里题材名或上涨逻辑提到它的票)"]
        for p_ in o["题材预案"]:
            L.append(f"- **{p_['题材']}**({p_['来源']}): " + (" / ".join(p_["个股"]) or "近 60 天没找到"))
            if p_["套利债"]:
                L.append(f"  套利债: {' / '.join(p_['套利债'])}")
    L += ["", "不自信点: " + "; ".join(o["不自信点"])]
    return "\n".join(L)


def load(D):
    try:
        return json.loads((LIVE / D / "expect.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    o = build(a.date)
    print(render(o) if "err" not in o else o["err"])


if __name__ == "__main__":
    main()
