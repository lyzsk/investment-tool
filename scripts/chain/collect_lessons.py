# -*- coding: utf-8 -*-
"""collect_lessons.py — 07 复盘 lessons 汇总(零 token, 10/16 晚 持有期改造: 沉淀 know-how)
扫 results/<skill>_chain/{live|asof}-<日>/07_review.md(缺则 slots/review/07_review.md)的 contract:
  lessons=[{"type":"规则草案|规则修正|错误归因","text","evidence"}] → 按导师分组、同类型去重(规范化后全等 或 相似度≥0.85 并为一条)、标出现次数与日期;
  多日核对=[{"result":"对|部分对|错|无法判断"}] → 每位导师的多日判断命中率一行; 拟人对照(tzzb 导师链)=[{"项","一致","原因"}] → 各项不一致次数+原因分布一行。
  --legacy: 旧版 07(无 lessons)的 预案对照[].教训 也收进来(类型记"旧版教训", 只作参考)
输出: scripts/chain/reports/lessons_<结束日>.md(供每周人工/蒸馏时并入 persona rules; 本脚本只汇总, 不写 rules.md)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/chain/collect_lessons.py [--days 7] [--date 20261016] [--legacy] [--asof] [--out <md>]
  --days N=结束日往前 N 个自然日(含结束日); --asof=扫 asof-* 回放目录(缺省只扫 live-*)
"""
import argparse, difflib, json, re, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import mentors  # noqa: E402  10/17 二B-4: 导师登记表(名=short 括号前, 同 facts 导师速览节标题)
NAMES = {m: mentors.head(m) for m in mentors.ids()}
TYPES = ("规则草案", "规则修正", "case卡", "错误归因", "旧版教训")
SIM = 0.85


def contract_of(text):
    blocks = re.findall(r"```contract\s*\n([\s\S]*?)```", text)
    try:
        return json.loads(blocks[-1]) if blocks else None
    except json.JSONDecodeError:
        return None


def norm(s):
    return re.sub(r"[\s，,。．.；;：:、!！?？\"'“”‘’（）()【】\[\]—\-]+", "", str(s or "")).lower()


def scan(results, d0, d1, prefix, legacy):
    """→ {skill: {"lessons": [(type, text, evidence, date)], "multi": Counter-like dict, "files": n, "bad": [文件]}}"""
    out = {}
    for cd in sorted(results.glob("*_chain")):
        skill = cd.name[:-len("_chain")]
        for rd in sorted(cd.iterdir()):
            m = re.fullmatch(rf"{prefix}-(\d{{8}})(?:-.+)?", rd.name)
            if not m or not (d0 <= m.group(1) <= d1):
                continue
            f = rd / "07_review.md"
            if not f.exists():
                f = rd / "slots" / "review" / "07_review.md"
            if not f.exists():
                continue
            day = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
            s = out.setdefault(skill, {"lessons": [], "multi": {}, "mimic": {}, "files": 0, "bad": []})
            c = contract_of(f.read_text(encoding="utf-8"))
            if c is None:
                s["bad"].append(f.resolve().relative_to(ROOT).as_posix() if f.resolve().is_relative_to(ROOT) else str(f))
                continue
            s["files"] += 1
            for x in c.get("lessons") or []:
                if isinstance(x, dict) and str(x.get("text") or "").strip():
                    t = x.get("type") if x.get("type") in TYPES else "错误归因"
                    s["lessons"].append((t, str(x["text"]).strip(), str(x.get("evidence") or "").strip(), day))
            if legacy and c.get("lessons") is None:
                for x in c.get("预案对照") or []:
                    if isinstance(x, dict) and str(x.get("教训") or "").strip():
                        s["lessons"].append(("旧版教训", str(x["教训"]).strip(), f"{x.get('项', '')}（{x.get('结果', '')}）", day))
            for x in c.get("多日核对") or []:
                r = str((x or {}).get("result") or "") if isinstance(x, dict) else ""
                for k in ("部分对", "无法判断", "对", "错"):
                    if r.startswith(k):
                        s["multi"][k] = s["multi"].get(k, 0) + 1
                        break
            for x in c.get("拟人对照") or []:   # tzzb 导师链: (项, 原因) 不一致计数
                if isinstance(x, dict) and x.get("一致") is False:
                    key = (str(x.get("项") or "?"), str(x.get("原因") or "?")[:8])
                    s["mimic"][key] = s["mimic"].get(key, 0) + 1
    return out


def dedupe(items):
    """同类型内: 规范化全等或相似度≥SIM 并为一组, 代表文本取最长那条; 按出现次数降序"""
    groups = []
    for t, text, ev, day in items:
        n = norm(text)
        for g in groups:
            if g["type"] == t and (g["norm"] == n or difflib.SequenceMatcher(None, g["norm"], n).ratio() >= SIM):
                g["n"] += 1
                g["days"].add(day)
                g["evs"].append(ev)
                if len(text) > len(g["text"]):
                    g["text"], g["norm"] = text, n
                break
        else:
            groups.append({"type": t, "text": text, "norm": n, "n": 1, "days": {day}, "evs": [ev]})
    return sorted(groups, key=lambda g: (-g["n"], TYPES.index(g["type"]), min(g["days"])))


def render(data, d0, d1, legacy):
    L = [f"# 07 复盘 lessons 汇总 {d0}~{d1}（collect_lessons.py 零 token 生成；{'含旧版教训; ' if legacy else ''}只汇总不写 rules.md）", "",
         "> 用法：每周人工/蒸馏时挑出现≥2 次或证据扎实的「规则草案/规则修正」并入对应导师 persona rules（单样本=候选，先找反例再收）；「case卡」同情境反复出现才升格为规则草案；「错误归因」看是否反复同因。", ""]
    if not data:
        return "\n".join(L + ["（区间内没有 07 复盘产物）", ""])
    for skill in sorted(data, key=lambda k: (k == "control", k)):
        s = data[skill]
        groups = dedupe(s["lessons"])
        mt = sum(s["multi"].values())
        L.append(f"## {NAMES.get(skill, skill)}（{skill}）— 07 共 {s['files']} 份, lessons {len(s['lessons'])} 条 → 去重 {len(groups)} 条")
        if mt:
            hit = s["multi"].get("对", 0) + 0.5 * s["multi"].get("部分对", 0)
            judged = mt - s["multi"].get("无法判断", 0)
            L.append(f"- 多日核对: " + " / ".join(f"{k} {s['multi'].get(k, 0)}" for k in ("对", "部分对", "错", "无法判断"))
                     + (f"；命中率(部分对记半) {hit / judged:.0%}" if judged else ""))
        if s["mimic"]:
            L.append("- 拟人偏差(不一致次数): " + " / ".join(f"{k[0]}·{k[1]} {v}" for k, v in sorted(s["mimic"].items(), key=lambda kv: -kv[1])))
        if s["bad"]:
            L.append(f"- ⚠ contract 解析失败: {', '.join(s['bad'])}")
        for g in groups:
            days = sorted(g["days"])
            ev = next((e for e in g["evs"] if e), "")
            L.append(f"- [{g['type']}] ×{g['n']}（{', '.join(d[5:] for d in days)}）{g['text']}" + (f"  \n  证据: {ev}" if ev else ""))
        if not groups:
            L.append("- （无 lessons）")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--asof", action="store_true")
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--out")
    a = ap.parse_args()
    d1 = a.date.replace("-", "")
    d0 = (datetime.strptime(d1, "%Y%m%d") - timedelta(days=max(1, a.days) - 1)).strftime("%Y%m%d")
    data = scan(Path(a.results), d0, d1, "asof" if a.asof else "live", a.legacy)
    md = render(data, f"{d0[:4]}-{d0[4:6]}-{d0[6:]}", f"{d1[:4]}-{d1[4:6]}-{d1[6:]}", a.legacy)
    out = Path(a.out) if a.out else ROOT / "scripts" / "chain" / "reports" / f"lessons_{d1}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    n = sum(len(v["lessons"]) for v in data.values())
    print(f"{len(data)} 条链 / {sum(v['files'] for v in data.values())} 份 07 / {n} 条 lessons → {out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
