# -*- coding: utf-8 -*-
"""q.py — paper v3 会话里模型可调的只读查询入口(命名查询工具; 会话目录里的 ./q 包一层调它)

为什么一个入口: claude -p 只放行 `Bash(./q:*)`, 模型只能跑这里列的只读查询, 不能随意执行命令
命令(都只读; 日期一律写 D = 今天, 工具内部只用 D 之前的数据):
  similar  <转债代码> <D> [竞价开盘%]            相似日分布(竞价 / 前日状态 / K 线 / 价位 / 大盘; 样本 <15 逐级放宽)
  window   <代码> <D> [cb|stock] [N]             滑动窗口日线相似: 最近 N 天走势最像的历史 30 段, 之后 1 / 5 天
  wminute  <转债代码> <D> <HH:MM>                分钟路径相似: 开盘到此刻走法最像的历史日, 之后最高 / 最低 / 收盘
  sells    <skill> <D> <昨收浮盈%> <持有天数> [今开%]   导师相似卖点: 同状态 P(当天卖) + 卖出时段 / 卖价 / 卖后走势
  sellsT   <skill> <D> [今开%]                   导师日内 T 卖点(当天买当天卖)
  levels   <代码> <D> [现价] [HH:MM]             关键价位表(涨跌停 / 前高前低 / 均线 / 缺口 / 涨停板位 / 成交密集区 / 整数关口 / 分时均价)
  theme    <题材名> <D>                          题材生命周期(阶段 / 本波第几天 / 近 3 个出现日)
  themeof  <股票名> <D>                          这只票近 20 天挂过的题材 + 各自生命周期
  themetop <D>                                   近 5 日最活跃题材
  same     <skill> <代码>                        导师在这只票上的全部历史买卖(cases_auto)
  md       <D> [小节名]                          某天 md 日记全文或某一节(如 涨停分析 / 龙虎榜)
  sql      "<select ...>"                        只读 SQL(investment_market 库; 只许 SELECT, 自动 LIMIT 200)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_v3" / "tools"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili")]


def out(x):
    print(json.dumps(x, ensure_ascii=False, indent=1) if not isinstance(x, str) else x)


def f(v):
    return None if v is None else float(v)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        return print(__doc__)
    cmd, x = a[0], a[1:]
    try:
        if cmd == "similar":
            import similar_days as S
            out(S.query(x[0], x[1], f(x[2]) if len(x) > 2 else None))
        elif cmd == "window":
            import window_similar as W
            out(W.daily(x[0], x[1], x[2] if len(x) > 2 else ("cb" if x[0].startswith(("11", "12")) else "stock"), int(x[3]) if len(x) > 3 else 10))
        elif cmd == "wminute":
            import window_similar as W
            out(W.minute(x[0], x[1], x[2]))
        elif cmd == "sells":
            import mentor_sells as M
            out(M.query(x[0], x[1], float(x[2]), int(x[3]), f(x[4]) if len(x) > 4 else None))
        elif cmd == "sellsT":
            import mentor_sells as M
            out(M.query_intraday(x[0], x[1], f(x[2]) if len(x) > 2 else None))
        elif cmd == "levels":
            import key_levels as K
            out(K.levels(x[0], x[1], f(x[2]) if len(x) > 2 and x[2] not in ("-", "") else None, x[3] if len(x) > 3 else None))
        elif cmd == "theme":
            import theme_life as T
            out(T.life(T.norm(x[0]), x[1]))
        elif cmd == "themeof":
            import theme_life as T
            out(T.by_stock(x[0], x[1]))
        elif cmd == "themetop":
            import theme_life as T
            out(T.top(x[0]))
        elif cmd == "same":
            p = ROOT / "skills" / f"{x[0]}-skill" / "persona" / "cases_auto.jsonl"
            rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            rows = [{k: r.get(k) for k in ("date", "time", "side", "vwap", "play", "sell_kind", "result")} for r in rows if str(r.get("code")) == x[1] and r.get("side") in ("买", "卖")]
            out({"skill": x[0], "code": x[1], "n": len(rows), "rows": rows[-60:]})
        elif cmd == "md":
            y, m = x[0][:4], int(x[0][5:7])
            p = ROOT / "md" / f"{y}S{(m - 1) // 3 + 1}" / f"{x[0]}.md"
            t = p.read_text(encoding="utf-8", errors="replace")
            if len(x) > 1:
                mm = re.search(rf"^## {re.escape(x[1])}.*?$(.*?)(?=^## |\Z)", t, re.S | re.M)
                t = mm.group(0) if mm else f"(没有小节 {x[1]}; 有: " + " / ".join(re.findall(r"^## (.+)$", t, re.M)) + ")"
            out(t)
        elif cmd == "sql":
            sql = " ".join(x).strip().rstrip(";")
            if not re.match(r"(?is)^\s*(select|with)\b", sql) or re.search(r"(?i)\b(insert|update|delete|drop|alter|create|replace|truncate|grant|into\s+outfile|load_file|sleep|benchmark)\b", sql):
                return out({"err": "只许 SELECT"})
            if not re.search(r"(?i)\blimit\s+\d+", sql):
                sql += " limit 200"
            import manual_backfill as mb
            c = mb.db().cursor()
            c.execute("use investment_market")
            c.execute("set session transaction read only")
            c.execute(sql)
            cols = [d[0] for d in c.description]
            out({"cols": cols, "rows": [[str(v) for v in r] for r in c.fetchall()]})
        else:
            print(f"未知命令 {cmd}\n" + __doc__)
    except Exception as e:   # noqa: BLE001
        out({"err": repr(e)[:300], "用法": [l for l in __doc__.splitlines() if l.strip().startswith(cmd)]})


if __name__ == "__main__":
    main()
