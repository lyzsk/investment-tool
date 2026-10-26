# -*- coding: utf-8 -*-
"""viewer_check.py — viewer_<日>.html 自测(10/24): JS 语法(node --check) + DATA 能解析 + 新字段齐全且数对得上; 只读, 零 token
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/viewer_check.py [--date 2026-10-23]
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import line_dirs as LDS   # noqa: E402  10/25 账本目录命名(live_<skill> / paper_<id>)
sys.path[:0] = [str(Path(__file__).resolve().parent)]
import viewer_extra as X   # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not ok:
        FAIL.append(name)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-23")
    D = ap.parse_args().date
    f = ROOT / "results" / "inv-stock" / "paper_line" / f"viewer_{D}.html"
    h = f.read_text(encoding="utf-8")
    check("① 文件 < 20MB", f.stat().st_size < 20e6, f"{f.stat().st_size / 1e6:.1f} MB")
    js = re.findall(r"<script>(.*?)</script>", h, re.S)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as t:
        t.write("\n".join(js))
    r = subprocess.run(["node", "--check", t.name], capture_output=True, text=True, encoding="utf-8")
    Path(t.name).unlink(missing_ok=True)
    check("② node --check 模板 JS", r.returncode == 0 and len(js) == 1, (r.stderr or "").strip()[:300] or f"{sum(map(len, js))} 字")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', h, re.S)
    d = json.loads(m.group(1).replace("<\\/", "</"))
    check("③ DATA JSON 能解析", isinstance(d, dict) and d.get("books"), f"{len(d['books'])} 本")
    B = d["books"]
    base = ROOT / "results" / "_live" / D
    nver = sum(len(list((base / LDS.ldir(b["id"]) / "versions").glob("*"))) for b in B)
    V = [v for b in B for v in b["versions"]]
    check("④ 版本数 = results/_live 下 versions 目录数", len(V) == nver, f"{len(V)} / {nver}")
    O = [o for v in V for o in v["orders"]]
    n06 = sum(len(c.get("rules") or []) for b in B for vd in (base / LDS.ldir(b["id"]) / "versions").glob("*") if (vd / "06.json").exists()
              for c in json.loads((vd / "06.json").read_text(encoding="utf-8")).get("codes") or [])
    check("⑤ 每张挂单都有结局字段(cat + why)", all(o.get("fate", {}).get("cat") and o["fate"].get("why") for o in O) and len(O) == n06, f"{len(O)} 张 / 06.json 规则 {n06} 条")
    fills = sum(1 for o in O if o["fate"]["cat"] == "成交")
    rule_fills = {(b["id"], t.get("rule")) for b in B for t in b["trades"] if t.get("rule")}   # rule = 版号:代码:规则号, 只在本账内唯一
    check("⑥ 结局'成交'张数 = state.trades 里不同 rule 数", fills == len(rule_fills), f"{fills} / {len(rule_fills)}")
    nat = [o for o in O if o["fate"]["cat"] not in ("执行器剔除",) and isinstance(o.get("px"), (int, float))]
    check("⑦ 进了生效策略的挂单都有之后走势(收盘相对挂单价)", all("dc" in o["fate"] for o in nat), f"{sum(1 for o in nat if o['fate'].get('dc') is not None)}/{len(nat)} 有价")
    check("⑧ 每版都有排队字段且 wait = hold + gate ≥ 0", all(v.get("q") and v["q"]["wait"] == v["q"]["hold"] + v["q"]["gate"] and v["q"]["wait"] >= 0 for v in V), f"{len(V)} 版")
    nq = sum(1 for v in V if str(v.get("why") or "").startswith("(排队补叫)"))
    check("⑨ 排队补叫的版本都对上了重定排队时刻", sum(1 for v in V if v["q"]["src"] == "重定排队") == nq, f"补叫 {nq} 版")
    T = d["tpm"]
    nA = len(X.AXIS)
    lens = [len(a[k]) for mode in ("spread", "start") for a in T[mode].values() for k in ("tok", "est")]
    check("⑩ 每分钟 token 数组长度 = 分钟轴(09:00~11:29 + 13:00~14:59)", T["axis"] == X.AXIS and set(lens) == {nA} and nA == 270, f"{nA} 分钟, {len(lens)} 条数组")
    check("⑪ 每分钟数组覆盖 全部 + 每本", set(T["spread"]) == {"all", *[b["id"] for b in B]})
    for mode in ("spread", "start"):
        a = T[mode]["all"]
        s = sum(a["tok"]) + sum(a["est"]) + T["spill"][mode]
        check(f"⑫ token 守恒({mode}): 轴上 + 轴外 = 全部调用合计", abs(s - T["total"]) <= 2 * nA, f"{s:,} vs {T['total']:,}")
        per = sum(sum(T[mode][b["id"]]["tok"]) + sum(T[mode][b["id"]]["est"]) for b in B)
        check(f"⑬ 各本之和 = 合计({mode})", abs(per - sum(a["tok"]) - sum(a["est"])) <= 2 * nA * len(B))
    ctx = sum(X.ctx(s) + (s.get("out") or 0) for v in V for s in v["steps"] if s.get("cr") is not None) + sum((k.get("cr") or 0) + (k.get("cw") or 0) for b in B for k in b["keep"])
    est = sum(next((X.ctx(s) + (s.get("out") or 0) for s in v["steps"] if s["name"] == "04"), 0) for v in V for s in v["steps"] if s["name"] in ("03_bull", "03_bear"))
    check("⑭ 合计 token = 有明细步骤 + 保温 + 03 估(同版 04)", T["total"] == ctx + est, f"{T['total']:,} = 明细 {ctx:,} + 03 估 {est:,}")
    mim = [b for b in B if b.get("kind") == "mimic"]
    check("⑮ 拟人账都有导师对照(verdict + 收盘仓位)", all(b.get("mentor_day") and b["mentor_day"]["verdict"] and b["mentor_day"]["close"] for b in mim)
          and all(b.get("mentor_day") is None for b in B if b.get("kind") != "mimic"), f"{len(mim)} 本拟人")
    K = [k for b in B for k in b["keep"]]
    nk = sum(1 for b in B for l in (base / LDS.ldir(b["id"]) / "events.jsonl").read_text(encoding="utf-8").splitlines() if '"缓存保温"' in l)
    check("⑯ 保温每次都在、都有 idle / note / bad", len(K) == nk and all("idle" in k and k.get("note") and "bad" in k for k in K), f"{len(K)} / events {nk}")
    big = max(K, key=lambda k: k.get("cw") or 0) if K else {}
    check("⑰ 已知异常被标红: 缓存写最大那次 bad=True", bool(big.get("bad")), f"{big.get('start')} 缓存写 {big.get('cw')} ${big.get('usd')}")
    c = d["calc"]
    check("⑱ 计算器两组默认值齐全", all(set(c[k]) == {"R", "Q", "O", "N", "S", "H"} for k in ("now", "slim")) and c["slim"]["R"] == 40000 and c["slim"]["S"] == 1, json.dumps(c, ensure_ascii=False))
    for fn in ("keepCard", "waitCard", "tpmCard", "drawTPM", "fateCard", "calcCard", "calcRun", "mentorCard", "keepBookCard", "probsCard"):
        if not re.search(rf"function {fn}\(", js[0]):
            check(f"⑲ 模板有 {fn}", False)
    check("⑲ 模板新函数都在", not any(x.startswith("⑲") for x in FAIL))
    print(f"\n{'全部通过' if not FAIL else '失败 ' + str(len(FAIL)) + ' 项: ' + ', '.join(FAIL)}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
