# -*- coding: utf-8 -*-
"""collect_mood.py — 盘面情绪面板(10/24 用户批 ❓12; 零 token)

内容(全市场): 13 档涨跌分布(涨停 / >8% / 6~8 / 4~6 / 2~4 / 0~2 / 平 / 0~−2 / −2~−4 / −4~−6 / −6~−8 / <−8% / 跌停, 同 md 午评 / 收评表头)
              + 上涨 / 下跌 / 平家数 + 平均涨幅 + 涨停 / 炸板 / 跌停家数 + 封板率(涨停 ÷ (涨停 + 炸板)) + 连板梯队(首板 / 2 板 / 3 板 / 4 板+ / 最高板是谁)
源: 分布 = 财联社 x-quote quote/index/home 的 up_down_dis(10/24 实测: 一个请求全市场, 上涨 4197 = 五个上涨档之和, 和 10/23 收盘对得上)
    池子 = 财联社 up_down_analysis?type=up_pool|up_open_pool|down_pool → 失败切东财 push2ex 涨停 / 炸板 / 跌停池(同 fetch_cls_pool.mjs 的备源)
口径提醒: 10/23 收盘核对 —— 接口上涨 4197 / 涨停 82, md 收评图(财联社图片 OCR)上涨 4526 / 涨停 84, 各档都小约 7%; 猜是接口不含北交所(未核实)。
          看盘中变化够用; 和收评图的绝对数不要直接比
节奏: 盘中每 5 分钟一次(4 个请求, 请求间 1~2 秒抖动, 每个请求最多 3 次退避重试); 挂在 collect_panel.py 的循环里调 step(), 不另起计划任务
产物: downloads/market/<日>/mood.jsonl, 每行一个快照
给链: block(D, until) → 01 的「盘面情绪」节(此刻 vs 30 分钟前 vs 昨天同一时刻; 只用 ≤ until 的快照, 回放不偷看)
用法: python collect_mood.py --once(拉一次打印, 不写盘) | --snap(拉一次写盘) | --show <D> [HH:MM]
"""
import argparse
import datetime as dt
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
H_CLS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36", "Referer": "https://www.cls.cn/"}
H_EM = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://quote.eastmoney.com/"}
BINS = ["涨停", ">8%", "6~8", "4~6", "2~4", "0~2", "平", "0~−2", "−2~−4", "−4~−6", "−6~−8", "<−8%", "跌停"]
STEP_MIN = 5


def _get(url, headers, tries=3):
    last = None
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8).read().decode("utf-8", "replace"))
        except Exception as e:   # noqa: BLE001
            last = e
            time.sleep((i + 1) * (0.75 + random.random() * 0.5))
    raise RuntimeError(f"{url[:60]}… {last!r}"[:160])


def dist():
    j = _get("https://x-quote.cls.cn/quote/index/home?app=CailianpressWeb&os=web&sv=8.7.9", H_CLS)
    u = (j.get("data") or {}).get("up_down_dis") or {}
    if not u.get("status") or "up_2" not in u:
        raise RuntimeError(f"up_down_dis 结构异常: {str(u)[:80]}")
    zt, dt_ = int(u["up_num"]), int(u["down_num"])
    d13 = dict(zip(BINS, [zt, int(u["up_10"]) - zt, u["up_8"], u["up_6"], u["up_4"], u["up_2"], u["flat_num"], u["down_2"], u["down_4"], u["down_6"], u["down_8"],
                          int(u["down_10"]) - dt_, dt_]))
    return {"dist13": {k: int(v) for k, v in d13.items()}, "rise": int(u["rise_num"]), "fall": int(u["fall_num"]), "flat": int(u["flat_num"]),
            "avg": round(float(u.get("average_rise") or 0) * 100, 2), "suspend": int(u.get("suspend_num") or 0)}


def _cls_pool(t):
    j = _get(f"https://x-quote.cls.cn/quote/index/up_down_analysis?app=CailianpressWeb&os=web&rever=1&sv=8.7.9&type={t}&way=last_px", H_CLS)
    if j.get("code") != 200 or not isinstance(j.get("data"), list):
        raise RuntimeError(f"{t} 结构异常")
    return [{"c": str(x.get("secu_code", ""))[-6:], "n": x.get("secu_name"), "lb": int(x.get("limit_up_days") or 1), "st": int(x.get("is_st") or 0),
             "t": str(x.get("time") or "")[11:19], "why": str(x.get("up_reason") or "").split("|")[0][:12]} for x in j["data"]]


def _em_pool(t, D):
    k = {"up_pool": "ZT", "up_open_pool": "ZB", "down_pool": "DT"}[t]
    j = _get(f"https://push2ex.eastmoney.com/getTopic{k}Pool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort={'fund:asc' if k == 'DT' else 'fbt:asc'}"
             f"&date={D.replace('-', '')}", H_EM)
    return [{"c": str(x.get("c")), "n": str(x.get("n") or "").strip(), "lb": int(x.get("lbc") or 1), "st": int("ST" in str(x.get("n") or "")), "t": "", "why": x.get("hybk") or ""}
            for x in (j.get("data") or {}).get("pool") or []]


def pools(D):
    out, src = {}, []
    for t in ("up_pool", "up_open_pool", "down_pool"):
        try:
            out[t] = _cls_pool(t)
            src.append("cls")
        except Exception:   # noqa: BLE001  财联社失败 → 东财备源
            try:
                out[t] = _em_pool(t, D)
                src.append("em")
            except Exception as e:   # noqa: BLE001
                out[t] = None
                src.append(f"失败 {e!r}"[:40])
        time.sleep(1 + random.random())
    return out, src


def ladder(up):
    up = [x for x in up or [] if not x["st"]]
    c = {"首板": sum(1 for x in up if x["lb"] == 1), "2板": sum(1 for x in up if x["lb"] == 2), "3板": sum(1 for x in up if x["lb"] == 3), "4板+": sum(1 for x in up if x["lb"] >= 4)}
    top = sorted(up, key=lambda x: -x["lb"])[:3]
    return c, [f"{x['n']}{x['lb']}板" for x in top if x["lb"] >= 2]


def snapshot(D=None):
    D = D or dt.date.today().isoformat()
    r = {"t": dt.datetime.now().strftime("%H:%M:%S")}
    try:
        r.update(dist())
    except Exception as e:   # noqa: BLE001
        r["dist_err"] = repr(e)[:120]
    time.sleep(1 + random.random())
    P, src = pools(D)
    r["src"] = src
    if P.get("up_pool") is not None:
        up = P["up_pool"]
        r["zt"] = len(up)
        r["zt_st"] = sum(x["st"] for x in up)
        r["ladder"], r["top"] = ladder(up)
        r["up"] = [[x["c"], x["n"], x["lb"], x["why"], x["t"][:5]] for x in up]   # 10/24 模块 4: 涨停池明细(代码 / 名 / 连板 / 题材 / 首封时刻) → 盘中题材强度 + 候选池"今日强题材"
    if P.get("up_open_pool") is not None:
        r["zb_list"] = [[x["c"], x["n"], x["why"]] for x in P["up_open_pool"]]
    if P.get("up_open_pool") is not None:
        r["zb"] = len(P["up_open_pool"])
    if P.get("down_pool") is not None:
        r["dt"] = len(P["down_pool"])
    if r.get("zt") is not None and r.get("zb") is not None and r["zt"] + r["zb"]:
        r["seal"] = round(r["zt"] / (r["zt"] + r["zb"]) * 100)
    return r


def write(D, r):
    d = MKT / D
    d.mkdir(parents=True, exist_ok=True)
    with (d / "mood.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


_LAST = {}


def step(D):
    """collect_panel 循环里每分钟调一次: 09:25~15:05 之间每 STEP_MIN 分钟拉一次写盘; 失败只打印, 不抛"""
    now = dt.datetime.now()
    hm = now.strftime("%H:%M")
    if not ("09:25" <= hm <= "15:05") or ("11:31" <= hm <= "12:59"):
        return None
    if _LAST.get(D) and (now - _LAST[D]).total_seconds() < STEP_MIN * 60 - 5:
        return None
    _LAST[D] = now
    try:
        r = snapshot(D)
        write(D, r)
        return r
    except Exception as e:   # noqa: BLE001
        print(f"[{hm}] 情绪面板失败 {e!r}", flush=True)
        return None


def rows(D, until=None):
    f = MKT / D / "mood.jsonl"
    if not f.exists():
        return []
    out = []
    for l in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if until is None or r.get("t", "") <= until:
            out.append(r)
    return out


def _line(r):
    s = []
    if r.get("dist13"):
        d = r["dist13"]
        s.append(f"上涨 {r['rise']} / 下跌 {r['fall']} / 平 {r['flat']}, 平均 {r['avg']:+.2f}%")
        s.append("13 档: " + " ".join(f"{k} {v}" for k, v in d.items()))
    if r.get("zt") is not None:
        s.append(f"涨停 {r['zt']}(含 ST {r.get('zt_st', 0)}) / 炸板 {r.get('zb', '-')} / 跌停 {r.get('dt', '-')}" + (f", 封板率 {r['seal']}%" if r.get("seal") is not None else ""))
    if r.get("ladder"):
        s.append("梯队: " + " / ".join(f"{k} {v}" for k, v in r["ladder"].items()) + (f"; 最高 {' '.join(r['top'])}" if r.get("top") else ""))
    return "; ".join(s) or "(这次没拉到)"


def block(D, until):
    """01 的「盘面情绪」节: 此刻 / 30 分钟前 / 昨天同一时刻"""
    R = rows(D, until)
    if not R:
        return "## 盘面情绪(全市场, 每 5 分钟)\n(暂无: 09:25 后才开始采)"
    cur = R[-1]
    t30 = (dt.datetime.strptime(cur["t"][:8], "%H:%M:%S") - dt.timedelta(minutes=30)).strftime("%H:%M:%S")
    ago = [r for r in R if r["t"] <= t30]
    L = [f"## 盘面情绪(全市场, 每 5 分钟; 财联社分布 + 涨停 / 炸板 / 跌停池)", f"- 此刻 {cur['t'][:5]}: {_line(cur)}"]
    if ago:
        a = ago[-1]
        dd = []
        for k, nm in (("zt", "涨停"), ("zb", "炸板"), ("dt", "跌停"), ("seal", "封板率"), ("rise", "上涨家数"), ("avg", "平均涨幅")):
            if cur.get(k) is not None and a.get(k) is not None:
                dd.append(f"{nm} {a[k]}→{cur[k]}")
        L.append(f"- 30 分钟前 {a['t'][:5]} → 此刻: " + ", ".join(dd))
    prev = sorted(p.name for p in MKT.glob("20*") if p.name < D and (p / "mood.jsonl").exists())
    if prev:
        Y = rows(prev[-1], cur["t"])
        if Y:
            y = Y[-1]
            L.append(f"- 昨天({prev[-1][5:]})同一时刻 {y['t'][:5]}: 涨停 {y.get('zt', '-')} / 炸板 {y.get('zb', '-')} / 跌停 {y.get('dt', '-')} / 上涨 {y.get('rise', '-')} / 平均 {y.get('avg', '-')}%")
    return "\n".join(L)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--snap", action="store_true")
    ap.add_argument("--show", nargs="+")
    a = ap.parse_args()
    if a.once or a.snap:
        r = snapshot()
        print(json.dumps(r, ensure_ascii=False))
        print(_line(r))
        if a.snap:
            write(dt.date.today().isoformat(), r)
    elif a.show:
        print(block(a.show[0], (a.show[1] + ":59")[:8] if len(a.show) > 1 else "15:10:00"))
    else:
        print(__doc__)
