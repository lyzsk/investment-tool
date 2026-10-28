# -*- coding: utf-8 -*-
"""watch_seed.py — 明日种子池(10/27 用户令, 午休上线; 零 token, 只读本地日 K / 证券表 / 拓扑)

三类(每只带来源标签, 一只票可多个标签):
  ① 续板: T 日(= D 的前一交易日)收盘涨停、连板 ≥1 的票 —— 明天冲 N+1; 附「梯队」= 各高度几只 + 哪一档空缺
  ② 断板观察: 近 5 个交易日涨停 ≥2 次、T 日没封住(用户例: 板-板-断-断-板 也算 = 只看"5 日内 ≥2 板", 不要求连续)
     —— 同口径里 T 日封住的(板断断板板 / 断板断断板 …)归 ① 续板, 标签写出形态串
  ③ 字辈: 近 10 个交易日涨停股名字里, 按拼音聚组(洋 / 阳 / 羊 = yang)的字比全市场基数高出很多倍 且 跨 ≥2 个行业(同行业共字 = 行业名, 如 传媒 / 机电, 不算字辈)
     → 这一组字在全 A 的同字票里, 挑近 20 日涨停过的(热成员)进池; 字辈不是一直有, 没有就空
产物: results/_live/<D>/watch_seed.json + watch_seed.md; 同时把代码写进 scripts/temp/collect_book_extra.txt 里一个自动区块
     (# >>> watch_seed 自动 … # <<<), 3 秒盘口(collect_book 每 60 秒重读)和分时信号(signals.extra_codes)不用重启就能接上
用法: python watch_seed.py [--date D(默认今天)] [--dry] [--cap 70]
待做(10/27 晚): check md 收盘后自动跑(D = 下一交易日); signals 的 🆕 来源标签读 watch_seed.json(现在显示成"你点名")
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
EXTRA = ROOT / "scripts" / "temp" / "collect_book_extra.txt"
BEGIN, END = "# >>> watch_seed 自动(watch_seed.py 生成, 别手改这段)", "# <<< watch_seed 自动"
STOP = set("股份集团科技电子新材业中国控发展能源智能实工有限公司华天东西南北海山江市城建信达泰安和宏通联合大一方源光ＡAB*ST")


def _flag(k, d=""):
    try:
        for l in (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
            kk, _, v = l.split("#")[0].partition("=")
            if kk.strip() == k:
                return v.strip()
    except OSError:
        pass
    return d


def days_upto(D):
    ds = sorted(d for d in os.listdir(MKT) if re.fullmatch(r"\d{4}-\d\d-\d\d", d) and d < D and (MKT / d / "kline_day.jsonl").exists())
    return ds


def load_day(d, names):
    out = {}
    for l in (MKT / d / "kline_day.jsonl").open(encoding="utf-8"):
        r = json.loads(l)
        s = r["symbol"]
        if s not in names or not r.get("limitUp") or r.get("close") is None:
            continue
        out[s] = (r["close"] >= r["limitUp"] - 0.005, r["high"] >= r["limitUp"] - 0.005)
    return out


def names_of(T):
    nm = {}
    f = MKT / T / "security_master.jsonl"
    for l in f.open(encoding="utf-8"):
        r = json.loads(l)
        if r.get("secType") == "STOCK" and r["symbol"][:2] in ("sh", "sz"):
            nm[r["symbol"]] = r["name"].replace(" ", "").replace("　", "")
    return nm


def industries(T):
    ind = {}
    f = MKT / T / "topology.jsonl"
    if f.exists():
        for l in f.open(encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            ind[r["c"]] = r.get("ind") or ""
    return ind


def build(D, cap=70):
    ds = days_upto(D)
    T = ds[-1]
    nm = names_of(T)
    ind = industries(T)
    win = ds[-20:]
    Z = {d: load_day(d, nm) for d in win}
    sealed = lambda s, d: Z[d].get(s, (False, False))[0]   # noqa: E731
    pat = lambda s: "".join("板" if sealed(s, d) else ("断" if s in Z[d] else "-") for d in win[-5:])   # noqa: E731
    seed = collections.OrderedDict()

    def add(s, tag, why):
        e = seed.setdefault(s, {"code": s[2:], "name": nm.get(s, s), "tags": [], "why": []})
        if tag not in e["tags"]:
            e["tags"].append(tag)
        e["why"].append(why)

    # ①② 续板 / 断板观察
    streak = {}
    for s in nm:
        n = 0
        for d in reversed(win):
            if sealed(s, d):
                n += 1
            else:
                break
        streak[s] = n
    c5 = {s: sum(sealed(s, d) for d in win[-5:]) for s in nm}
    ladder = collections.Counter(n for n in streak.values() if n >= 1)
    top = max(ladder) if ladder else 0
    gaps = [h for h in range(2, top) if not ladder.get(h)]
    keep = int(_flag("SEED_BREAK_KEEP", "2") or 2)   # 10/27 用户: ≥2 连板断板后 断 1~2 天都要在观察池(福莱新材 板板断断 → 10/23 要在)

    def runs(s):
        """→ (T 日往前连续没封的天数, 再往前那一段连板的长度)"""
        flags = [sealed(s, d) for d in win]
        i, gap = len(flags) - 1, 0
        while i >= 0 and not flags[i]:
            gap, i = gap + 1, i - 1
        cur = 0
        while i >= 0 and flags[i]:
            cur, i = cur + 1, i - 1
        return gap, cur

    def prev_run(s):
        """T 日封住时: 本段连板之前、隔着断板的上一段连板长度(福莱新材 板板断断板板 → 上一段 2)"""
        flags = [sealed(s, d) for d in win]
        i = len(flags) - 1
        while i >= 0 and flags[i]:
            i -= 1
        g = 0
        while i >= 0 and not flags[i] and g <= keep:
            g, i = g + 1, i - 1
        n = 0
        while i >= 0 and flags[i]:
            n, i = n + 1, i - 1
        return n if 1 <= g <= keep else 0
    manual = []
    for s in sorted(nm, key=lambda s: (-streak[s], -c5[s])):
        if streak[s] >= 2:
            add(s, "续板", f"{streak[s]} 连板 → 明天冲 {streak[s] + 1} 板; 5 日形态 {pat(s)}")
        elif streak[s] == 1 and prev_run(s) >= 2:
            add(s, "续板", f"{prev_run(s)} 连板断板后今天回封 → 明天冲 2 连板(5 日 {c5[s]} 板); 5 日形态 {pat(s)}")
        elif streak[s] == 1 and c5[s] >= 2:
            manual.append(s)   # 1 板-断-断-1 板: 用户 10/27 定人工排查, 不进池
    for s in sorted(nm, key=lambda s: -c5[s]):
        if sealed(s, T):
            continue
        gap, run = runs(s)
        if run >= 2 and 1 <= gap <= keep:
            add(s, "断板观察", f"{run} 连板后断 {gap} 天(5 日 {c5[s]} 板); 形态 {pat(s)}")
        elif c5[s] >= 2:
            manual.append(s)
    manual_rows = [{"code": s[2:], "name": nm[s], "pat": pat(s), "c5": c5[s]} for s in manual]
    # ③ 字辈
    try:
        from pypinyin import lazy_pinyin
        py = lambda ch: lazy_pinyin(ch)[0]   # noqa: E731
    except Exception:   # noqa: BLE001  10/27 晚: anaconda base 没装 pypinyin → yang 组(洋 / 阳 / 羊)整组丢了; 必须用 scripts/venv 的 python
        print("[watch_seed] ⚠️ 没有 pypinyin, 字辈退化成按单字分组(洋 / 阳 / 羊 不会并成 yang)—— 用 scripts/venv/Scripts/python.exe 跑", file=sys.stderr)
        py = lambda ch: ch   # noqa: E731
    lu10 = {s for d in win[-10:] for s in nm if sealed(s, d)}
    lu20 = {s for d in win for s in nm if sealed(s, d)}
    # 行业字: 单个字的近 10 日涨停成员 ≥2 且同一行业占 ≥60%(媒 = 传媒, 机 = 机械 …) → 不算字辈, 从拼音组里剔掉
    by_char = collections.defaultdict(set)
    for s in lu10:
        for c in set(nm[s]):
            if c not in STOP and not c.isascii():
                by_char[c].add(s)
    ind_char = {c for c, m in by_char.items() if len(m) >= 2 and collections.Counter(ind.get(x[2:], "?") for x in m).most_common(1)[0][1] / len(m) >= 0.6}
    uni = collections.Counter(py(c) for n in nm.values() for c in set(n) if c not in STOP and c not in ind_char)
    grp = collections.defaultdict(set)
    for c, m in by_char.items():
        if c not in ind_char:
            grp[py(c)] |= m
    force = [x.strip() for x in (os.environ.get("ZIBEI_FORCE") or _flag("ZIBEI_FORCE", "")).split(",") if x.strip()]   # 用户点名的字辈(拼音或字)
    force_py = {py(x[0]) if not x.isascii() else x for x in force}
    w10 = win[-10:]
    zibei = []
    for k, mem in grp.items():
        base = uni[k] / len(nm) * len(lu10)
        if base <= 0 or len(mem) < 3:
            continue
        lift, excess = len(mem) / base, len(mem) - base
        inds = collections.Counter(ind.get(s[2:], "?") for s in mem)
        top_share = inds.most_common(1)[0][1] / len(mem)
        sync = max(len({s for s in mem if any(sealed(s, d) for d in w10[i:i + 3])}) for i in range(max(1, len(w10) - 2)))
        bi = collections.Counter(w for x in mem for w in {nm[x][i:i + 2] for i in range(len(nm[x]) - 1)} if any(py(c) == k for c in w))
        word_share = bi.most_common(1)[0][1] / len(mem) if bi else 0   # 同一个双字词(传媒 / 煤电 …)占多数 = 行业名不是字辈
        auto = len(mem) >= 5 and excess >= 8 and sync >= 0.6 * len(mem) and len(inds) >= 3 and top_share <= 0.5 and word_share < 0.4
        if auto or k in force_py:
            chars = sorted({c for s in mem for c in nm[s] if py(c) == k and c not in ind_char})
            zibei.append({"py": k, "chars": chars, "n": len(mem), "lift": round(lift, 1), "excess": round(excess, 1), "sync3": sync, "inds": len(inds),
                          "src": "用户点名" if k in force_py else "自动", "members_lu10": [nm[s] for s in sorted(mem)]})
    zibei.sort(key=lambda z: (z["src"] != "用户点名", -z["excess"]))
    zibei = [z for z in zibei if z["src"] == "用户点名"] + [z for z in zibei if z["src"] != "用户点名"][:3]
    for z in zibei:
        hot = [s for s in nm if any(py(c) == z["py"] and c not in ind_char for c in nm[s]) and s in lu20]
        hot.sort(key=lambda s: (-c5[s], -streak[s]))
        for s in hot[:15]:
            add(s, f"字辈:{'/'.join(z['chars'])}", f"名字带「{'/'.join(z['chars'])}」(近 10 日 {z['n']} 只涨停, 基数的 {z['lift']} 倍, 3 日内同步 {z['sync3']} 只, 跨 {z['inds']} 个行业, {z['src']}); 本票近 20 日涨停过")
    items = list(seed.values())
    pri = lambda e: (0 if "续板" in e["tags"] else 1 if any(t.startswith("字辈") for t in e["tags"]) else 2)   # noqa: E731
    items.sort(key=pri)
    items = items[:cap]
    return {"date": D, "T": T, "ladder": {str(h): ladder[h] for h in sorted(ladder, reverse=True)}, "gaps": gaps, "zibei": zibei,
            "seed": items, "manual": manual_rows, "built": dt.datetime.now().isoformat(timespec="seconds")}


def write_extra(res, dry=False):
    txt = EXTRA.read_text(encoding="utf-8") if EXTRA.exists() else ""
    txt = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", txt, flags=re.S)
    have = set(re.findall(r"(?m)^(\d{6})", txt))
    lines = [BEGIN + f" {res['date']} 基于 {res['T']} 收盘"]
    for e in res["seed"]:
        if e["code"] in have:
            continue
        lines.append(f"{e['code']}  # {e['name']} {'/'.join(e['tags'])}")
    lines.append(END)
    new = txt.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    if not dry:
        EXTRA.write_text(new, encoding="utf-8")
    return len(lines) - 2


def to_md(res):
    L = [f"## 明日种子池 {res['date']}(基于 {res['T']} 收盘)", ""]
    L.append("梯队(连板高度: 只数): " + "  ".join(f"{h} 板 {n}" for h, n in res["ladder"].items() if int(h) >= 2) + (f"; 空缺 {'/'.join(map(str, res['gaps']))} 板" if res["gaps"] else "; 无空档"))
    if res["zibei"]:
        L.append("")
        L.append("字辈(近 10 日涨停股名字共字, 跨行业):")
        for z in res["zibei"]:
            L.append(f"- 「{'/'.join(z['chars'])}」({z['src']}) {z['n']} 只 · 基数的 {z['lift']} 倍 · 3 日内同步 {z['sync3']} 只 · {z['inds']} 个行业: {'、'.join(z['members_lu10'])}")
    else:
        L.append("字辈: 近 10 日没有跨行业的共字(这阵子没有字辈炒作)")
    if res.get("manual"):
        L += ["", f"### 人工排查(1 板-断-1 板这类, 不进池; {len(res['manual'])})"] + [f"- {m['name']}({m['code']}) 形态 {m['pat']}" for m in res["manual"]]
    for tag in ("续板", "断板观察", "字辈"):
        es = [e for e in res["seed"] if any(t.startswith(tag) for t in e["tags"])]
        if es:
            L += ["", f"### {tag}({len(es)})"] + [f"- {e['name']}({e['code']}) {'/'.join(e['tags'])}: {e['why'][0]}" for e in es]
    return "\n".join(L) + "\n"


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--cap", type=int, default=70)
    a = ap.parse_args()
    res = build(a.date, a.cap)
    out = ROOT / "results" / "_live" / a.date
    out.mkdir(parents=True, exist_ok=True)
    md = to_md(res)
    if not a.dry:
        (out / "watch_seed.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "watch_seed.md").write_text(md, encoding="utf-8")
    n = write_extra(res, a.dry)
    print(md)
    print(f"[watch_seed] 种子 {len(res['seed'])} 只, 新写进 collect_book_extra {n} 只" + (" (dry)" if a.dry else ""))


if __name__ == "__main__":
    main()
