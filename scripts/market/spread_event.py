# -*- coding: utf-8 -*-
"""spread_event.py — "大小盘剪刀差"事件(白线 / 黄线穿越; 10/21 晚用户定: 黄线用国证2000 代中证2000, 和上证比; 零 token)

定义: 剪刀差 s = 国证2000 当日涨跌% − 上证当日涨跌%(正 = 中小票强 = 白线在黄线下方; 负 = 权重强 = 白线在黄线上方)
事件: s 穿越 0 轴后, 连续 H 分钟都在新的一侧且 |s| ≥ M 个百分点 → 在确认那一分钟记一次"白线下穿黄线(转正) / 上穿(转负)"
       推荐(用户认): H = 3 分钟, M = 0.1 个百分点
实时: check(rows_sh, rows_gz, state) 由执行器按 3 秒指数(index_snap.jsonl)喂分钟收盘 → 返回新事件或 None(还没接入执行器, 等用户定)
回测: --backtest 用 downloads/market/_minute_hist/ 的 上证 sh000001 + 国证2000 sz399303 1 分钟线(通达信), 对比几档 (H, M):
      每天触发几次 / 触发后 30 分钟剪刀差是否继续同向(有没有信息量, 对照随机时刻) / 触发后 30 分钟上证涨跌 / 和 θ 指数事件(index_event, 系数 0.35)重叠多少
用法: python spread_event.py --backtest | --selftest
"""
import argparse
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
H_DIR = ROOT / "downloads" / "market" / "_minute_hist"
sys.path.insert(0, str(Path(__file__).resolve().parent))
H_DEF, M_DEF = 3, 0.1


def load(sym):
    by = defaultdict(dict)
    for l in (H_DIR / f"{sym}.jsonl").open(encoding="utf-8"):
        r = json.loads(l)
        by[r["tradeDate"]][r["barTime"][11:16].replace(":", "")] = float(r["close"])
    return by


def mins():
    out, h, m = [], 9, 31
    while (h, m) <= (15, 0):
        hm = f"{h:02d}{m:02d}"
        if not ("1130" < hm < "1301"):
            out.append(hm)
        m += 1
        if m == 60:
            h, m = h + 1, 0
    return out


MINS = mins()   # 09:31~11:30 + 13:01~15:00 共 240 个交易分钟


def spread_day(sh, gz, D, P):
    """→ (上证当日涨跌% 序列, 剪刀差序列), 下标同 MINS; 缺分钟用前值"""
    pcs, pcg = sh[P][max(sh[P])], gz[P][max(gz[P])]
    a, s, ls, lg = [], [], None, None
    for m in MINS:
        ls = sh[D].get(m, ls)
        lg = gz[D].get(m, lg)
        if ls is None or lg is None:
            a.append(None)
            s.append(None)
            continue
        ps, pg = (ls / pcs - 1) * 100, (lg / pcg - 1) * 100
        a.append(ps)
        s.append(pg - ps)
    return a, s


def events(s, H=H_DEF, M=M_DEF):
    """穿越 0 轴后连续 H 分钟在新的一侧且 |s| ≥ M → [(下标, +1 转正 / −1 转负)]; 第一次站稳只定"起始侧", 不算事件"""
    ev, side, run, cand = [], None, 0, None
    for i, x in enumerate(s):
        if x is None:
            continue
        sd = 1 if x > 0 else -1
        if abs(x) >= M:
            if cand == sd:
                run += 1
            else:
                cand, run = sd, 1
            if run >= H and sd != side:
                if side is not None:
                    ev.append((i, sd))
                side = sd
        else:
            cand, run = None, 0
    return ev


def check(seq, state, H=H_DEF, M=M_DEF):
    """实时用: seq = 当天到此刻的剪刀差分钟序列; state = {"n": 已处理到的下标, "seen": 已报事件数}; → 新事件 (下标, 方向) 或 None"""
    ev = events(seq, H, M)
    if len(ev) > state.get("seen", 0):
        state["seen"] = len(ev)
        return ev[-1]
    return None


def backtest():
    import index_event as IE
    sh, gz = load("sh000001"), load("sz399303")
    days = sorted(set(sh) & set(gz))
    days = [d for d in days if len(sh[d]) >= 200 and len(gz[d]) >= 200]
    pairs = [(days[k], days[k - 1]) for k in range(1, len(days))]
    print(f"数据: 上证 + 国证2000 1 分钟线 {pairs[0][0]} ~ {pairs[-1][0]} 共 {len(pairs)} 天")
    # θ 事件(系数 0.35, 加码 10%, 心跳 30)
    th_ev = {}
    for D, _ in pairs:
        try:
            px = IE._px("SH", D)
            th_ev[D] = [i for i, _ in IE.simulate(px, IE.scheme_thetas(("E", 0.35, 0.0), D, px, "SH"), hb=30, esc=0.10, n_free=4)]
        except Exception:   # noqa: BLE001
            th_ev[D] = None
    S = {D: spread_day(sh, gz, D, P) for D, P in pairs}
    # 基准: 随机时刻"按近 5 分钟剪刀差方向"看 30 分钟后是否继续
    rnd = random.Random(7)
    base_c, base_sh = [], []
    for D, (a, s) in S.items():
        for _ in range(30):
            i = rnd.randrange(5, 210)
            if None in (s[i], s[i - 5], s[i + 30], a[i], a[i + 30]):
                continue
            d = 1 if s[i] >= s[i - 5] else -1
            base_c.append(d * (s[i + 30] - s[i]) > 0)
            base_sh.append(a[i + 30] - a[i])
    print(f"基准(随机时刻, 按近 5 分钟剪刀差方向): 30 分钟后剪刀差继续同向 {sum(base_c) / len(base_c) * 100:.0f}%; 上证 30 分钟平均变动 {st.mean(base_sh):+.3f} 个百分点")
    print("| H 分钟 | M 个百分点 | 日均 | P90 | 最多 | 0 次的天 | 30 分钟后剪刀差继续同向 | 平均延续 | 转正后上证 30 分钟 | 转负后上证 30 分钟 | 和 θ 事件 ±5 分钟内重叠 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for H, M in ((1, 0.05), (3, 0.05), (3, 0.1), (5, 0.1), (3, 0.2), (5, 0.2), (10, 0.2), (5, 0.3)):
        per, cont, ext, up_sh, dn_sh, ov, n_ov = [], [], [], [], [], 0, 0
        for D, (a, s) in S.items():
            ev = events(s, H, M)
            per.append(len(ev))
            for i, d in ev:
                if i + 30 < len(s) and s[i + 30] is not None:
                    cont.append(d * (s[i + 30] - s[i]) > 0)
                    ext.append(d * (s[i + 30] - s[i]))
                    (up_sh if d > 0 else dn_sh).append(a[i + 30] - a[i])
                if th_ev.get(D) is not None:
                    n_ov += 1
                    ov += any(abs(i + 1 - j) <= 5 for j in th_ev[D])   # simulate 下标 1..240 对 MINS 0..239
        q = sorted(per)
        m_ = lambda x: f"{st.mean(x):+.2f}" if x else "-"   # noqa: E731
        print(f"| {H} | {M} | {st.mean(per):.1f} | {q[int(0.9 * (len(q) - 1))]} | {q[-1]} | {sum(1 for x in per if x == 0) / len(per) * 100:.0f}% | "
              f"{(sum(cont) / len(cont) * 100 if cont else 0):.0f}%(n={len(cont)}) | {m_(ext)} | {m_(up_sh)}(n={len(up_sh)}) | {m_(dn_sh)}(n={len(dn_sh)}) | "
              f"{(ov / n_ov * 100 if n_ov else 0):.0f}% |")
    ev10 = {D: events(S[D][1]) for D, _ in pairs[-5:]}
    print("近 5 天推荐档 (3, 0.1) 事件:", {D: [f"{MINS[i]}{'转正' if d > 0 else '转负'}" for i, d in v] for D, v in ev10.items()})


def selftest():
    s = [0.2] * 10 + [-0.05] * 3 + [-0.15] * 2 + [0.3] + [-0.12] * 5 + [0.0] * 3 + [0.25] * 3
    ev = events(s, 3, 0.1)
    assert ev == [(18, -1), (26, 1)], ev   # 起始侧正; −0.05 不够 M; −0.15 只 2 分钟不够 H; 0.3 打断; −0.12 第 3 分钟(下标 18)确认转负; 0.25 第 3 分钟(26)确认转正
    st_ = {}
    assert check(s[:18], st_) is None and check(s[:19], st_) == (18, -1) and check(s[:20], st_) is None
    print("自测通过: 起始侧不算事件 / 幅度不够不算 / 持续不够不算 / 被打断重计 / 实时只报新事件")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else backtest()


if __name__ == "__main__":
    main()
