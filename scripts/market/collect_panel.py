# -*- coding: utf-8 -*-
"""collect_panel.py — 多指数实时面板(10/20 用户定: 02 市况判定的固定面板; 零 token)

为什么: 10/20 "无主线退潮"误判——链 08:05~08:25 只看了外围收盘价, 没看 A50 / 小纳指 当月连续"深跌后拉回"的过程,
        也没比上证 / 中证2000 / 创业板; 09:14 起的拉升链内也回补不了。
面板(用户清单): 日经225 · 韩国KOSPI · A50 期指连续 · 小型纳指期货连续(与纳指100期货同价) · 上证指数 · 中证2000 · 创业板指 · 恒生科技(用户待定, 先采)
源: 新浪 hq.sinajs.cn 一次批量请求带全部品种(不碰东财 / 腾讯); 每 60 秒一次(约 0.017 次/秒, 远低于封禁阈值)
产物: downloads/market/<日>/panel_minute.jsonl  每行 {t, k(面板键), n(名), p(现价), pc(昨收/昨结), pct, hi, lo, src}
摘要(给链 / ctx_index): summary(D, before=None) → 每个指数: 现涨跌 · 今日最低涨跌 · 离低点反弹 · 近 15 分钟方向 · 标记(深跌后反转 / 冲高回落)
时段: 07:30~15:05(工作日); --ensure 不在时段 / 已在跑 = 什么都不做(驱动器 0915 开跑和 check md mix 每 5 分钟都调一次)
用法: python collect_panel.py --ensure | --run [--date D] | --once(拉一次打印, 盘后实测接口用) | --show [--date D] [--before HHMM]
10/20 15:08 盘后实测: 8 个新浪品种全通; 中证2000 新浪 / 腾讯都没有 → 东财 push2 stock/get(secid=2.932000) 实测通
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MKT = ROOT / "downloads" / "market"
LOCK = ROOT / "scripts" / "temp" / "collect_panel.pid"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
START, END, STEP = "0730", "1505", 60
# (面板键, 名称, 新浪代码, 解析器) —— 解析口径同 collect_global.py(10/12 实测); 标"待核"的代码 15:00 后 --once 核实
PANEL = [
    ("NKY", "日经225", "b_NKY", "intl"),
    ("KOSPI", "韩国KOSPI", "b_KOSPI", "intl"),             # 10/20 盘后实测通
    ("A50", "A50期指连续", "hf_CHA50CFD", "fut"),
    ("NQ", "小纳指期货连续", "hf_NQ", "fut"),
    ("SH", "上证指数", "s_sh000001", "cn"),
    # ("CSI2000", "中证2000", "em:2.932000", "em"),          # 10/22 晚用户令停: 东财 push2 被封(本机 IPv4/IPv6 连上即断), 中证2000 新浪 / 腾讯都没有 → 小盘一律用下面的国证2000(贫民版)
    ("GZ2000", "国证2000", "s_sz399303", "cn"),
    ("CYB", "创业板指", "s_sz399006", "cn"),
    ("SZ", "深证成指", "s_sz399001", "cn"),                  # 10/21 晚用户令: 补深证成指 / 科创50 / 沪深300(另有 3 秒级的在 collect_book → index_snap.jsonl)
    ("KC50", "科创50", "s_sh000688", "cn"),
    ("HS300", "沪深300", "s_sh000300", "cn"),
    ("HSTECH", "恒生科技", "rt_hkHSTECH", "hk"),             # 用户待定
    # 10/20 用户批: 纳指ETF 159941 每分钟采 价格 + 实时净值 IOPV + 溢价率 + 停牌(现价为 0 = 停牌中), 攒约 20 个交易日再定建仓 / 做T 时点
    ("NDQETF", "纳指ETF159941", "tx:sz159941", "tx"),       # 腾讯 qt: f[3] 现价 f[4] 昨收 f[33] 高 f[34] 低 f[77] 溢价率% f[78] IOPV(10/20 盘后实测)
]


def f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def parse(kind, p):
    """→ (现价, 昨收, 高, 低) 或抛错"""
    if kind == "intl":   # 0名 1现价 2涨跌 3涨跌% ... 8昨收 9开 10高 11低
        return f(p[1]), f(p[8]), f(p[10]), f(p[11])
    if kind == "fut":    # 0现价 4高 5低 7昨结
        return f(p[0]), f(p[7]), f(p[4]), f(p[5])
    if kind == "hk":     # 3昨收 4高 5低 6现价
        return f(p[6]), f(p[3]), f(p[4]), f(p[5])
    if kind == "tx":     # 腾讯 qt(只用于新浪没有 IOPV 的 ETF): 现价 / 昨收 / 高 / 低; 溢价率 / IOPV 由 fetch 另记
        return f(p[3]), f(p[4]), f(p[33]), f(p[34])
    if kind == "em":     # 东财 stock/get: f43 现价 f60 昨收 f44 高 f45 低
        return f(p[0]), f(p[1]), f(p[2]), f(p[3])
    if kind == "cn":     # s_ 简版: 0名 1现价 2涨跌额 3涨跌% → 昨收 = 现价 − 涨跌额; 无高低(摘要用分钟序列自己算)
        last, chg = f(p[1]), f(p[2])
        return last, (last - chg) if last is not None and chg is not None else None, None, None
    raise ValueError(kind)


import socket
_gai = socket.getaddrinfo


def _v4_only(host, *a, **k):
    """10/20 实测: 东财 push2 走 IPv6 会被服务端直接断开(RemoteDisconnected), Python 默认先试 IPv6 → 东财域名只解析 IPv4"""
    r = _gai(host, *a, **k)
    return [x for x in r if x[0] == socket.AF_INET] or r if "eastmoney" in str(host) else r


socket.getaddrinfo = _v4_only


def fetch():
    url = "https://hq.sinajs.cn/list=" + ",".join(x[2] for x in PANEL if ":" not in x[2])
    r = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(r, timeout=8).read().decode("gbk", errors="replace")
    raw = {}
    for l in txt.strip().splitlines():
        if l.startswith("var hq_str_") and '="' in l:
            k, v = l[len("var hq_str_"):].split('="', 1)
            raw[k] = v.rstrip('";').split(",")
    for key, name, code, kind in PANEL:   # 东财单品种(新浪没有的指数)
        if code.startswith("em:"):
            u = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code[3:]}&fields=f43,f44,f45,f60&fltt=2"
            for k in range(2):   # 10/20 实测: 东财连发第二次常 RemoteDisconnected → 隔 2 秒重试一次; 仍失败本分钟记缺, 不影响其他品种
                try:
                    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}), timeout=8).read())["data"]
                    raw[code] = [d["f43"], d["f60"], d["f44"], d["f45"]]
                    break
                except Exception:   # noqa: BLE001
                    time.sleep(2)
        if code.startswith("tx:"):   # 腾讯 qt 单品种(ETF 的 IOPV / 溢价率只有它给); 每分钟 1 次, 远低于约 1.6 次 / 秒的封禁线
            try:
                tx = urllib.request.urlopen(urllib.request.Request("https://qt.gtimg.cn/q=" + code[3:], headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"}), timeout=8).read().decode("gbk", "replace")
                raw[code] = tx.split('"')[1].split("~")
            except Exception:   # noqa: BLE001
                pass
    t = dt.datetime.now().strftime("%H:%M:%S")
    out = []
    for key, name, code, kind in PANEL:
        p = raw.get(code)
        row = {"t": t, "ts": f"{dt.date.today().isoformat()} {t}", "k": key, "n": name, "src": code}
        try:
            if not p or len(p) < 3:
                raise ValueError("空报文")
            last, pc, hi, lo = parse(kind, p)
            if kind == "tx" and len(p) > 78:   # 溢价率 / IOPV; 现价 0 且无成交 = 停牌中(记下, 不当缺数据)
                row.update(prem=f(p[77]), iopv=f(p[78]))
                if not last:
                    row.update(p=None, halt=1)
                    out.append(row)
                    continue
            if not last:
                raise ValueError("无现价")
            row.update(p=last, pc=pc, pct=round((last / pc - 1) * 100, 3) if pc else None, hi=hi, lo=lo)
        except (ValueError, IndexError) as e:
            row.update(p=None, err=str(e)[:40])
        out.append(row)
    return out


MINLINE = {"A50": "CHA50CFD", "NQ": "NQ"}   # 外盘期货当日分钟线(新浪 GlobalFuturesService; A50 自前一日 17:00、NQ 自 06:00 起), 补 07:30 开采前的隔夜过程


def backfill(D):
    """10/20 实测接口通: 拉 A50 / 小纳指 当日分钟线, 补进 panel_minute.jsonl(标 bf=1, ts 带日期, 跨夜按 ts 排序); 已补过不重复"""
    dd = MKT / D
    f_ = dd / "panel_minute.jsonl"
    have = set()
    if f_.exists():
        for l in f_.open(encoding="utf-8"):
            r = json.loads(l)
            if r.get("bf"):
                have.add(r["k"])
    names = {k: n for k, n, _, _ in PANEL}
    n = 0
    for key, sym in MINLINE.items():
        if key in have:
            continue
        u = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t1hf_{sym}=/GlobalFuturesService.getGlobalFuturesMinLine?symbol={sym}"
        try:
            txt = urllib.request.urlopen(urllib.request.Request(u, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}), timeout=10).read().decode("utf-8", "replace")
            rows = json.loads(txt[txt.index("({") + 1: txt.rindex("})") + 1])["minLine_1d"]
        except Exception as e:   # noqa: BLE001
            print(f"分钟线回补 {key} 失败: {e}", flush=True)
            continue
        pc = f(rows[0][1])
        out = []
        for r in rows:
            ts, px = r[-1], f(r[5] if len(r) > 6 and r is rows[0] else r[1])
            if px and ts[:10] <= D:
                out.append({"t": ts[11:], "ts": ts, "k": key, "n": names[key], "src": "minline:" + sym, "p": px, "pc": pc,
                            "pct": round((px / pc - 1) * 100, 3) if pc else None, "bf": 1})
        with f_.open("a", encoding="utf-8") as fh:
            for r in out:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        n += len(out)
    return n


def run(D):
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(str(__import__("os").getpid()))
    dd = MKT / D
    dd.mkdir(parents=True, exist_ok=True)
    try:
        print(f"隔夜分钟线回补 {backfill(D)} 行", flush=True)
    except Exception as e:   # noqa: BLE001
        print(f"隔夜分钟线回补失败: {e}", flush=True)
    fails = 0
    while dt.datetime.now().strftime("%H%M") < END:
        try:
            rows = fetch()
            with (dd / "panel_minute.jsonl").open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            fails = 0
        except Exception as e:   # noqa: BLE001 —— 网络抖动不退出, 连败 10 次(10 分钟)才退
            fails += 1
            print(f"[{dt.datetime.now():%H:%M:%S}] 面板采集失败 {fails}: {e}", flush=True)
            if fails >= 10:
                break
        try:   # 10/24 用户批(❓12): 盘面情绪面板(全市场 13 档 + 涨停 / 炸板 / 跌停 / 封板率 / 梯队), 自己控制每 5 分钟拉一次, 失败不影响面板
            import collect_mood
            collect_mood.step(D)
        except Exception as e:   # noqa: BLE001
            print(f"[{dt.datetime.now():%H:%M:%S}] 情绪面板异常 {e!r}", flush=True)
        time.sleep(STEP)
    return 0


def rows_of(D, before=None):
    f_ = MKT / D / "panel_minute.jsonl"
    if not f_.exists():
        return {}
    cut = f"{D} {before[:2]}:{before[2:]}:59" if before else "9999"
    by = {}
    for l in f_.open(encoding="utf-8"):
        r = json.loads(l)
        r.setdefault("ts", f"{D} {r['t']}")
        if r["ts"] <= cut and r.get("p"):
            by.setdefault(r["k"], []).append(r)
    for v in by.values():
        v.sort(key=lambda r: r["ts"])   # 隔夜回补行(前一日 17:00 起)排在当日实时行之前
    return by


def rows_raw(D, before=None):
    """含停牌行(p=None, halt=1)的原始行, 只给"是不是停牌"判断用"""
    f_ = MKT / D / "panel_minute.jsonl"
    cut = f"{D} {before[:2]}:{before[2:]}:59" if before else "9999"
    by = {}
    if f_.exists():
        for l in f_.open(encoding="utf-8"):
            r = json.loads(l)
            if r.get("ts", f"{D} {r['t']}") <= cut:
                by.setdefault(r["k"], []).append(r)
    return by


def summary(D, before=None):
    """每个面板指数的过程摘要(给 02 / 挂单复核): 现涨跌 / 当日最低涨跌 / 离低点反弹 / 近 15 分钟方向 / 标记"""
    out = []
    for key, name, _, _ in PANEL:
        rs = rows_of(D, before).get(key) or []
        if not rs or not rs[-1].get("pc"):
            halted = any(r.get("halt") for r in rows_raw(D, before).get(key, []))
            out.append({"k": key, "n": name, "缺": True, "halt": halted})
            continue
        pc = rs[-1]["pc"]
        ps = [r["p"] for r in rs]
        lows = [r["lo"] for r in rs if r.get("lo")] + ps
        highs = [r["hi"] for r in rs if r.get("hi")] + ps
        lo, hi, now = min(lows), max(highs), ps[-1]
        ago = next((r["p"] for r in reversed(rs) if r["ts"] <= (dt.datetime.strptime(rs[-1]["ts"], "%Y-%m-%d %H:%M:%S") - dt.timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")), ps[0])
        d = {"k": key, "n": name, "t": rs[-1]["t"], "pct": round((now / pc - 1) * 100, 2), "lo_pct": round((lo / pc - 1) * 100, 2),
             "hi_pct": round((hi / pc - 1) * 100, 2), "from_lo": round((now / lo - 1) * 100, 2), "d15": round((now / ago - 1) * 100, 2), "prem": rs[-1].get("prem")}
        tags = []
        if d["lo_pct"] <= -0.8 and d["from_lo"] >= 0.6:
            tags.append("深跌后反转")
        if d["hi_pct"] >= 0.8 and (hi / now - 1) * 100 >= 0.6:
            tags.append("冲高回落")
        d["tag"] = tags
        out.append(d)
    return out


def text(D, before=None):
    s = summary(D, before)
    if all(x.get("缺") for x in s):
        return ""
    L = ["多指数面板(collect_panel; 过程, 不只看收盘): 指数 | 现涨跌 | 今日最低 | 离低点反弹 | 近15分钟 | 标记"]
    for x in s:
        L.append((f"- {x['n']}: 停牌中" if x.get("halt") else f"- {x['n']}: 缺") if x.get("缺") else
                 f"- {x['n']}({x['t'][:5]}): {x['pct']:+.2f}% | 低 {x['lo_pct']:+.2f}% | 反弹 {x['from_lo']:+.2f}% | {x['d15']:+.2f}% | {'、'.join(x['tag']) or '-'}"
                 + (f" | 溢价 {x['prem']:+.2f}%" if x.get("prem") is not None else ""))
    return "\n".join(L)


def alive():
    try:
        pid = int(LOCK.read_text())
    except (OSError, ValueError):
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=NOWIN)
    return str(pid) in (r.stdout or "")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--before")
    a = ap.parse_args()
    if a.backfill:
        print(f"回补 {backfill(a.date)} 行")
        return 0
    if a.once:
        for r in fetch():
            print(r)
        return 0
    if a.show:
        print(text(a.date, a.before) or "(今天没有面板数据)")
        return 0
    if a.run:
        return run(a.date)
    if a.ensure:
        hm = dt.datetime.now().strftime("%H%M")
        flags = (ROOT / "scripts" / "claude_profile" / "chain_flags.txt").read_text(encoding="utf-8")
        if not any(l.split("#")[0].strip() == "PANEL_COLLECT=1" for l in flags.splitlines()):   # 盘后实测接口通过才开(盘中不对新浪做未验证的请求)
            print("多指数面板: 开关 PANEL_COLLECT 未开")
            return 0
        if not (START <= hm < END) or dt.date.today().weekday() >= 5:
            print("多指数面板: 不在时段")
            return 0
        if alive():
            print("多指数面板: 运行中")
            return 0
        subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--run", "--date", a.date], cwd=ROOT, creationflags=NOWIN,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        print("多指数面板: 已拉起")
    return 0


if __name__ == "__main__":
    sys.exit(main())
