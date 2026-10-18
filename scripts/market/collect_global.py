"""collect_global.py — 行情库第 4 段: 外围市场收盘快照(2026-10-12 建)
链路: Quartz MarketGlobalHandler(每天 08:30) → 本脚本 → downloads/market/<北京日期>/global_security.jsonl + global_kline.jsonl + DONE_global
      → Java importGlobal(security_master 有则更新/无则插入; kline_day 按 symbol+trade_date 先删后插, 幂等)
源: 新浪 hq.sinajs.cn 一次批量(10/12 实测各品种报文格式, 见 PARSERS); 08:30 时美股/欧股/期货=北京时间凌晨收盘值, 港股/日股=上一交易日收盘
trade_date: 各市场当地交易日(美股取报文里的美东日期; 24h 品种(期货/外汇)= 北京时间戳减 6 小时的日期, 即美盘所属日)
symbol 口径: <市场>.<代码>, 如 us.NDX / hk.HSI / gl.A50; volume 按源原值(DDL: 外围按源原值), amount NULL
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_global.py [--force]
出口: 0=完成 1=失败(全部解析不出)"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
MARKET = ROOT / "downloads" / "market"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn"}
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# (新浪代码, symbol, exchange, secType, 名称, 解析器)
ITEMS = [
    ("gb_$ndx", "us.NDX", "US", "INDEX", "纳斯达克100", "us"),
    ("gb_$ixic", "us.IXIC", "US", "INDEX", "纳斯达克综合", "us"),
    ("gb_$inx", "us.SPX", "US", "INDEX", "标普500", "us"),
    ("gb_$dji", "us.DJI", "US", "INDEX", "道琼斯", "us"),
    ("gb_$hxc", "us.HXC", "US", "INDEX", "纳斯达克中国金龙", "us"),
    ("gb_kweb", "us.KWEB", "US", "ETF", "中概互联网ETF", "us"),
    ("rt_hkHSI", "hk.HSI", "HK", "INDEX", "恒生指数", "hk"),
    ("rt_hkHSTECH", "hk.HSTECH", "HK", "INDEX", "恒生科技指数", "hk"),
    ("b_NKY", "jp.NKY", "JP", "INDEX", "日经225", "intl"),
    ("znb_UKX", "gl.UKX", "GLOBAL", "INDEX", "英国富时100", "intl"),
    ("hf_CHA50CFD", "gl.A50", "GLOBAL", "OTHER", "富时中国A50期货", "fut"),
    ("hf_ES", "gl.ES", "GLOBAL", "OTHER", "标普500期货", "fut"),
    ("hf_NQ", "gl.NQ", "GLOBAL", "OTHER", "纳斯达克100期货", "fut"),
    ("hf_GC", "gl.GC", "GLOBAL", "OTHER", "纽约黄金", "fut"),
    ("hf_CL", "gl.CL", "GLOBAL", "OTHER", "纽约原油", "fut"),
    ("fx_susdcnh", "gl.USDCNH", "GLOBAL", "OTHER", "离岸人民币", "fx"),
]


def log(*a):
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def session_day(bj_date, bj_time):
    """24h 品种: 北京时间戳减 6 小时的日期(凌晨 05:00 收的美盘 → 前一日)"""
    t = dt.datetime.strptime(f"{bj_date} {bj_time[:8]}", "%Y-%m-%d %H:%M:%S")
    return (t - dt.timedelta(hours=6)).date().isoformat()


def parse(kind, p):
    """返回 (trade_date, open, high, low, close, pre_close, volume) 或抛错"""
    if kind == "us":   # 0名 1现价 2涨跌% 3北京时间 4涨跌额 5开 6高 7低 ... 10量 ... 25 "Oct 09 05:16PM EDT" 26昨收 29年
        mon, day = p[25].split()[:2]
        year = int(p[29]) if len(p) > 29 and p[29].isdigit() else int(p[3][:4])
        return (dt.date(year, MONTHS[mon], int(day)).isoformat(), f(p[5]), f(p[6]), f(p[7]), f(p[1]), f(p[26]),
                int(float(p[10])) if f(p[10]) else None)
    if kind == "hk":   # 0代码 1名 2开 3昨收 4高 5低 6现价 ... 12量 17日期 yyyy/MM/dd
        return (p[17].replace("/", "-"), f(p[2]), f(p[4]), f(p[5]), f(p[6]), f(p[3]), int(float(p[12])) if f(p[12]) else None)
    if kind == "intl":   # 0名 1现价 2涨跌 3涨跌% ... 6日期 7时间 8昨收 9开 10高 11低
        return (p[6], f(p[9]), f(p[10]), f(p[11]), f(p[1]), f(p[8]), None)
    if kind == "fut":   # 0现价 2买 3卖 4高 5低 6时间 7昨结/昨收 8开 9持仓 12日期 13名
        return (session_day(p[12], p[6]), f(p[8]), f(p[4]), f(p[5]), f(p[0]), f(p[7]), None)
    if kind == "fx":   # 0时间 1买 2卖 3最新 ... 5昨收 6高 7低 8现价 9名 ... 17日期
        return (session_day(p[17], p[0]), None, f(p[6]), f(p[7]), f(p[8]) or f(p[3]), f(p[5]), None)
    raise ValueError(kind)


def write_jsonl(path, recs):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = MARKET / dt.date.today().isoformat()
    if (out / "DONE_global").exists() and not a.force:
        log("今日已有 DONE_global, 跳过")
        return 0
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(x[0] for x in ITEMS), headers=UA, timeout=15)
    r.raise_for_status()
    raw = {}
    for line in r.content.decode("gbk", errors="replace").splitlines():
        if "=\"" in line:
            raw[line.split("=")[0].replace("var hq_str_", "")] = line.split("=\"", 1)[1].rstrip("\";").split(",")
    secs, bars, errors = [], [], []
    for code, sym, ex, typ, name, kind in ITEMS:
        p = raw.get(code)
        if not p or len(p) < 5:
            errors.append(f"{sym}: 报文空")
            continue
        try:
            d, o, h, low, c, pc, v = parse(kind, p)
            if not c:
                raise ValueError("现价空")
            dt.date.fromisoformat(d)
        except Exception as e:   # noqa: BLE001  单品种格式变了不挡其他
            errors.append(f"{sym}: {e}")
            continue
        secs.append({"symbol": sym, "code": sym.split(".", 1)[1], "exchange": ex, "secType": typ, "boardType": None,
                     "name": name, "isSt": 0, "source": "sina"})
        bars.append({"symbol": sym, "tradeDate": d, "open": o or c, "high": h or c, "low": low or c, "close": c, "preClose": pc,
                     "volume": v, "amount": None, "turnoverRate": None, "limitUp": None, "limitDown": None, "source": "sina"})
    if not bars:
        log(f"全部解析失败: {errors}")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "global_security.jsonl", secs)
    write_jsonl(out / "global_kline.jsonl", bars)
    mf_path = out / "manifest.json"
    mf = json.loads(mf_path.read_text("utf-8")) if mf_path.exists() else {}
    mf["global"] = {"at": dt.datetime.now().isoformat(), "rows": len(bars), "errors": errors}
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1), "utf-8")
    (out / "DONE_global").write_text(dt.datetime.now().isoformat())
    log(f"外围 {len(bars)}/{len(ITEMS)} 个品种, 失败 {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
