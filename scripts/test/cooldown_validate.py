# -*- coding: utf-8 -*-
"""cooldown_validate.py — paper v3 防超频冷却 / 去抖参数的零 token 验证(10/23 00:4x 用户令: 系数要测出来, 不能拍)

问题: ①出区间去抖 ②叫醒条件重新待命 ③重新出策略冷却 ④区间最窄宽度 —— 用"噪声单位 σ"做成动态, 系数取多少?
数据: 10/19~10/22 四天 3 秒盘口(downloads/market/<日>/book_snap.jsonl[.gz]; 股票 / 转债 / ETF) + v2 10/21~10/22 各本账真实写过的区间(results/_live/<日>/se_*/strategies)
σ(噪声单位, 价格单位) = max(A, B):  A = 近 5 日日内振幅((高−低)/昨收)中位 × 昨收(行情库日线, 只用 D 之前)
                                    B = 近 30 分钟里"5 分钟振幅"的中位(3 秒盘口自算; 不足 5 分钟时只用 A)
事件 = 价格穿过某个价位 L(区间上下沿 / 叫醒价位); 标签(只用来评估, 不参与规则):
   有意义 = 穿过后 HORIZON 分钟内, 价格继续往外走 ≥ MOVE × A(近 5 日振幅) → 值得叫醒模型重想
   噪声   = 没走出去
规则(每种参数一套):
   ①出区间: 越过边沿 ≥ m·σ 才开始计时, 持续 H 秒才叫醒; H = clamp(base × σ% / 3%, 30, 180)(base=0 表示固定 60 秒的现行规则)
   ②重新待命: 响过之后, 价格要退回到价位另一侧 ≥ r·σ 并待满 30 秒才重新待命(box=1: 价位在"近 30 分钟里、最近 5 分钟之前"的分时箱体内时, 要跌出箱底 / 涨出箱顶)
       现行 = 不成立满 60 秒就重新待命
   ④区间最窄: 区间半宽 < k·σ 时放宽到 k·σ
   ③冷却: 用 v2 真实"重定"时刻, 看不同冷却分钟数会压掉几次自由触发
产物: results/inv-stock/test/cooldown_validate.md + 打印
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/test/cooldown_validate.py [--move 0.3] [--horizon 15]
"""
import argparse
import bisect
import collections
import glob
import gzip
import json
import statistics as stt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]
OUT = ROOT / "results" / "inv-stock" / "test" / "cooldown_validate.md"
MIN_PER = 60   # 分钟线来源每档抽多少个票-日


def sec(t):
    return int(t[:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])


def tsec(s):   # 交易时间轴: 去掉午休, 11:30 和 13:00 接上
    return s if s <= 41400 else s - 5400


def load_tape(D):
    f = ROOT / "downloads" / "market" / D / "book_snap.jsonl"
    op, src = (open, f) if f.exists() else (gzip.open, f.with_suffix(".jsonl.gz"))
    T = collections.defaultdict(list)
    with op(src, "rt", encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            t, p = r.get("t", ""), r.get("p") or 0
            if p and ("09:30:00" <= t <= "11:30:00" or "13:00:00" <= t <= "14:57:00"):
                T[str(r["s"])[2:]].append((tsec(sec(t)), float(p)))
    for k in T:
        T[k].sort()
        dd, last = [], None   # 同一秒去重
        for x in T[k]:
            if x[0] != last:
                dd.append(x)
                last = x[0]
        T[k] = dd
    return T


def amp_A(cur, code, D):
    sym = ("sh" if code.startswith(("6", "5", "11")) else "sz") + code
    cur.execute("select high, low, pre_close from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit 5", (sym, D))
    rs = [(float(h) - float(l)) / float(pc) for h, l, pc in cur.fetchall() if h and l and pc]
    cur.execute("select close from kline_day where is_deleted=0 and symbol=%s and trade_date < %s order by trade_date desc limit 1", (sym, D))
    c = cur.fetchone()
    return (stt.median(rs), float(c[0])) if rs and c and c[0] else (None, None)


def tick_of(code):
    return 0.001 if code.startswith(("1", "5")) else 0.01


class Series:
    """一只票一天: 秒级价格 + 每分钟 σ_B"""
    def __init__(self, code, rows, A_pct, pc):
        self.code, self.ts, self.ps = code, [r[0] for r in rows], [r[1] for r in rows]
        self.A = A_pct * pc   # 价格单位
        self.Apct = A_pct
        self.tick = tick_of(code)
        mins = collections.OrderedDict()
        for t, p in rows:
            m = t // 60
            lo, hi = mins.get(m, (p, p))
            mins[m] = (min(lo, p), max(hi, p))
        self.mk = list(mins.keys())
        self.mb = list(mins.values())
        self.B = {}
        for j, m in enumerate(self.mk):
            w = [(self.mk[i], self.mb[i]) for i in range(max(0, j - 29), j + 1)]
            if len(w) < 5:
                self.B[m] = None
                continue
            rng = sorted(max(b[1] for _, b in w[i:i + 5]) - min(b[0] for _, b in w[i:i + 5]) for i in range(len(w) - 4))
            self.B[m] = rng[len(rng) // 2]

    def sigma(self, t, use_B=True):
        b = self.B.get(t // 60) if use_B else None
        return max(self.A, b or 0)

    def box(self, t):
        """近 30 分钟里、最近 5 分钟之前那段分时的箱体; 不够 10 分钟返回 None"""
        m = t // 60
        j = bisect.bisect_right(self.mk, m) - 1
        old = self.mb[max(0, j - 29):max(0, j - 4)]
        if len(old) < 5:
            return None
        return min(b[0] for b in old), max(b[1] for b in old)


def label(s, i, L, up, move, horizon):
    """第 i 个点穿过价位 L 后 horizon 分钟内往外走 ≥ move×A?"""
    t0 = s.ts[i]
    need = move * s.A
    j = i
    while j < len(s.ts) and s.ts[j] - t0 <= horizon * 60:
        if (s.ps[j] - L if up else L - s.ps[j]) >= need:
            return True
        j += 1
    return False


# ---------------------------------------------------------------- ① 出区间
def band_fire(s, i0, i1, lo, hi, m, base, use_B):
    """区间 [lo, hi] 在 [i0, i1) 有效; 返回 (第一次叫醒的下标, 方向) 或 None"""
    out_since, side = None, None
    for i in range(i0, i1):
        t, p = s.ts[i], s.ps[i]
        sg = s.sigma(t, use_B)
        mg = m * sg
        cur = "up" if p > hi + mg else ("dn" if p < lo - mg else None)
        if cur is None:
            out_since, side = None, None
            continue
        if cur != side:
            out_since, side = t, cur
        if base == 0:
            H = 60
        else:
            H = min(180, max(30, base * (sg / s.ps[i]) / 0.03))
        if t - out_since >= H:
            return i, side
    return None


def first_cross(s, i0, i1, lo, hi):
    for i in range(i0, i1):
        p = s.ps[i]
        if p > hi:
            return i, "up"
        if p < lo:
            return i, "dn"
    return None


def eval_band(cases, m, base, use_B, kmin, move, horizon):
    """cases: [(s, i0, i1, lo, hi)] → 叫醒次数 / 其中有意义 / 噪声 / 有意义的穿越被漏掉 / 平均延迟秒"""
    fire = good = bad = miss = 0
    delays = []
    for s, i0, i1, lo, hi in cases:
        fc = first_cross(s, i0, i1, lo, hi)   # "有意义 / 漏掉"按模型原本写的区间判(放宽是执行器的事, 不能改变"该不该叫醒"的标准)
        meaningful = fc is not None and label(s, fc[0], hi if fc[1] == "up" else lo, fc[1] == "up", move, horizon)
        if kmin:
            mid, half = (lo + hi) / 2, (hi - lo) / 2
            need = kmin * s.sigma(s.ts[i0], use_B)
            if half < need:
                lo, hi = mid - need, mid + need
        f = band_fire(s, i0, i1, lo, hi, m, base, use_B)
        if f:
            fire += 1
            ok = label(s, f[0], hi if f[1] == "up" else lo, f[1] == "up", move, horizon) or meaningful
            good += ok
            bad += not ok
            if fc:
                delays.append(s.ts[f[0]] - s.ts[fc[0]])
        elif meaningful:
            miss += 1
    return {"叫醒": fire, "有意义": good, "噪声": bad, "漏掉有意义": miss, "延迟中位秒": round(stt.median(delays)) if delays else None}


# ---------------------------------------------------------------- ② 重新待命
def eval_rearm(levels, rule, r, box, move, horizon, use_B=True):
    """levels: [(s, i0, L, up)] 从 i0 起盯 "价 ≥ L"(up) 或 "价 ≤ L"; 一直盯到收盘(模拟模型每次都原样写回)"""
    fire = good = bad = 0
    eps = hit_eps = 0
    for s, i0, L, up in levels:
        # 一波行情 = 有意义的穿越; 距上一个有意义穿越 < horizon 分钟的算同一波(去重)
        ep_start, last_m, prev = [], None, None
        for i in range(i0, len(s.ts)):
            c_ = s.ps[i] >= L if up else s.ps[i] <= L
            if c_ and prev is False and label(s, i, L, up, move, horizon):
                if last_m is None or s.ts[i] - last_m > horizon * 60:
                    ep_start.append(s.ts[i])
                last_m = s.ts[i]
            prev = c_
        fires = []
        armed, since, false_since = None, None, None
        for i in range(i0, len(s.ts)):
            t, p = s.ts[i], s.ps[i]
            cond = p >= L if up else p <= L
            if armed is None:   # 写下时: 已成立 = 不待命
                armed = not cond
                since = None
                continue
            if cond:
                since = false_since = None
                if armed:
                    fire += 1
                    fires.append(t)
                    ok = label(s, i, L, up, move, horizon)
                    good += ok
                    bad += not ok
                    armed = False
                continue
            if armed:
                continue
            if rule.startswith("fixed"):   # fixed60 / fixed300 / fixed600: 不成立满 N 秒
                since = t if since is None else since
                if t - since >= int(rule[5:]):
                    armed = True
                continue
            if rule.startswith("dynor"):   # 退开 rσ 待 30 秒, 或者 不成立满 N 秒(兜底: 抓"磨回去再突破"的新一波)
                false_since = t if false_since is None else false_since
                if t - false_since >= int(rule[5:]):
                    armed = True
                    continue
            sg = s.sigma(t, use_B)
            gap = max(2 * s.tick, r * sg)
            if box:
                bx = s.box(t)
                if bx and bx[0] < L < bx[1]:
                    gap = max(gap, ((L - bx[0]) if up else (bx[1] - L)) + s.tick)
            away = (L - p if up else p - L) >= gap
            if away:
                since = t if since is None else since
                if t - since >= 30:
                    armed = True
            else:
                since = None
        eps += len(ep_start)
        hit_eps += sum(1 for e in ep_start if any(e <= f <= e + horizon * 60 for f in fires))
    return {"叫醒": fire, "有意义": good, "噪声": bad, "行情波数": eps, "抓到波数": hit_eps}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--move", type=float, default=0.3)
    ap.add_argument("--horizon", type=int, default=15)
    a = ap.parse_args()
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("use investment_market")
    S = {}   # (D, code) → Series
    for D in DAYS:
        T = load_tape(D)
        for code, rows in T.items():
            if len(rows) < 1500:
                continue
            A, pc = amp_A(cur, code, D)
            if not A:
                continue
            S[(D, code)] = Series(code, rows, A, pc)
        print(D, "票", sum(1 for k in S if k[0] == D), flush=True)

    # 盯盘名单几乎都是活跃票 → 补"分钟线"来源(kline_minute 10/12 起关注集 900+ 只, 开高低收 → 每分钟 4 个点), 按 A 分三档各抽 MIN_PER 个票-日
    import random
    random.seed(7)
    cur.execute("select distinct trade_date from kline_minute where symbol='sh000001' and trade_date >= '2026-10-12' order by trade_date")
    mdays = [str(x[0]) for x in cur.fetchall()]
    cur.execute("select distinct symbol from kline_minute where trade_date >= '2026-10-12' and (symbol like 'sh6%%' or symbol like 'sz0%%' or symbol like 'sz3%%')")
    syms = [x[0] for x in cur.fetchall()]
    random.shuffle(syms)
    need = {"安静": MIN_PER, "中等": MIN_PER, "活跃": MIN_PER}
    for sym in syms:
        if not any(need.values()):
            break
        D = random.choice(mdays)
        code = sym[2:]
        if (D, code) in S:
            continue
        A, pc = amp_A(cur, code, D)
        if not A:
            continue
        bk = "安静" if A < 0.025 else ("中等" if A < 0.05 else "活跃")
        if not need[bk]:
            continue
        cur.execute("select date_format(bar_time,'%%H:%%i'), open, high, low, close from kline_minute where is_deleted=0 and trade_date=%s and symbol=%s order by bar_time", (D, sym))
        rows = []
        for hm, o, h, l, c in cur.fetchall():
            if not (o and c) or not ("09:30" <= hm <= "11:29" or "13:00" <= hm <= "14:56"):
                continue
            t0 = tsec(int(hm[:2]) * 3600 + int(hm[3:]) * 60)
            o, h, l, c = float(o), float(h), float(l), float(c)
            mid = (l, h) if abs(o - l) < abs(o - h) else (h, l)
            rows += [(t0, o), (t0 + 20, mid[0]), (t0 + 40, mid[1]), (t0 + 59, c)]
        if len(rows) < 800:
            continue
        S[(D + "·分钟线", code)] = Series(code, rows, A, pc)
        need[bk] -= 1
    print("补分钟线票-日", sum(1 for k in S if k[0].endswith("分钟线")), flush=True)

    def bucket(s):
        return "安静(<2.5%)" if s.Apct < 0.025 else ("中等(2.5~5%)" if s.Apct < 0.05 else "活跃(≥5%)")
    # ---- ① 区间: 真实 v2 区间 + 合成区间(半宽按 v2 真实宽度分位抽: 1.4 / 2.3 / 3.8 / 4.9%)
    real = []
    for D in ("2026-10-21", "2026-10-22"):
        for d in glob.glob(str(ROOT / "results" / "_live" / D / "se_*")):
            vs = sorted(glob.glob(d + "/strategies/*.json"))
            for j, f in enumerate(vs):
                try:
                    st_ = (json.loads(Path(f).read_text(encoding="utf-8")).get("strategy") or {})
                except ValueError:
                    continue
                hm = Path(f).stem.split("_")[-1]
                t0 = tsec(int(hm[:2]) * 3600 + int(hm[2:]) * 60)
                t1 = tsec(int(Path(vs[j + 1]).stem.split("_")[-1][:2]) * 3600 + int(Path(vs[j + 1]).stem.split("_")[-1][2:]) * 60) if j + 1 < len(vs) else 10 ** 9
                for x in st_.get("codes") or []:
                    b, s = x.get("band"), S.get((D, str(x.get("code"))))
                    if not b or not s or not (0 < b[0] < b[1]):
                        continue
                    i0 = bisect.bisect_left(s.ts, max(t0, tsec(34200)))
                    i1 = bisect.bisect_left(s.ts, t1)
                    if i1 - i0 > 20:
                        real.append((s, i0, i1, float(b[0]), float(b[1])))
    syn = []
    for (D, code), s in S.items():
        for k, t0 in enumerate(range(tsec(34200) + 300, tsec(52200), 1800)):   # 每 30 分钟一个锚点, 区间管 30 分钟
            i0 = bisect.bisect_left(s.ts, t0)
            i1 = bisect.bisect_left(s.ts, t0 + 1800)
            if i1 - i0 < 50:
                continue
            p = s.ps[i0]
            half = (0.014, 0.023, 0.038, 0.049)[k % 4] * p
            syn.append((s, i0, i1, p - half, p + half))
    print("区间样本: 真实 v2", len(real), "合成", len(syn), flush=True)
    L = [f"# 冷却 / 去抖参数零 token 验证(10/23 凌晨; 标签: 穿过后 {a.horizon} 分钟内再往外走 ≥ {a.move}×近 5 日振幅 = 有意义)", "",
         f"数据: {', '.join(DAYS)} 3 秒盘口 {len(S)} 个票-日; v2 真实区间段 {len(real)} 个; 合成区间段 {len(syn)} 个(每 30 分钟一个锚点, 半宽 1.4~4.9% 轮换 = v2 真实宽度 P10~P75)", ""]
    grid1 = [("现行: 固定 60 秒", 0, 0, True, 0)] + [(f"m={m} 固定 60 秒", m, 0, True, 0) for m in (0.05, 0.1)] + \
            [(f"m={m} base={b}", m, b, True, 0) for m in (0, 0.05, 0.1, 0.2) for b in (15, 30, 60)] + \
            [("只用 A: m=0.05 base=30", 0.05, 30, False, 0), ("m=0.05 base=30 + 最窄 0.5σ", 0.05, 30, True, 0.5), ("m=0.1 base=30 + 最窄 0.5σ", 0.1, 30, True, 0.5)]
    for name, cases in (("① 出区间 · v2 真实区间", real), ("① 出区间 · 合成区间", syn)):
        L += [f"## {name}", "", "| 规则 | 全部: 叫醒 / 有意义 / 噪声 / 漏掉有意义 / 延迟秒 | 安静 | 中等 | 活跃 |", "|---|---|---|---|---|"]
        for lab, m, b, uB, k in grid1:
            row = [lab]
            for bk in (None, "安静(<2.5%)", "中等(2.5~5%)", "活跃(≥5%)"):
                cs = [c for c in cases if bk is None or bucket(c[0]) == bk]
                r = eval_band(cs, m, b, uB, k, a.move, a.horizon)
                row.append(f"{r['叫醒']} / {r['有意义']} / {r['噪声']} / {r['漏掉有意义']} / {r['延迟中位秒']}")
            L.append("| " + " | ".join(row) + " |")
            print(name, lab, row[1], flush=True)
        L.append("")
    # ---- ④ 区间最窄(真实 v2 区间; ① 用现行 60 秒, 看放宽本身的效果)
    L += ["## ④ 区间最窄宽度 · v2 真实区间(① 用现行固定 60 秒)", "", "| 最窄半宽 | 叫醒 / 有意义 / 噪声 / 漏掉有意义 / 延迟秒 | 被放宽的区间数 |", "|---|---|---|"]
    for k in (0, 0.25, 0.5, 0.75, 1.0):
        r = eval_band(real, 0, 0, True, k, a.move, a.horizon)
        nw = sum(1 for s, i0, i1, lo, hi in real if (hi - lo) / 2 < k * s.sigma(s.ts[i0]))
        L.append(f"| {k}σ | {r['叫醒']} / {r['有意义']} / {r['噪声']} / {r['漏掉有意义']} / {r['延迟中位秒']} | {nw} |")
        print("④", k, r, nw, flush=True)
    L.append("")
    # ---- ② 重新待命: 每个票-日 4 个价位(10:00 时价 ±1%、±2%; 冲高看 ≥, 跌破看 ≤), 一直盯到收盘
    lv = []
    for (D, code), s in S.items():
        i0 = bisect.bisect_left(s.ts, tsec(36000))
        if i0 >= len(s.ts) - 100:
            continue
        p = s.ps[i0]
        for d in (0.01, 0.02):
            lv += [(s, i0, round(p * (1 + d), 3), True), (s, i0, round(p * (1 - d), 3), False)]
    # 再加"箱体中间价位"(10:00 时价本身, 冲高 / 跌破各一): 最容易来回穿
    for (D, code), s in S.items():
        i0 = bisect.bisect_left(s.ts, tsec(36000))
        if i0 < len(s.ts) - 100:
            lv += [(s, i0, s.ps[i0], True), (s, i0, s.ps[i0], False)]
    L += [f"## ② 重新待命(价位 {len(lv)} 个: 10:00 价 ±1% / ±2% / 本身, 冲高和跌破各一; 模拟模型每次原样写回、盯到收盘)", "",
          "| 规则 | 全部: 叫醒 / 有意义 / 噪声 / 抓到行情波数/总波数 | 安静 | 中等 | 活跃 |", "|---|---|---|---|---|"]
    for lab, rule, r, box in [("现行: 不成立满 60 秒", "fixed60", 0, False), ("不成立满 5 分钟", "fixed300", 0, False), ("不成立满 10 分钟", "fixed600", 0, False)] + \
            [(f"退开 {r}σ{' + 箱体' if b else ''}", "dyn", r, b) for r in (0.1, 0.15, 0.2, 0.25, 0.5) for b in (False, True)] + \
            [(f"退开 {r}σ 或 不成立满 {n // 60} 分钟", f"dynor{n}", r, False) for r in (0.25, 0.5) for n in (300, 600)]:
        row = [lab]
        for bk in (None, "安静(<2.5%)", "中等(2.5~5%)", "活跃(≥5%)"):
            ls = [x for x in lv if bk is None or bucket(x[0]) == bk]
            q = eval_rearm(ls, rule, r, box, a.move, a.horizon)
            row.append(f"{q['叫醒']} / {q['有意义']} / {q['噪声']} / {q['抓到波数']}/{q['行情波数']}")
        L.append("| " + " | ".join(row) + " |")
        print("②", row, flush=True)
    L.append("")
    # ---- ③ 冷却: v2 真实自由触发(出区间 / 翻转 / 心跳)时刻, 不同冷却会压掉几次
    gaps = []
    for D in ("2026-10-21", "2026-10-22"):
        for d in glob.glob(str(ROOT / "results" / "_live" / D / "se_*")):
            ts = []
            for l in Path(d, "events.jsonl").read_text(encoding="utf-8").splitlines() if Path(d, "events.jsonl").exists() else []:
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                if e.get("kind") == "重定" and ("出区间" in e.get("why", "") or "翻转" in e.get("why", "") or "开盘实况" in e.get("why", "")):
                    ts.append(sec(e["t"]))
            ts.sort()
            gaps += [(b - a_) / 60 for a_, b in zip(ts, ts[1:])]
    if gaps:
        gaps.sort()
        L += ["## ③ 重新出策略冷却(v2 10/21~10/22 真实自由触发的相邻间隔, n=%d)" % len(gaps), "",
              "间隔分位(分钟) P10 / P25 / 中位 / P75: " + " / ".join(f"{gaps[int(len(gaps) * q)]:.1f}" for q in (.1, .25, .5, .75)), "",
              "| 冷却 | 会被压掉(推迟)的自由触发占比 |", "|---|---|"]
        for c in (2, 3, 5, 8, 10):
            L.append(f"| {c} 分钟 | {sum(1 for g in gaps if g < c) / len(gaps):.0%} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("→", OUT)


if __name__ == "__main__":
    main()
