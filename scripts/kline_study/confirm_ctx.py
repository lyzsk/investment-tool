# -*- coding: utf-8 -*-
"""confirm_ctx.py — 盘中二次确认上下文(10/25 用户: 收到 live line 推送后迟疑了就发截图, 让 Claude 基于某个 skill 上一次 chain + market-skill 二次确认 / 给挂单建议)

零 token, 只读; 给交互会话(我)一屏看全:
  ①这只票在各条 live line 最新一版策略里怎么写的(挂单 / 区间 / 叫醒条件 / kline 看法 / 情景)+ 那条线现在是留下还是暂停
  ②K线结构(日线 + 15 分钟段式箱体 / ATR / 近 60 日结构, 盘中最新)
  ③此刻 3 秒盘口(现价 / 买一卖一 / 五档买卖比 / 相对均价 / 前 3 分钟涨跌)+ 今天涨停过程(秒级)
  ④同状态统计: 次日 / 3 日情景(按 T−1 收盘状态)
用法: python confirm_ctx.py <代码> [skill] [--date D]   (截图: 先 python kline_inbox.py --force 收件拿到代码, 或直接看图读代码)
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "paper_line" / "tools")]


def strategies(code, D, skill=None):
    import pack
    keep = pack.keep_of(D)
    out = []
    for d in sorted((ROOT / "results" / "_live" / D).glob("live_*")):
        sk = d.name[5:]
        if skill and sk != skill:
            continue
        sp = sorted((d / "strategies").glob("*.json"))
        if not sp:
            continue
        j = json.loads(sp[-1].read_text(encoding="utf-8"))
        s = j.get("strategy") or {}
        hit = [x for x in s.get("codes") or [] if str(x.get("code")) == code]
        out.append({"skill": sk, "状态": "留下" if sk in keep else "暂停", "版本": sp[-1].stem, "因": str(j.get("why"))[:80], "看法": str(s.get("view"))[:160],
                    "这只票": hit or "这一版没写这只票"})
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("skill", nargs="?")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    D, code = a.date, a.code
    import intake as I
    import kline_struct as KS
    import tape as TP
    print("## ① 各条 live line 最新一版怎么写这只票")
    print(json.dumps(strategies(code, D, a.skill), ensure_ascii=False, indent=1)[:6000])
    print("\n## ② K线结构(盘中最新)")
    print(KS.line(code, D))
    print("\n## ③ 此刻 3 秒盘口")
    B = TP.book(code, D)
    if B:
        t = B[-1][1]
        R = I.daily_rows(code, D, 2)
        pc = R[-1][5] if R and R[-1][0] == D else (R[-1][4] if R else None)
        up = I.zt(pc, I.lim_pct(code)) if pc else None
        print(t, json.dumps(TP.leg_ctx(code, D, t, B[-1][2], "买", up), ensure_ascii=False))
        if up and max(r[2] for r in B) >= up - 0.005:
            print("涨停过程:", json.dumps(TP.seal_story(code, D, up), ensure_ascii=False))
    else:
        print("今天 3 秒盘口没有这只票(不在采集名单)")
    print("\n## ④ 同状态统计(按 T−1 收盘状态)")
    try:
        prev = I.daily_rows(code, D, 3)
        end = [r[0] for r in prev if r[0] < D][-1]
        print(json.dumps(I.stats(code, end), ensure_ascii=False)[:2500])
    except Exception as e:   # noqa: BLE001
        print(f"(统计失败 {e!r})")


if __name__ == "__main__":
    main()
