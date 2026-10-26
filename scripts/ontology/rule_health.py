# -*- coding: utf-8 -*-
"""ontology/rule_health.py — 07 规则体检(10/25 用户批: "负的多才是优化的动力"; 零 token, 只读)

口径: 体检对象 = 模型下单时在 why 末尾「依据：…」里引用过的规则编号(导师 skill 的 R 编号 + market-skill 的 M / KD / KS + telegraph-skill 的 T)
      —— 653 条导师规则只有 31 条能机械触发, 按"被引用"统计才覆盖得到话术级规则
  数据: results/_live/<日>/v3_*/state.json 里的成交(paper v3 + live line; 不含回放 / 桩), 每笔买入按样例库同一口径打标签:
        X = 这只票买入前 30 个交易日日振幅中位; 正 = T+1~T+3 任一天最高 ≥ 成交价 +X%; 负 = 都没冲到且 T+3 收盘 < 成交价; 平 = 其余; 待核 n = 还差 n 天
  每条规则: 引用它的买入笔数 / 正负平 / T+1 收盘分布 / 最差几例(带当时的理由原文)
  可疑 = 已判定 ≥ 2 笔 且 负 > 正(样本攒多了再收紧, 门槛在 SUSPECT 里)
  你核销: docs/review/rule_verdicts.json {"<skill>:<编号>": {"verdict": "确认错误|驳回|再观察", "at": 日期, "note": "…"}};
          确认错误 → 我把 rules.md 那条划掉 + 加反例, rule_tags 标已证伪, 盘前材料不再给, 闸拦"拿它当依据"; 驳回 → 写进修订记录, 以后不再报
产物: docs/review/rule_suspects.md(给你核销) + downloads/ontology/rule_health.json(必查 / 07 复盘读)
另列: 各导师 rules.md 里从没被引用过的规则(可能是死规则, 也可能是模型没看到)
用法: python rule_health.py
"""
import collections
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "paper_line" / "tools")]
LIVE = ROOT / "results" / "_live"
OUT_MD = ROOT / "docs" / "review" / "rule_suspects.md"
OUT_JS = ROOT / "downloads" / "ontology" / "rule_health.json"
VERD = ROOT / "docs" / "review" / "rule_verdicts.json"
SUSPECT = {"min_done": 2}
KNOW = {"M": "market-skill", "KD": "market-skill", "KS": "market-skill", "U": "market-skill", "T": "telegraph-skill"}


def line_skill(name):
    try:
        L = {x["id"]: x["skill"] for x in json.loads((ROOT / "scripts" / "paper_line" / "lines.json").read_text(encoding="utf-8"))["lines"]}
    except (OSError, ValueError):
        L = {}
    lid = name[6:] if name.startswith("paper_") else name[3:] if name.startswith("v3_") else name
    return lid[5:] if lid.startswith("live_") else L.get(lid)


def cited(why):
    m = re.search(r"依据[：:](.*)$", why or "", re.S)
    seg = m.group(1) if m else ""
    return sorted(set(re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,2}\d+)(?!\d)", seg)) - {"E" + x for x in re.findall(r"E(\d+)", seg)})


def kline(code, d0):
    import manual_backfill as mb
    c = mb.db().cursor()
    sym = ("sh" if code.startswith(("6", "9", "11", "5")) else "sz") + code
    c.execute("select trade_date, high, low, close, pre_close from investment_market.kline_day where symbol=%s and is_deleted=0 and trade_date>=%s order by trade_date",
              (sym, (dt.date.fromisoformat(d0) - dt.timedelta(days=60)).isoformat()))
    return [(str(a), *(float(x or 0) for x in r)) for a, *r in c.fetchall()]


def label(code, d, px, cache):
    if code not in cache:
        cache[code] = kline(code, d)
    K = cache[code]
    ix = {k[0]: i for i, k in enumerate(K)}
    i = ix.get(d)
    if i is None:
        return {"label": "无行情"}
    amp = [(K[j][1] - K[j][2]) / K[j][4] * 100 for j in range(max(0, i - 30), i) if K[j][4]]
    X = st.median(amp) if amp else 5.0
    r, hit, have = {"X": round(X, 2), "r0": round((K[i][3] / px - 1) * 100, 2)}, False, 0
    for k in (1, 2, 3):
        if i + k < len(K):
            have = k
            r[f"h{k}"] = round((K[i + k][1] / px - 1) * 100, 2)
            r[f"c{k}"] = round((K[i + k][3] / px - 1) * 100, 2)
            hit = hit or r[f"h{k}"] >= X
    r["label"] = "正" if hit else ("负" if r.get("c3", 0) < 0 else "平") if have == 3 else f"待核{3 - have}"
    return r


def all_rules(skill):
    p = ROOT / "skills" / f"{skill}-skill" / "persona" / "rules.md"
    try:
        t = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {m.group(1): m.group(2).strip()[:60] for m in re.finditer(r"(?m)^#{3,4} (R\d+)\b[\s:：·]*(.*)$", t)}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows, cache, tgt = [], {}, []
    for f in sorted([*LIVE.glob("20*/live_*/state.json"), *LIVE.glob("20*/paper_*/state.json")]):
        D, ln = f.parent.parent.name, f.parent.name
        sk = line_skill(ln)
        if not sk or D >= "2099":
            continue
        try:
            st_ = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for t in st_.get("trades") or []:
            if t.get("side") != "BUY":
                continue
            try:   # 10/25 用户选 H: 每笔买入标"买之前今天有没有被加红电报点名、哪一类", 按类别累计实盘(模拟)结果
                import telegraph_now as TGN
                hs = TGN.named(D, str(t.get("t") or "23:59:59")).get(str(t["code"])) or []
            except Exception:   # noqa: BLE001
                hs = []
            if hs:
                tgt.append({"D": D, "line": ln, "t": t.get("t"), "code": t["code"], "name": t.get("name"), "act": hs[-1]["act"], "tg_t": hs[-1]["t"],
                            **label(str(t["code"]), D, float(t["px"]), cache)})
            ids = cited(t.get("why"))
            if not ids:
                continue
            res = label(str(t["code"]), D, float(t["px"]), cache)
            own = all_rules(sk)
            for rid in ids:
                if rid.startswith(("E", "Q")):   # E / Q 编号是材料条目, 不是规则
                    continue
                pre = re.match(r"[A-Z]+", rid).group(0)
                owner = sk if rid in own else KNOW.get(pre, sk)
                rows.append({"rule": f"{owner}:{rid}", "line": ln, "D": D, "t": t.get("t"), "code": t["code"], "name": t.get("name"), "px": t["px"],
                             "why": re.sub(r"\s+", " ", str(t.get("why") or ""))[:300], **res})
    try:
        verd = json.loads(VERD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        verd = {}
    g = collections.defaultdict(list)
    for r in rows:
        g[r["rule"]].append(r)
    H = {}
    for k, xs in g.items():
        n = collections.Counter(x["label"][:2] for x in xs)
        done = n["正"] + n["负"] + n["平"]
        c1 = [x["c1"] for x in xs if x.get("c1") is not None]
        H[k] = {"n": len(xs), "正": n["正"], "负": n["负"], "平": n["平"], "待核": n["待核"], "c1_mean": round(st.mean(c1), 2) if c1 else None,
                "suspect": done >= SUSPECT["min_done"] and n["负"] > n["正"], "verdict": (verd.get(k) or {}).get("verdict")}
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.write_text(json.dumps({"built": dt.datetime.now().isoformat(timespec="seconds"), "rules": H}, ensure_ascii=False, indent=1), encoding="utf-8")
    days = sorted({r["D"] for r in rows})
    L = [f"# 规则体检 · 可疑规则待你核销（{dt.date.today()} 重算；成交数据 {days[0] if days else '-'} ~ {days[-1] if days else '-'}，{len(rows)} 条\"买入 × 引用规则\"）", "",
         "> 脚本 `scripts/ontology/rule_health.py`（零 token）。只统计**成交了的买入**、按它 why 末尾「依据：」引用的规则编号归账；标签口径同样例库（正 = T+1~T+3 最高 ≥ 成交价 +X%）。",
         f"> 可疑 = 已判定 ≥ {SUSPECT['min_done']} 笔且负 > 正。核销写在 `docs/review/rule_verdicts.json`（或直接跟我说\"zhiyingjuexin:R10 确认错误 / 驳回 / 再观察\"）。", "",
         "## 可疑（负 > 正）", "", "| 规则 | 规则原文 | 引用买入 | 正 / 负 / 平 / 待核 | T+1 收盘均值 | 你的核销 |", "|---|---|---|---|---|---|"]
    titles = {}

    def title(k):
        sk, rid = k.split(":")
        if sk not in titles:
            titles[sk] = all_rules(sk)
        return titles[sk].get(rid, "")
    sus = sorted((k for k, v in H.items() if v["suspect"]), key=lambda k: -H[k]["负"])
    for k in sus:
        v = H[k]
        L.append(f"| {k} | {title(k)} | {v['n']} | {v['正']} / {v['负']} / {v['平']} / {v['待核']} | {v['c1_mean']} | {v['verdict'] or '待核销'} |")
    if not sus:
        L.append("| （暂无：已判定样本还太少） | | | | | |")
    for k in sus:
        L += ["", f"### {k} {title(k)} — 最差几例", ""]
        for x in sorted([x for x in g[k] if x["label"] == "负"], key=lambda x: x.get("c3", 0))[:4]:
            L.append(f"- {x['D']} {x['t']} {x['line']} 买 {x['name']}({x['code']}) @{x['px']} · T+1 高 {x.get('h1')} 收 {x.get('c1')} · T+3 收 {x.get('c3')} · X={x['X']}%  \n  当时理由：{x['why']}")
    L += ["", "## 全部被引用过的规则", "", "| 规则 | 引用买入 | 正 / 负 / 平 / 待核 | T+1 收盘均值 |", "|---|---|---|---|"]
    for k, v in sorted(H.items(), key=lambda kv: -kv[1]["n"]):
        L.append(f"| {k} {title(k)[:30]} | {v['n']} | {v['正']} / {v['负']} / {v['平']} / {v['待核']} | {v['c1_mean']} |")
    used = collections.defaultdict(set)
    for k in H:
        sk, rid = k.split(":")
        used[sk].add(rid)
    L += ["", "## 从没被引用过的规则（按导师；可能是死规则，也可能是模型没看到）", ""]
    for sk in sorted({line_skill(f.parent.name) for f in [*LIVE.glob("20*/live_*/state.json"), *LIVE.glob("20*/paper_*/state.json")]} - {None}):
        R = all_rules(sk)
        un = [f"{r} {R[r][:24]}" for r in R if r not in used[sk]]
        if R:
            L.append(f"- **{sk}**（{len(R)} 条里 {len(un)} 条没被引用）：" + "；".join(un[:40]) + (" …" if len(un) > 40 else ""))
    L += ["", "## 电报点名后买入（按点名动作分类；10/25 用户选 H）", "", "| 点名动作 | 买入笔数 | 正 / 负 / 平 / 待核 | 例 |", "|---|---|---|---|"]
    ga = collections.defaultdict(list)
    for x in tgt:
        ga[x["act"]].append(x)
    for k, xs in sorted(ga.items(), key=lambda kv: -len(kv[1])):
        n = collections.Counter(x["label"][:2] for x in xs)
        L.append(f"| {k} | {len(xs)} | {n['正']} / {n['负']} / {n['平']} / {n['待核']} | " + "；".join(f"{x['D'][5:]} {x['line']} {x['name']} 点名 {x['tg_t'][:5]} 买 {str(x['t'])[:5]} → {x['label']}" for x in xs[:3]) + " |")
    if not tgt:
        L.append("| （还没有） | | | |")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
