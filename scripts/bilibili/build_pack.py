# -*- coding: utf-8 -*-
"""build_pack.py — B站视频「素材包」(零 token, 10/14 建, TODO §3-A 第 15 条)
动机: 写 md(sum)会话中位 80~96 轮工具调用、单次读缓存 300~550 万 token——大头是模型自己翻 567KB 的 vision.json、
  自己查代码、自己拉行情算快照。这些全是机械活, 前移成脚本, 写 md 的会话只读一份 pack 就能下笔。
产物: results/bilibili/<mid>/<yyyy.MM.dd>/<bvid>.pack.md, 内容:
  ① 抬头行(标题/链接/发布时刻/时长, 照 sum.md 格式) ② 逐字稿引用块(按 ~120 字机械分段, 原文不改)
  ③ 画面要点(pages: 持仓高亮紫/灰帧票数、注意力榜前 10、BS 买卖点、持仓快照、自选股、页面分布) + VLM 逐帧精简行(去 null)
  ④ 代码表(名称→6 位码, 证券主表精确匹配; 对不上标 [?]) ⑤ 分层技术快照(T1 持仓=完整, T2 注意力前 5+BS=完整, T3 口述提及=一行),
     截至发布日收盘(as-of, 回填历史日不偷看后面的 K 线), 字段照 sum.md §3.5: MA5/10/20/60/120/144 · MACD(12,26,9) · RSI6/12/24(Wilder)
     · KDJ(9,3,3) · CCI14 · 30 日振幅中位 · 120 日区间高低+位置% · 近 20 日前高前低 · 近 60 日未回补缺口 · 均线排列
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/bilibili/build_pack.py --up taoge --date 2026-10-14 [--force]
      (--date 缺省=扫该 UP results 里所有缺 pack 的日子; 行情缺档时调 kline.mjs 补, 每票 ≤1 次请求)
"""
import argparse, datetime as dt, json, re, statistics as st, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPS = json.loads((ROOT / "scripts" / "backfill_bilibili" / "ups.json").read_text(encoding="utf-8"))
NOWIN = 0x08000000


def sec_master():
    for d in sorted((ROOT / "downloads" / "market").glob("20??-??-??"), reverse=True):
        f = d / "security_master.jsonl"
        if f.exists():
            m = {}
            for line in f.read_text(encoding="utf-8").splitlines():
                j = json.loads(line)
                if j.get("secType") in ("STOCK", None):
                    m[j["name"].replace(" ", "")] = j["code"]
            return m
    return {}


def paragraphs(txt, n=120):
    out, cur = [], ""
    for line in [l.strip() for l in txt.splitlines() if l.strip()]:
        cur += line
        if len(cur) >= n:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return out


def daily(code, upto, fetch=True):
    f = ROOT / "downloads" / "quotes" / "daily" / f"{code}.json"
    k = json.loads(f.read_text(encoding="utf-8"))["klines"] if f.exists() else []
    if fetch and (not k or k[-1]["d"] < upto):
        subprocess.run(["node", "scripts/quotes/kline.mjs", "--codes", code], cwd=ROOT, capture_output=True, timeout=60, creationflags=NOWIN)
        time.sleep(2)
        if f.exists():
            k = json.loads(f.read_text(encoding="utf-8"))["klines"]
    return [x for x in k if x["d"] <= upto]


def ema(xs, n):
    e, out = xs[0], []
    for x in xs:
        e = e + (x - e) * 2 / (n + 1); out.append(e)
    return out


def wilder_rsi(cs, n):
    if len(cs) < n * 4:
        return None
    up = dn = 0.0
    for i in range(1, len(cs)):
        ch = cs[i] - cs[i - 1]
        up = (max(ch, 0) + (n - 1) * up) / n; dn = (max(-ch, 0) + (n - 1) * dn) / n
    return 100.0 if dn == 0 else 100 * up / (up + dn)


def snapshot(k):
    if len(k) < 30:
        return None
    cs = [x["c"] for x in k]; last = k[-1]
    ma = {n: round(sum(cs[-n:]) / n, 2) for n in (5, 10, 20, 60, 120, 144) if len(cs) >= n}
    dif = [a - b for a, b in zip(ema(cs, 12), ema(cs, 26))]; dea = ema(dif, 9)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    kv = dv = 50.0
    for i in range(len(k)):
        w = k[max(0, i - 8):i + 1]; hh, ll = max(x["h"] for x in w), min(x["l"] for x in w)
        rsv = 50 if hh == ll else (k[i]["c"] - ll) / (hh - ll) * 100
        kv = (2 * kv + rsv) / 3; dv = (2 * dv + kv) / 3
    jv = 3 * kv - 2 * dv
    tp = [(x["h"] + x["l"] + x["c"]) / 3 for x in k[-14:]]; mtp = sum(tp) / len(tp)
    md = sum(abs(x - mtp) for x in tp) / len(tp)
    cci = (tp[-1] - mtp) / (0.015 * md) if md else 0
    amp = [(k[i]["h"] - k[i]["l"]) / k[i - 1]["c"] * 100 for i in range(max(1, len(k) - 30), len(k))]
    w120 = k[-120:]; hi, lo = max(x["h"] for x in w120), min(x["l"] for x in w120)
    w20 = k[-21:-1] if len(k) > 21 else k[:-1]
    gaps = []
    for i in range(max(1, len(k) - 60), len(k)):
        p, c = k[i - 1], k[i]
        if c["l"] > p["h"] and min(x["l"] for x in k[i:]) > p["h"]:
            gaps.append(f"{c['d'][5:]}上跳缺口{p['h']}~{c['l']}")
        if c["h"] < p["l"] and max(x["h"] for x in k[i:]) < p["l"]:
            gaps.append(f"{c['d'][5:]}下跳缺口{c['h']}~{p['l']}")
    order = [ma.get(n) for n in (5, 10, 20, 60) if ma.get(n)]
    arr = "多头排列" if order == sorted(order, reverse=True) else "空头排列" if order == sorted(order) else "交织"
    return {"d": last["d"], "c": last["c"], "chg": round((last["c"] / k[-2]["c"] - 1) * 100, 2), "ma": ma, "arr": arr,
            "macd": (round(dif[-1], 3), round(dea[-1], 3), round(hist[-1], 3)),
            "rsi": [None if wilder_rsi(cs, n) is None else round(wilder_rsi(cs, n), 1) for n in (6, 12, 24)],
            "kdj": (round(kv, 1), round(dv, 1), round(jv, 1)), "cci": round(cci, 1), "amp30": round(st.median(amp), 2) if amp else None,
            "r120": (hi, lo, round((last["c"] - lo) / (hi - lo) * 100) if hi > lo else None),
            "h20": max(x["h"] for x in w20) if w20 else None, "l20": min(x["l"] for x in w20) if w20 else None, "gaps": gaps[-3:]}


def fmt_full(name, code, s):
    if not s:
        return f"- {name}({code}): 日线档不足, 快照缺"
    ma = " ".join(f"MA{n}={v}" for n, v in s["ma"].items())
    return (f"- **{name}({code})** 截至 {s['d']} 收 {s['c']}({s['chg']:+}%) | {ma} | {s['arr']} | MACD dif/dea/柱 {s['macd'][0]}/{s['macd'][1]}/{s['macd'][2]}"
            f" | RSI6/12/24 {'/'.join(str(x) for x in s['rsi'])} | KDJ {'/'.join(str(x) for x in s['kdj'])} | CCI14 {s['cci']}"
            f" | 30日振幅中位 {s['amp30']}% | 120日区间 {s['r120'][1]}~{s['r120'][0]} 位置 {s['r120'][2]}% | 近20日高/低 {s['h20']}/{s['l20']}"
            f" | 未回补缺口: {'; '.join(s['gaps']) or '无'}")


def fmt_light(name, code, s):
    if not s:
        return f"- {name}({code}): 快照缺"
    return f"- {name}({code}) 收 {s['c']}({s['chg']:+}%) | 120日位置 {s['r120'][2]}% | {s['arr']}(MA5 {s['ma'].get(5)} / MA20 {s['ma'].get(20)})"


def build(up, day_dir, force=False):
    cfg = UPS[up]
    idx = json.loads((ROOT / "scripts" / "backfill_bilibili" / cfg["index"]).read_text(encoding="utf-8"))
    vids = {v["bvid"]: v for v in (idx.values() if isinstance(idx, dict) else idx)}
    names = sec_master()
    made = []
    for txt in sorted(day_dir.glob("BV*.txt")):
        if txt.name.endswith((".raw.txt",)) or not txt.stat().st_size:
            continue
        bvid = txt.stem
        out = day_dir / f"{bvid}.pack.md"
        if out.exists() and not force:
            continue
        v = vids.get(bvid, {})
        pub = dt.datetime.fromtimestamp(int(v["pubdate"])) if v.get("pubdate") else None
        day = pub.date().isoformat() if pub else day_dir.name.replace(".", "-")
        L = [f"# 素材包 {bvid}({up}, 机械生成, 零 token; 写 md 时直接用, 有疑问再查 txt / vision.json 原件)", "",
             "## ① 抬头行(照抄)", "",
             f"**[{v.get('title', '?')}](https://www.bilibili.com/video/{bvid})** · {pub.strftime('%H:%M') if pub else '?'} 发布 · "
             f"{round(v['duration'] / 60, 1) if v.get('duration') else '?'} 分钟 ·（语音转写）", "",
             "## ② 逐字稿引用块(原文机械分段, 可按话题合并相邻段, 不许改字)", ""]
        text = txt.read_text(encoding="utf-8")
        for p in paragraphs(text):
            L += [f"> {p}", ""]
        vj = txt.with_name(f"{bvid}.vision.json")
        pages, vlm = {}, {}
        if vj.exists():
            j = json.loads(vj.read_text(encoding="utf-8")); pages, vlm = j.get("pages") or {}, j.get("vlm") or {}
        L += ["## ③ 画面要点(vision.json pages 段 + VLM 逐帧精简)", ""]
        if not pages:
            L += ["> ⚠️ 画面产物缺失(仅CPU管线), 本节无视觉信息", ""]
        else:
            hl = pages.get("持仓高亮") or []
            L.append("- **持仓高亮(紫=持仓, 用户 9/28 确认)**: " + ("; ".join(f"{x['名称']} 紫{x.get('紫帧', 0)}/灰{x.get('灰帧', 0)}帧" for x in hl) or "无"))
            L.append("- **注意力榜前 10**: " + ("; ".join(f"{x['股票']} {x.get('驻留秒')}s {x.get('最新价')}({x.get('涨跌幅%')}%)" for x in (pages.get("注意力榜") or [])[:10]) or "无"))
            L.append("- **BS 买卖点**: " + (json.dumps(pages.get("BS买卖点"), ensure_ascii=False) if pages.get("BS买卖点") else "无"))
            L.append("- **持仓快照**: " + (json.dumps(pages.get("持仓快照"), ensure_ascii=False) if pages.get("持仓快照") else "无"))
            L.append("- **自选股清单**: " + ("、".join(f"{x['名称']}({x.get('帧数')}帧)" for x in (pages.get("自选股清单") or [])) or "无"))
            L.append("- **页面类型分布**: " + json.dumps(pages.get("页面类型分布"), ensure_ascii=False))
            L += ["", "VLM 逐帧(去空字段):", "```"]
            for t, fr in vlm.items():
                if isinstance(fr, dict):
                    L.append(f"{t} " + json.dumps({k: v2 for k, v2 in fr.items() if v2 not in (None, "", [], {})}, ensure_ascii=False))
            L += ["```", ""]
        # 分层
        from collections import Counter
        votes = Counter((str(fr.get("股票名")).replace(" ", ""), str(fr.get("代码"))) for fr in vlm.values()
                        if isinstance(fr, dict) and fr.get("股票名") and re.fullmatch(r"\d{6}", str(fr.get("代码") or "")))
        vcode = {}
        for (nm0, cd), _ in votes.most_common():
            vcode.setdefault(nm0, cd)
        t1 = [x["名称"] for x in (pages.get("持仓高亮") or []) if x.get("紫帧", 0) > 0]
        t2 = [x["股票"] for x in (pages.get("注意力榜") or [])[:5] if x["股票"] not in t1]
        said = []
        for nm in sorted(names, key=len, reverse=True):
            if len(nm) >= 3 and nm in text.replace(" ", "") and nm not in t1 + t2 and not any(nm in s for s in said):
                said.append(nm)
        L += ["## ④ 代码表 + 分层技术快照(截至发布日收盘, as-of; 字段照 sum.md §3.5, 全部机械算)", ""]
        for tag, group, full in (("T1 持仓(完整快照+持仓逆向由你写推断)", t1, True), ("T2 聚焦(注意力前 5, 完整快照, 不写动机)", t2, True),
                                 ("T3 口述提及(轻量一行)", said[:12], False)):
            L.append(f"### {tag}")
            if not group:
                L.append("- 无")
            for nm in group:
                k0 = nm.replace(" ", "")
                # 代码: 证券主表精确名(含 */ST 变体) → 退 VLM 多帧投票(sum.md 纪律: 代码以 OCR/多帧投票为准, 两边都无=[?])
                code = names.get(k0) or names.get("*" + k0) or names.get(k0.lstrip("*")) or vcode.get(k0)
                if not code:
                    L.append(f"- {nm}: 代码 [?](证券主表无精确匹配, 指数/板块/改名票?)"); continue
                s = snapshot(daily(code, day))
                L.append(fmt_full(nm, code, s) if full else fmt_light(nm, code, s))
            L.append("")
        L += ["(口述提及只按证券全名精确匹配, ASR 同音误字(如 晾能=量能)可能漏票——以逐字稿为准补, 补的票快照写'缺'即可)", ""]
        out.write_text("\n".join(L), encoding="utf-8")
        made.append(out)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--up", required=True, choices=list(UPS))
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    base = ROOT / "results" / "bilibili" / UPS[a.up]["mid"]
    dirs = [base / a.date.replace("-", ".")] if a.date else sorted(p for p in base.glob("20??.??.??") if p.is_dir())
    n = 0
    for d in dirs:
        if d.is_dir():
            n += len(build(a.up, d, a.force))
    print(f"JSON:{json.dumps({'up': a.up, 'packs': n})}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
