# -*- coding: utf-8 -*-
"""signal_params.py — 分时信号 S1~S7 的动态参数(10/25 用户批: "参数按每只票自己的历史分布定, 像失效区间 / 翻转一样动态"; 零 token, 只读本地文件)

口径(全部只用 D 之前的数据; 启动时算一次, 结果缓存 downloads/market/<D>/signal_params.json):
  σ5      本票近 20 日 5 分钟收益率标准差(signals.Meta.sigmas 已有)
  k 校准  让"中位数那只票"拿到的阈值 = 原来的固定值(S2 带宽 0.3% / S3 涨跌 2% / S3 接近 1% / S5 拉升 1.5%), 别的票按自己的 σ5 等比例放大缩小:
          k = 原固定值 ÷ 全部股票 σ5 的中位; 阈值 = clip(k × 本票 σ5, 下限, 上限)  —— k 以后用回测(命中后 30 分钟 / 收盘期望)再调
  S7 x    本票近 30 日"开盘后 30 分钟最高相对开盘"的 P80(分钟路径; 不足 10 天用全部票的 P80)
  S6      抬高幅度 = 本票近 10 日竞价 09:20→09:25 变动(auction_live_open.json 的 d_after920)P90(不足 8 次用全部票的 P90), 下限 1%
          最小未匹配买入金额 = 本票近 20 日日均成交额 / 240 × 0.5(半分钟的平均成交额)
  S4a     开板持续 ≥ N 秒才算炸板(排除秒开秒封): N = 近 3 个交易日 3 秒盘口里全部开板时长的 P25, 夹在 6~60 秒
  S4b     回封动作: 开板期间卖一挂在涨停价、卖一量从这次开板的最大值降掉 ≥ DROP —— DROP = 近 3 日"真回封"前 6 秒卖一量相对开板期间最大值的降幅中位, 夹在 0.3~0.8
用法: python signal_params.py D   → 打印并写缓存
"""
import collections
import glob
import gzip
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
QUOTES = ROOT / "downloads" / "quotes"
BASE = {"S2_BAND": (0.003, 0.0015, 0.01), "S3_RISE": (0.02, 0.01, 0.06), "S3_PULLBACK": (0.02, 0.01, 0.06), "S3_NEAR": (0.01, 0.004, 0.03), "S5_UP": (0.015, 0.008, 0.05)}


def _q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else None


def board_stats(D, days=3):
    """近 days 个交易日 3 秒盘口: 开板时长(秒)分布 + 回封前卖一量降幅分布; 封板 = 卖盘空(卖一价 / 量为 0)且买一 > 0"""
    dirs = sorted(d for d in MKT.glob("20*") if d.name < D and (list(d.glob("book_snap.jsonl*"))))[-days:]
    durs, drops = [], []
    for d in dirs:
        f = next(iter(sorted(d.glob("book_snap.jsonl*"))), None)
        op = gzip.open if f.suffix == ".gz" else open
        S = {}
        with op(f, "rt", encoding="utf-8") as fh:
            for l in fh:
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                t = r.get("t") or ""
                if not ("09:30:00" <= t <= "14:57:00") or "11:30:05" < t < "13:00:00":
                    continue
                b, k = r.get("b") or [], r.get("k") or []
                if not b or not b[0][0]:
                    continue
                x = int(t[:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])
                sealed = (not k) or not k[0][0] or not k[0][1]
                s = S.setdefault(r["s"], {"sealed": False, "t0": None, "lim": None, "mx": 0, "hist": []})
                if sealed:
                    if s["t0"] is not None:
                        durs.append(x - s["t0"])
                        if s["mx"] > 0 and len(s["hist"]) >= 2:
                            drops.append(1 - s["hist"][-2] / s["mx"])
                    s.update(sealed=True, t0=None, lim=float(b[0][0]), mx=0, hist=[])
                elif s["sealed"]:
                    s.update(sealed=False, t0=x, mx=0, hist=[])
                if s["t0"] is not None and s["lim"] and abs(float(k[0][0]) - s["lim"]) < 1e-6:
                    v = float(k[0][1] or 0)
                    s["mx"] = max(s["mx"], v)
                    s["hist"].append(v)
                elif s["t0"] is not None:
                    s["hist"].append(0.0)
    return durs, drops, [d.name for d in dirs]


def build(D, sig_fn=None):
    """→ {"_global": {...}, 代码: {...}}; sig_fn(code) → σ5(没有返回 None)"""
    cache = MKT / D / "signal_params.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    out = {}
    # σ5 中位 → k
    sig = {}
    if sig_fn is None:
        import signals as SG
        m = SG.Meta(D)
        sig = {c: v[0] for c, v in m.sigmas().items() if c[:1] in "036" and not c.startswith(("11", "12"))}
    smed = st.median(sig.values()) if sig else 0.005
    k = {n: b[0] / smed for n, b in BASE.items()}
    # S7: 开盘 30 分钟最高相对开盘
    s7 = collections.defaultdict(list)
    for kind in ("stock", "cb"):
        fs = [f for f in sorted(glob.glob(str(QUOTES / kind / "minute_path" / "*.jsonl"))) if Path(f).stem < D][-30:]
        for f in fs:
            for l in open(f, encoding="utf-8"):
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                p = r.get("p") or []
                if len(p) >= 30 and p[0]:
                    s7[str(r["code"])].append((max(p[:30]) / p[0] - 1) * 100)
    pool7 = [x for v in s7.values() for x in v]
    g7 = _q(pool7, 0.8) or 6.0
    # S6: 竞价 09:20 后变动
    s6 = collections.defaultdict(list)
    for f in sorted(MKT.glob("20*/auction_live_open.json")):
        if f.parent.name >= D:
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for s, v in (j.get("symbols") or {}).items():
            if isinstance(v, dict) and v.get("d_after920") is not None:
                s6[s[2:]].append(float(v["d_after920"]))
    pool6 = [x for v in s6.values() for x in v if x > 0]
    g6 = max(1.0, _q(pool6, 0.9) or 3.0)
    durs, drops, bdays = board_stats(D)
    n_open = min(60, max(6, _q(durs, 0.25) or 6))
    drop = min(0.8, max(0.3, st.median(drops) if drops else 0.5))
    out["_global"] = {"σ5中位": round(smed, 5), "k": {n: round(v, 3) for n, v in k.items()}, "S7_X_pool": round(g7, 2), "S6_UP_pool": round(g6, 2),
                      "S4a_N秒": n_open, "S4b_DROP": round(drop, 2), "开板样本": len(durs), "回封样本": len(drops), "盘口天": bdays, "S6天数": len({f.parent.name for f in MKT.glob('20*/auction_live_open.json')})}
    for c in set(sig) | set(s7) | set(s6):
        d = {}
        sg = sig.get(c)
        if sg:
            for n, (b0, lo, hi) in BASE.items():
                d[n] = round(min(hi, max(lo, k[n] * sg)), 5)
        if len(s7.get(c, [])) >= 10:
            d["S7_X"] = round(_q(s7[c], 0.8), 2)
        if len([x for x in s6.get(c, []) if x > 0]) >= 8:
            d["S6_UP"] = round(max(1.0, _q([x for x in s6[c] if x > 0], 0.9)), 2)
        if d:
            out[c] = d
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    D = sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat()
    o = build(D)
    print(json.dumps(o["_global"], ensure_ascii=False, indent=1))
    print(f"有个股参数的票 {len(o) - 1} 只; 例:", {c: o[c] for c in list(o)[1:4]})
