# -*- coding: utf-8 -*-
"""theme_life.py — 题材生命周期(v3 命名查询工具; 零 token, 零外部请求; 10/22 晚用户令 "1、2、3 先做")

回答: "这个题材现在走到第几天? 在发酵、高潮、分歧还是退潮? 这只票挂在哪些题材下?"
来源: md 每日「## 涨停分析」节(1/15 起约 184 天; 每个 ### 是一个题材, 表格 = 该题材涨停 / 大涨股 + 板数 + 涨停时间 + 上涨逻辑)
      财联社涨停池 downloads/cls_pool/<日>/up_pool.json 只有 10/13 起 8 天, 暂不用
第一步 同义合并(--alias 重建):
  ①规整: 去 "概念 / 板块 / 产业链 / 方向 / 题材"、去 "(数字)"、全半角统一
  ②人工表 ALIAS_SEED(写死的同义词, 最优先) + scripts/paper_line/catalog/theme_alias_manual.json(你改这个, 覆盖一切)
  ③自动只出"建议"不生效: 小题材的股票 ≥70% 落在大题材里且共同股 ≥ 5 → 列为建议(实测这类多是 "父子" 关系, 如 化肥⊂化工、腾讯⊂算力工程, 不能直接并)
  产物: scripts/paper_line/catalog/theme_alias.json(规整名 → 标准名 + 依据)
第二步 生命周期(只用 D 之前的日子 = 盘前视角; --after 用含 D 当天 = 盘后视角):
  每题材每天: 涨停家数(涨停时间不是 "--") / 大涨家数 / 最高板 / 首板占比
  连续段: 断档 ≤ 2 个交易日算同一波; 第几天 = 本波第几个出现日
  阶段(规则, 依据近 3 个出现日): 首日 / 发酵(家数或高度上升) / 高潮(家数 = 本波最大且 ≥ 5) / 分歧(家数降、高度升或持平) / 退潮(家数和高度都降) / 断档(最近 2 天没出现)
用法:
  python theme_life.py --alias                       (重建同义表, 打印自动合并的组待核)
  python theme_life.py --theme 机器人 --date 2026-10-23
  python theme_life.py --stock 太极股份 --date 2026-10-23   (这只票近 20 天挂过的题材 + 各题材生命周期)
  python theme_life.py --top --date 2026-10-23       (近 5 天最活跃的 15 个题材)
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAT = ROOT / "scripts" / "paper_line" / "catalog"
ALIAS_F = CAT / "theme_alias.json"
MANUAL_F = CAT / "theme_alias_manual.json"
REL_F = CAT / "theme_related.json"   # 10/23 用户定: 成分股高度重叠的两个题材多半是父子 / 关联, 不是同义 → 不合并, 记成关联(查一个顺带给另一个的阶段)
NOT_THEME = {"复盘持仓", "龙虎榜", "其他", "同花顺投资账本", "其它"}
# 明显同义, 先写死(左 = 规整后的名字, 右 = 标准名); 拿不准的不写, 交给自动 + 你核
ALIAS_SEED = {"ST股": "ST", "摘帽": "ST", "液冷IDC": "液冷", "光纤光缆": "光通信", "芯片": "半导体", "存储器": "半导体",
              "有色金属": "有色", "黄金": "有色", "AI": "AI应用", "油气设服": "油气设备", "医药生物": "医药", "创新药": "医药",
              "短剧": "文化传媒", "影视": "文化传媒", "钠电池": "锂电池", "固态电池": "锂电池", "PEEK材料": "PEEK", "航运港口": "航运",
              "半导体设备": "半导体", "人形机器人": "机器人", "CRO/CMO": "医药", "CXO/CMO": "医药", "液冷服务器": "液冷"}


def norm(t):
    t = t.strip().replace("（", "(").replace("）", ")").replace("＋", "+")
    t = re.sub(r"\s+", "", t)                       # "AI 应用" = "AI应用"
    t = re.sub(r"\((\d+|[^)]*日)\)$", "", t)         # "ST股(8)" / "芯片产业链(6 月 30 日)"
    t = re.sub(r"(概念|板块|产业链|方向|题材)$", "", t).strip()
    return t


def boards(s):
    s = s.replace(" ", "")
    if "首板" in s:
        return 1
    m = re.search(r"(\d+)天(\d+)板", s) or re.search(r"(\d+)连板", s)
    if m:
        return int(m.group(m.lastindex))
    return 0


def parse_md():
    """→ [(日, 原题材名, 股票名, 代码或空, 板数, 涨停?, 涨停时间, 上涨逻辑)]"""
    out = []
    for f in sorted(ROOT.glob("md/*/*.md")):
        d = f.stem
        if not re.match(r"\d{4}-\d{2}-\d{2}$", d):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^## 涨停分析\s*$(.*?)(?=^## |\Z)", txt, re.S | re.M)
        if not m:
            continue
        theme = None
        for line in m.group(1).splitlines():
            if line.startswith("### "):
                theme = line[4:].strip()
                continue
            if not theme or not line.startswith("|") or "股票名称" in line or re.match(r"^\|\s*:?-", line):
                continue
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) < 5:
                continue
            nm = c[0].split("<br>")[0].strip()
            code = (re.search(r"\d{6}", c[0]) or [None])[0] if "<br>" in c[0] else None
            zt_t = c[3]
            out.append((d, theme, nm, code or "", boards(c[1]), bool(re.match(r"\d{1,2}:\d{2}", zt_t)), zt_t, c[4]))
    return out


def build_alias(rows):
    S = defaultdict(set)
    for d, th, nm, *_ in rows:
        n = norm(th)
        if n and n not in NOT_THEME:
            S[n].add(nm)
    canon = {n: (ALIAS_SEED.get(n, n), "人工表" if n in ALIAS_SEED else "本名") for n in S}
    # 自动只给建议: 小题材股票大部分落在大题材里(父子或同义, 要人判)
    names = sorted(S, key=lambda n: -len(S[n]))
    auto = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = len(S[a] & S[b])
            if inter >= 5 and inter / len(S[b]) >= 0.7 and canon[b][0] != canon[a][0]:
                auto.append((b, "→", a, f"共同 {inter} / {b} 共 {len(S[b])} 只"))
    if MANUAL_F.exists():
        for k, v in json.loads(MANUAL_F.read_text(encoding="utf-8")).items():
            canon[norm(k)] = (v, "你改的")
    # 关联题材: 重叠关系 + "同日涨停共现率"(小题材出现的日子里, 大题材当天也有涨停的比例)当联动度 —— 共现高 = 真同涨同跌, 低 = 只是成分股重叠
    days_of = defaultdict(set)
    for d, th, *_ in rows:
        days_of[norm(th)].add(d)
    codes_of = defaultdict(set)
    for d, th, nm, code, *_ in rows:
        if code:
            codes_of[norm(th)].add(code)
    nb = {}
    try:   # 拓扑联动度(用户 01:1x: "它们是拓扑关系相似度高"): 小题材的票里, 有几成的拓扑前 5 邻居里有大题材的票(最近一份拓扑回算)
        hs = sorted((ROOT / "downloads" / "market" / "topology_hist").glob("20*.jsonl"))
        if hs:
            for l in hs[-1].read_text(encoding="utf-8").splitlines():
                r = json.loads(l)
                nb[r["c"]] = {x["c"] for x in r.get("nb") or []}
    except (OSError, ValueError):
        pass

    def topo(small, big):
        xs = [c for c in codes_of[small] if c in nb]
        return round(sum(1 for c in xs if nb[c] & codes_of[big]) / len(xs), 2) if xs else None
    rel = defaultdict(list)
    for b, _, a, why in auto:
        co = len(days_of[b] & days_of[a]) / len(days_of[b]) if days_of[b] else 0
        rel[b].append({"关联": a, "关系": f"多半是父子 / 关联({why})", "同日涨停共现率": round(co, 2), "拓扑联动": topo(b, a)})
        rel[a].append({"关联": b, "关系": f"子题材({why})", "同日涨停共现率": round(len(days_of[a] & days_of[b]) / len(days_of[a]), 2) if days_of[a] else 0, "拓扑联动": topo(a, b)})
    REL_F.write_text(json.dumps(dict(sorted(rel.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    CAT.mkdir(parents=True, exist_ok=True)
    sug = {x[0]: f"建议并入 {x[2]}({x[3]})" for x in auto}
    ALIAS_F.write_text(json.dumps({k: {"标准名": v[0], "依据": v[1], "股票数": len(S.get(k, ())), **({"建议": sug[k]} if k in sug else {})} for k, v in sorted(canon.items())},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return canon, auto


_ROWS = None


def rows_canon():
    global _ROWS
    if _ROWS is None:
        rows = parse_md()
        if ALIAS_F.exists():
            A = {k: v["标准名"] for k, v in json.loads(ALIAS_F.read_text(encoding="utf-8")).items()}
        else:
            A = {k: v[0] for k, v in build_alias(rows)[0].items()}
        _ROWS = [(d, A.get(norm(th), norm(th)), nm, code, b, zt, t, lg) for d, th, nm, code, b, zt, t, lg in rows if norm(th) not in NOT_THEME]
    return _ROWS


def daily_stats(theme, D, after=False):
    R = [r for r in rows_canon() if r[1] == theme and (r[0] <= D if after else r[0] < D)]
    days = sorted({r[0] for r in rows_canon() if (r[0] <= D if after else r[0] < D)})
    by = defaultdict(list)
    for r in R:
        by[r[0]].append(r)
    ser = []
    for d in days:
        x = by.get(d, [])
        ser.append({"d": d, "涨停": sum(1 for r in x if r[5]), "大涨": sum(1 for r in x if not r[5]), "最高板": max([r[4] for r in x] or [0]),
                    "首板占比": round(sum(1 for r in x if r[4] == 1) / max(1, sum(1 for r in x if r[5])), 2), "票": [r[2] for r in x if r[5]][:8]})
    return ser


def life_one(theme, D, after=False):
    return life(theme, D, after, rel=False)


def life(theme, D, after=False, rel=True):
    ser = daily_stats(theme, D, after)
    if not ser:
        return {"err": "没有数据"}
    on = [i for i, s in enumerate(ser) if s["涨停"] > 0]
    if not on:
        return {"题材": theme, "D": D, "阶段": "从未出现"}
    # 本波: 从最近一个出现日往回, 断档 ≤ 2 个交易日算同一波
    j = len(on) - 1
    while j > 0 and on[j] - on[j - 1] <= 3:
        j -= 1
    wave = [ser[i] for i in on[j:]]
    gap = len(ser) - 1 - on[-1]
    last3 = wave[-3:]
    peak = max(w["涨停"] for w in wave)
    cur = wave[-1]
    if gap >= 2:
        stage = f"断档(最近 {gap} 个交易日没出现)"
    elif len(wave) == 1:
        stage = "首日"
    else:
        prev = wave[-2]
        if cur["涨停"] == peak and cur["涨停"] >= 5 and cur["涨停"] >= prev["涨停"]:
            stage = "高潮(家数 = 本波最大)"
        elif cur["涨停"] > prev["涨停"] or cur["最高板"] > prev["最高板"]:
            stage = "发酵(家数或高度上升)"
        elif cur["最高板"] >= prev["最高板"]:
            stage = "分歧(家数降、高度没降)"
        else:
            stage = "退潮(家数和高度都降)"
    return {"题材": theme, "D": D, "视角": "盘后(含 D)" if after else "盘前(截至 D−1)", "阶段": stage,
            "本波第几天": len(wave), "本波起点": wave[0]["d"], "本波峰值家数": peak, "最近一次出现": cur["d"],
            "近 3 个出现日": [{k: w[k] for k in ("d", "涨停", "大涨", "最高板", "首板占比", "票")} for w in last3],
            "历史波数": sum(1 for a, b in zip([-99] + on, on) if b - a > 3), **(related(theme, D, after) if rel else {})}


def related(theme, D, after=False):
    """关联题材(父子 / 重叠)此刻的阶段; 只查一层, 不递归"""
    try:
        R = json.loads(REL_F.read_text(encoding="utf-8")).get(theme) or []
    except (OSError, ValueError):
        return {}
    out = []
    for x in R[:3]:
        L = life_one(x["关联"], D, after)
        tp = x.get("拓扑联动")
        out.append(f"{x['关联']}({x['关系'][:8]}; 同日涨停共现 {x['同日涨停共现率']:.0%}" + (f"; 拓扑联动 {tp:.0%}" if tp is not None else "") + f"): {L.get('阶段', '无数据')}")
    return {"关联题材": out} if out else {}


def by_stock(name_or_code, D, after=False, look=20):
    days = sorted({r[0] for r in rows_canon() if (r[0] <= D if after else r[0] < D)})[-look:]
    R = [r for r in rows_canon() if r[0] in days and (r[2] == name_or_code or r[3] == name_or_code)]
    th = defaultdict(list)
    for r in R:
        th[r[1]].append(f"{r[0]} {('%d 板' % r[4]) if r[4] else '大涨'} {r[7]}")
    return {"票": name_or_code, "D": D, f"近 {look} 个交易日挂过的题材": {t: {"出现": v, "生命周期": life(t, D, after)} for t, v in th.items()}}


def top(D, after=False, n=15):
    days = sorted({r[0] for r in rows_canon() if (r[0] <= D if after else r[0] < D)})[-5:]
    cnt = defaultdict(int)
    for r in rows_canon():
        if r[0] in days and r[5]:
            cnt[r[1]] += 1
    out = []
    for t, c in sorted(cnt.items(), key=lambda x: -x[1])[:n]:
        L = life(t, D, after)
        out.append(f"{t}: 近 5 日涨停 {c} 家 | {L.get('阶段')} | 本波第 {L.get('本波第几天')} 天 | 峰值 {L.get('本波峰值家数')} 家")
    return {"D": D, "近 5 日最活跃题材": out}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", action="store_true")
    ap.add_argument("--theme")
    ap.add_argument("--stock")
    ap.add_argument("--top", action="store_true")
    ap.add_argument("--date", default="9999-12-31")
    ap.add_argument("--after", action="store_true")
    a = ap.parse_args()
    if a.alias:
        rows = parse_md()
        canon, auto = build_alias(rows)
        print("解析行", len(rows), "| 天数", len({r[0] for r in rows}), "| 规整后题材名", len(canon), "| 标准名", len({v[0] for v in canon.values()}))
        print("自动建议(没生效; 认可的写进 theme_alias_manual.json, 格式 {\"化肥\": \"化工\"}):")
        for x in auto:
            print("  ", x)
        return
    if a.theme:
        t = norm(a.theme)
        if ALIAS_F.exists():
            t = json.loads(ALIAS_F.read_text(encoding="utf-8")).get(t, {}).get("标准名", t)
        out = life(t, a.date, a.after)
    elif a.stock:
        out = by_stock(a.stock, a.date, a.after)
    else:
        out = top(a.date, a.after)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
