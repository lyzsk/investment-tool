# -*- coding: utf-8 -*-
"""skill_weights.py — paper 各 skill 权重 初版(10/16 晚用户令: B8 先出初版并直接上线; 公式后续随数据迭代)
用户定的目标函数(10/11 + 10/16): 不淘汰任何 skill, 全员有权重只调大小; 权重 = 拟人度 × 导师真人业绩; 样本少时向等权强收缩
初版公式(全部零 token, 每天收盘后 check md 跑):
  拟人度 M∈[0,1] = 可用分项的均值
      ① 分层行为(mimicry_score.py 累计结果, 自 10/08): 每层(L1 交易/L2 方向/L3 标的/L4 仓位)内各指标相对"照抄导师昨天"的胜负,
         层分=(赢+0.5×平)/指标数, 取 4 层均值(只看胜负不看幅度, 各指标量纲不同)
      ② 打法分布(mentor_fingerprint.py 统一分类器): 1 − JS(链新开仓打法分布, 导师真人新开仓打法分布); 链新开仓 <3 笔不算
      无真人数据的链(B站三位 UP)=0.5 中性
  真人业绩 P∈[0.5,1.5] = 1 + 0.25×clip(收缩夏普, −2, 2); 收缩夏普=近 60 个交易日日收益年化夏普 × n/(n+20); 无真人净值(B站 UP)=1 中性
  原始分 raw = M × P → 归一化; 再向等权收缩: w = λ·raw_norm + (1−λ)/N, λ = d/(d+20), d=该链 10/08 起有净值的交易日数; 保底 3% 后归一
  噪声带(10/17 用户批 B2, scripts/dfcf/paper/noise_band.json): 拟人度 M 是 LLM 跑出来的、有运行噪声; 按 M 排序后相邻链 M 差 < 带宽
      就并成一组、组内 M 取平均(=视为相等), 再乘各自真人业绩 P(P 来自真人账本, 无 LLM 噪声, 不并)。
      带宽 = 1.96·√2·σ/√d, σ=noise_band.json mimicry.sigma_day_planning(缺省 0.05), d=两链有净值天数的较小者(累计 d 天平均的标准误);
      组内最大差也不超带宽(complete linkage, 防一串链被链式并成一组)。文件不存在=跳过
输出: scripts/dfcf/paper/weights/<日>.json + .md(daily_digest 读最新一份显示前三/后三)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/skill_weights.py [--date YYYY-MM-DD] [--no-play] [--selftest]
"""
import argparse, ast, json, math, re, statistics as st, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "weights"
TZZB = ROOT / "downloads" / "tzzb"
LIVE_START = "2026-10-08"
def _hp():
    try:
        import yaml
        return (yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8")) or {}).get("skill_weights") or {}
    except Exception:   # noqa: BLE001
        return {}


HP = _hp()   # 超参数(params.yaml skill_weights 节; 缺省=初版值)
K_SHRINK, FLOOR, P_WIN = int(HP.get("shrink_days", 20)), float(HP.get("floor", 0.03)), int(HP.get("perf_window", 60))
P_SHRINK, P_SLOPE, P_CLIP, TEMP = int(HP.get("perf_shrink", 20)), float(HP.get("perf_slope", 0.25)), float(HP.get("perf_clip", 2.0)), HP.get("temperature")
# 10/18 审计④ R13(用户定): 真人业绩改"按排名加减分"——近 RANK_WIN 个交易日真人收益排名, 第 1 名 +RANK_WIN/RANK_DIV, 最后一名 −RANK_WIN/RANK_DIV,
#   中间按名次线性; 30 日 → ±0.3(÷100 用户说是拍的, 在 params 里调)。原"近 60 日收缩夏普"会追热手(9/15 顶上限), 只留作报告参考
PERF_MODE, RANK_WIN, RANK_DIV = str(HP.get("perf_mode", "rank")), int(HP.get("rank_window", 30)), float(HP.get("rank_div", 100))


sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表(原解析 accounts.mjs 文本)


def chains():
    return [(e["book"], e["display"]) for e in mentors.all() if e["type"] in ("UP", "tzzb")]


def ledger_of(src):
    try:
        return mentors.by_book(src)
    except StopIteration:
        return src[2:]


def real_perf(src, d):
    """导师真人近 60 日收缩夏普 → P; 无账本=None"""
    try:
        il = json.loads((TZZB / ledger_of(src) / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["index_list"]
        il = ast.literal_eval(il) if isinstance(il, str) else il
    except (OSError, ValueError, KeyError, SyntaxError, TypeError):
        return None
    cut = d.replace("-", "")
    il = [x for x in il if str(x["date"]) < cut and float(x.get("index") or 0) > 0][-(max(P_WIN, RANK_WIN) + 1):]
    if il and (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(str(il[-1]["date"]), "%Y%m%d")).days > 30:
        return None   # 停更账本(冲5000w 停在 07/06): 旧业绩不代表现在, 按中性
    r = [float(il[i]["index"]) / float(il[i - 1]["index"]) - 1 for i in range(1, len(il))]
    if len(r) < 10:
        return None
    sd = st.pstdev(r)
    sh = (st.mean(r) / sd * math.sqrt(250)) if sd > 0 else 0.0
    shr = sh * len(r) / (len(r) + P_SHRINK)
    rk = il[-(RANK_WIN + 1):]
    return {"n": len(r), "sharpe": round(sh, 2), "sharpe_shrunk": round(shr, 2), "ret": round(float(il[-1]["index"]) / float(il[0]["index"]) - 1, 4),
            f"ret_{RANK_WIN}d": round(float(rk[-1]["index"]) / float(rk[0]["index"]) - 1, 4),
            "P": round(1 + P_SLOPE * max(-P_CLIP, min(P_CLIP, shr)), 3)}


def rank_perf(rows):
    """R13: 有真人净值的链按近 RANK_WIN 日真人收益排名 → P = 1 + A·(1 − 2·(名次−1)/(人数−1)), A = RANK_WIN/RANK_DIV; 无真人=1"""
    have = [r for r in rows if r.get("real") and r["real"].get(f"ret_{RANK_WIN}d") is not None]
    have.sort(key=lambda r: -r["real"][f"ret_{RANK_WIN}d"])
    amp, n = RANK_WIN / RANK_DIV, len(have)
    for i, r in enumerate(have):
        r["P"] = round(1 + amp * (1 - 2 * i / (n - 1)), 3) if n > 1 else 1.0
        r["real"]["rank"] = f"{i + 1}/{n}"
    for r in rows:
        if r not in have:
            r["P"] = 1.0
        r["raw"] = r["M"] * r["P"]


def mimic_layers(src):
    fs = sorted((HERE / "mimicry").glob("cum_*.json"))
    if not fs:
        return None
    pr = (json.loads(fs[-1].read_text(encoding="utf-8")).get("pairs") or {}).get(src)
    if not pr:
        return None
    lay = {}
    for k, v in (pr.get("metrics") or {}).items():
        lift = (v.get("persist") or {}).get("lift")
        if lift is None:
            continue
        lay.setdefault(k[:2], []).append(1.0 if lift > 1e-9 else 0.5 if abs(lift) <= 1e-9 else 0.0)
    if not lay:
        return None
    sc = {L: sum(x) / len(x) for L, x in lay.items()}
    return {"layers": {k: round(v, 3) for k, v in sorted(sc.items())}, "score": round(sum(sc.values()) / len(sc), 3), "file": fs[-1].name, "n_days": pr.get("n_days")}


def play_sim(srcs):
    """链 vs 真人 新开仓打法分布相似度 1−JS; 加载行情面板较慢(约 1 分钟), 失败=空"""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "tzzb"))
        import mentor_fingerprint as mf
        M = mf.Market()
        out = {}
        for src in srcs:
            led = ledger_of(src)
            cf = ROOT / "skills" / f"{led}-skill" / "persona" / "cases_auto.jsonl"
            pd = mf.paper_dist(M, "cb" if src == "A-cb" else src[2:])
            if not cf.exists() or not pd or pd["n_new"] < 3:
                continue
            labs = [c.get("play") for c in (json.loads(l) for l in cf.read_text(encoding="utf-8").splitlines() if l.strip()) if c.get("side") == "买" and c.get("new_open")]
            labs = [x for x in labs if x]
            real = mf.dist(labs, mf.PLAY_ORDER)
            out[src] = {"sim": round(1 - mf.js_distance(pd["dist_new"], real), 3), "n_new": pd["n_new"]}
        return out
    except Exception as e:   # noqa: BLE001
        print(f"WARN 打法相似度不可用(跳过该分项): {e}")
        return {}


def live_days(src):
    try:
        b = json.loads((HERE / "books" / f"{src}.json").read_text(encoding="utf-8"))
        return len({n["date"] for n in b.get("nav", []) if n["date"] >= LIVE_START})
    except (OSError, ValueError):
        return 0


def compute(d, use_play=True):
    cs = chains()
    srcs = [s for s, _ in cs]
    ps = play_sim(srcs) if use_play else {}
    rows = []
    for src, name in cs:
        ml, pl, rp = mimic_layers(src), ps.get(src), real_perf(src, d)
        parts = [x for x in ((ml or {}).get("score"), (pl or {}).get("sim")) if x is not None]
        M = sum(parts) / len(parts) if parts else 0.5
        P = rp["P"] if rp else 1.0
        rows.append({"src": src, "name": name, "M": round(M, 3), "P": P, "raw": M * P, "mimic": ml, "play": pl, "real": rp, "days": live_days(src)})
    if PERF_MODE == "rank":
        rank_perf(rows)
    r_note = apply_noise_band(rows, d)
    if TEMP:   # 温度: softmax(ln raw / T)(10/18 R15: 不再使用, params 不配 temperature)
        ex = [math.exp(math.log(max(r["raw"], 1e-6)) / float(TEMP)) for r in rows]
        for r, e in zip(rows, ex):
            r["raw"] = e
    tot = sum(r["raw"] for r in rows) or 1.0
    N = len(rows)
    for r in rows:
        lam = r["days"] / (r["days"] + K_SHRINK)
        r["lambda"] = round(lam, 3)
        r["w0"] = lam * r["raw"] / tot + (1 - lam) / N
    s = sum(max(FLOOR, r["w0"]) for r in rows)
    for r in rows:
        r["w"] = round(max(FLOOR, r["w0"]) / s, 4)
    rows.sort(key=lambda r: -r["w"])
    return {"date": d, "generated_at": datetime.now().isoformat(timespec="seconds"), "formula": f"w = λ·norm(M×P{'^(1/T), T=' + str(TEMP) if TEMP else ''}) + (1−λ)/N, λ=d/(d+{K_SHRINK}), 保底 {FLOOR:.0%}", "noise_band": r_note, "rows": rows}


_SIG = {}


def sigma_day(asof=None):
    """10/18 审计④ R11(用户批): 拟人度单日综合分"换一天"的波动——每次按 mimicry/<日>.json 现算(各链跨日标准差的中位数), 随数据动态更新;
    综合分口径同噪声带实验: L1_交易 / L2_方向 / L3_持仓Jaccard / 1-min(L4_总仓误差,1) 的均值; 只用 asof 之前的日子。
    少于 3 条链各有 ≥3 天时退回 0.18(10/17 实测中位); 下限 = noise_band.json 的 LLM 重跑 σ(0.05), 不会比单纯重跑噪声还窄"""
    key = asof or "_"
    if key in _SIG:
        return _SIG[key]
    try:
        floor = float((json.loads((HERE / "noise_band.json").read_text(encoding="utf-8")).get("mimicry") or {}).get("sigma_day_planning") or 0.05)
    except (OSError, ValueError):
        floor = 0.05
    per = {}
    for f in sorted((HERE / "mimicry").glob("20??-??-??.json")):
        if asof and f.stem >= asof:
            continue
        try:
            pairs = json.loads(f.read_text(encoding="utf-8")).get("pairs") or {}
        except (OSError, ValueError):
            continue
        for ch, v in pairs.items():
            m = v.get("metrics") or {}
            xs = [float((m.get(k) or {}).get("chain")) for k in ("L1_交易", "L2_方向", "L3_持仓Jaccard") if (m.get(k) or {}).get("chain") is not None]
            e = (m.get("L4_总仓误差") or {}).get("chain")
            if e is not None:
                xs.append(1 - min(float(e), 1.0))
            if xs:
                per.setdefault(ch, []).append(sum(xs) / len(xs))
    sds = [st.stdev(v) for v in per.values() if len(v) >= 3]
    sig = max(floor, st.median(sds)) if len(sds) >= 3 else max(floor, 0.18)
    _SIG[key] = sig
    return sig


def band_width(d, asof=None):
    """拟人度噪声带宽(两链 M 之差的 95% 判别阈值); d=累计天数, d<1 按 1。
    10/18 R11: σ 由"同一天 LLM 重跑"的 0.05 改成跨日实测(sigma_day, 动态), 原值只作下限"""
    return 1.96 * math.sqrt(2) * sigma_day(asof) / math.sqrt(max(1, d))


def apply_noise_band(rows, asof=None):
    """B2: M 差在噪声带内的链并组取平均 M, raw 重算 = M_组均 × P; 返回给报告的一句说明"""
    if band_width(1) is None:
        return "噪声带文件不存在, 未应用"
    srt = sorted(rows, key=lambda r: -r["M"])
    groups, cur = [], [srt[0]] if srt else []
    for r in srt[1:]:
        if all(abs(x["M"] - r["M"]) < band_width(min(x["days"], r["days"]), asof) for x in cur):
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    if cur:
        groups.append(cur)
    for gi, g in enumerate(groups, 1):
        m = sum(x["M"] for x in g) / len(g)
        for x in g:
            x["M_raw"], x["M"], x["band_group"] = x["M"], round(m, 3), gi
            x["raw"] = m * x["P"]
    big = [g for g in groups if len(g) > 1]
    return (f"噪声带已应用(B2): 拟人度差在带宽内的并组取平均, 共 {len(groups)} 组" + (f", 其中 {len(big)} 组多链(最大 {max(len(g) for g in big)} 条)" if big else "")
            + f"; 带宽 1 天 {band_width(1, asof):.2f} / 20 天 {band_width(20, asof):.2f}(跨日 σ={sigma_day(asof):.3f})")


def write(res):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{res['date']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# paper skill 权重 初版 · {res['date']}", "", f"> 公式：{res['formula']}；拟人度 M=分层行为胜负(对照着照抄导师昨天) 与 打法分布相似度 的均值；真人业绩 P=1+0.25×收缩夏普(近 60 日)；B站 UP 无真人数据=中性。{res['noise_band']}", "",
         "| 链 | 权重 | 拟人度 M | 分层(L1/L2/L3/L4) | 打法相似 | 真人业绩 P | 真人近60日夏普/收益 | 收缩 λ(天数) |", "|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        lay = (r["mimic"] or {}).get("layers") or {}
        rp = r["real"] or {}
        L.append(f"| {r['name']} | {r['w']:.1%} | {r['M']:.2f} | {'/'.join(f'{lay.get(k, float('nan')):.2f}' if k in lay else '-' for k in ('L1', 'L2', 'L3', 'L4'))} | "
                 f"{(r['play'] or {}).get('sim', '-')} | {r['P']:.2f} | {rp.get('sharpe', '-')}/{(f'{rp['ret']:+.0%}' if rp else '-')} | {r['lambda']:.2f}({r['days']}) |")
    L += ["", "- 初版：样本只有个位数交易日，λ 小 → 权重接近等权是预期；随天数增加逐步放开。只调大小不淘汰。"]
    (OUT / f"{res['date']}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def selftest():
    global chains, mimic_layers, real_perf, live_days, play_sim
    keep = (chains, mimic_layers, real_perf, live_days, play_sim)
    try:
        chains = lambda: [("A-a", "甲"), ("A-b", "乙"), ("A-c", "丙")]
        mimic_layers = lambda s: {"score": {"A-a": 0.8, "A-b": 0.2}.get(s, 0.5), "layers": {}} if s != "A-c" else None
        real_perf = lambda s, d: {"P": {"A-a": 1.5, "A-b": 0.5}[s]} if s != "A-c" else None
        play_sim = lambda srcs: {}
        live_days = lambda s: 0
        r0 = {x["src"]: x["w"] for x in compute("2026-10-20", False)["rows"]}
        assert max(r0.values()) - min(r0.values()) < 1e-9, f"0 天应严格等权 {r0}"
        live_days = lambda s: 200
        r1 = {x["src"]: x["w"] for x in compute("2026-10-20", False)["rows"]}
        assert r1["A-a"] > r1["A-c"] > r1["A-b"] and r1["A-b"] >= FLOOR - 1e-9 and abs(sum(r1.values()) - 1) < 1e-6, r1
        # B2: M 差在噪声带内 → M 视为相等, 权重只差在 P
        mimic_layers = lambda s: {"score": {"A-a": 0.52, "A-b": 0.50}.get(s, 0.51), "layers": {}}
        real_perf = lambda s, d: {"P": 1.0}
        live_days = lambda s: 5
        r2 = {x["src"]: x["w"] for x in compute("2026-10-20", False)["rows"]}
        assert max(r2.values()) - min(r2.values()) < 1e-9, f"噪声带内应等权 {r2}"
        print("SKILL_WEIGHTS SELFTEST PASS:", r0, r1, r2)
    finally:
        chains, mimic_layers, real_perf, live_days, play_sim = keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    write(compute(a.date, not a.no_play))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
