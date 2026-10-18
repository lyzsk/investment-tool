# -*- coding: utf-8 -*-
"""minute_supplement.py — 关注集外的票补抓当日 1 分钟线(10/16 晚: 重跑 10/16 发现 41 张挂单 26 张票不在关注集, 分钟回放全留 open)
调用方: matcher.mjs --replay-min 遇到无分钟线的挂单票时同步调用(只在回放/重跑用, 盘后才有完整数据)
数据源/口径同 collect_minute.py(通达信逐笔→分钟 bar, 末笔≈日线收盘校验, 不过=重连重取, 仍不过=记缺失不写)
输出: downloads/market/<日>/kline_minute_extra.jsonl(追加; 不碰 kline_minute.jsonl, 不入库) + kline_minute_extra_miss.json(取不到的记时刻, 1 小时内不重试; 10/18 M18: 原先永久不重试, 碰上坏服务器就一直缺)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/minute_supplement.py --date 2026-10-16 --codes 601398,510300
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_minute as cm   # noqa: E402


RETRY_S = 3600   # 取不到的票 1 小时后可重试(多半是当时连的服务器缺数据)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--codes", required=True)
    a = ap.parse_args()
    out = cm.MARKET / a.date
    ef, mf = out / "kline_minute_extra.jsonl", out / "kline_minute_extra_miss.json"
    idx = {r["symbol"] for r in cm.read_jsonl(out / "security_master.jsonl") if r.get("secType") == "INDEX"}
    have = {r["symbol"][-6:] for r in cm.read_jsonl(ef) if r["symbol"] not in idx} if ef.exists() else set()   # H2: 指数的分钟线不算"这只票已有"
    have |= {r["symbol"][-6:] for r in cm.read_jsonl(out / "kline_minute.jsonl") if r["symbol"] not in idx} if (out / "kline_minute.jsonl").exists() else set()
    raw = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    miss_old = {c: 0 for c in raw} if isinstance(raw, list) else dict(raw)   # 旧格式=代码列表(无时刻) → 视为可重试
    now = time.time()
    recent = {c for c, t in miss_old.items() if now - float(t or 0) < RETRY_S}
    codes = [c for c in dict.fromkeys(x.strip() for x in a.codes.split(",")) if c and c not in have and c not in recent]
    if not codes:
        print("SUPP 无需补抓")
        return 0
    sec = {}
    for r in cm.read_jsonl(out / "security_master.jsonl"):   # 10/17 健壮性 H2: 同一 6 位码可能既是指数又是个股(000001 上证指数/平安银行), 优先非指数
        if r["code"] not in sec or sec[r["code"]].get("secType") == "INDEX":
            sec[r["code"]] = r
    kl = {r["symbol"]: r for r in cm.read_jsonl(out / "kline_day.jsonl")}   # H2: 按带市场前缀的 symbol, 不按 6 位码(指数/个股撞码)
    ymd = int(a.date.replace("-", ""))
    api, bars, miss = cm.connect(ymd), [], []
    try:
        for code in codes:
            s = sec.get(code, {})
            sym = s.get("symbol") or cm.symbol_of_code(code)
            k = kl.get(sym) or {}
            try:
                unit = 10 if s.get("secType") == "CB" else 100
                for _try in range(2):
                    ticks = cm.all_ticks(api, sym, ymd)
                    sc = cm.price_scale(ticks, k.get("close")) if ticks else 1.0
                    if not ticks or not k.get("close") or cm.ticks_ok(ticks, k, sc):
                        break
                    try:
                        api.disconnect()
                    except Exception:   # noqa: BLE001
                        pass
                    api = cm.connect(ymd)
                else:
                    ticks = []
                b = cm.bars_from_ticks(sym, a.date, ticks, unit, k.get("preClose"), sc) if ticks and k.get("close") else []
            except Exception as e:   # noqa: BLE001
                print(f"失败 {code}: {e}")
                b = []
                try:
                    api.disconnect()
                except Exception:   # noqa: BLE001
                    pass
                api = cm.connect(ymd)
            (bars.extend(b) if b else miss.append(code))
    finally:
        try:
            api.disconnect()
        except Exception:   # noqa: BLE001
            pass
    with ef.open("a", encoding="utf-8") as f:
        for r in bars:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if miss:
        miss_old.update({c: now for c in miss})
        mf.write_text(json.dumps(miss_old, ensure_ascii=False), encoding="utf-8")
    print(f"SUPP 补抓 {len(codes) - len(miss)}/{len(codes)} 只 {len(bars)} 根; 取不到: {miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
