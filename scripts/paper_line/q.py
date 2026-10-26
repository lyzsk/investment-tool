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
  cases    <skill> <代码> [D]                     同上, 但每次带 正 / 负 / 平 标签(负样本只能当教训, 不能当依据)
  rule     <skill> <规则编号>                     某条导师规则全文(开机只常驻简表; 验证状态 / 样本 / 反例在全文里)
  peers    <股票代码> <D>                        同炒作逻辑邻居: 龙虎榜席位 + 席位风格(历史净买票次日分布) / 同题材 / 梯队位置
  cbpath   <转债代码> <D> [N]                    同一只转债近 N 日(默认 10)开盘缺口 / 30 分钟最高 / 尾盘低点后拉升 / 收盘
  pattern  <代码> <D> [N]                        近期规律: 近 N 天(默认 10)固定形态出现率 vs 长期, 只列回测有预测力的 + 回测第二天出现率(不是概率保证)
  events   <代码> <D>                          事件本体: 这只票这天的全部事件(状态 / 开板 / 席位 / 题材 / 电报 / 导师交易)+ 连着什么
  like     <事件id> [标签,标签]                  事件本体: 同标签的历史事件 → 结果全分布 + 案例(每个案例带当天还连着什么)
  md       <D> [小节名]                          某天 md 日记全文或某一节(如 涨停分析 / 龙虎榜)
  must     <代码> [线号]                         今天盘前首跑放不下、只给了简版的票: 完整必查(和全量一样, E 编号相同)
  sql      "<select ...>"                        只读 SQL(investment_market 库; 只许 SELECT, 自动 LIMIT 200)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line" / "tools"), str(ROOT / "scripts" / "market"), str(ROOT / "scripts" / "backfill_bilibili"), str(ROOT / "scripts" / "lib")]


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
            sys.path.insert(0, str(ROOT / "scripts" / "paper_line"))
            import pack   # 10/24: 转债相似日按文件路径导入(避开 scripts/dfcf/paper/similar_days.py 同名)
            S = pack._cb_similar()
            out(S.query(x[0], x[1], f(x[2]) if len(x) > 2 else None))
        elif cmd == "events":   # 10/24 事件本体 v0: 这只票这天发生了什么、连着什么
            sys.path.insert(0, str(ROOT / "scripts" / "ontology"))
            import query as OQ
            out(OQ.events(x[0], x[1]))
        elif cmd == "like":   # 10/24 事件本体 v0: 同标签历史事件, 统计 + 案例
            sys.path.insert(0, str(ROOT / "scripts" / "ontology"))
            import query as OQ
            out(OQ.like(x[0], x[1].split(",") if len(x) > 1 else None))
        elif cmd == "peers":   # 10/24 用户令: 同炒作逻辑邻居
            import peers as P
            out(P.query(x[0], x[1]))
        elif cmd == "cbpath":   # 10/24 用户令: 同一只转债近 N 日开盘 / 尾盘路径
            import cb_path as C
            out(C.query(x[0], x[1], int(x[2]) if len(x) > 2 else 10))
        elif cmd == "pattern":   # 10/24 用户令: 近期规律(固定形态近 N 天出现率 vs 长期 + 回测第二天出现率)
            import pattern_scan as PS
            out(PS.query(x[0], x[1], int(x[2]) if len(x) > 2 else 10))
        elif cmd == "rule":   # 10/24 📋1 瘦身配套: 开机只常驻规则简表, 要某条规则全文(验证状态 / 样本 / 反例)用这个
            t = (ROOT / "skills" / f"{x[0]}-skill" / "persona" / "rules.md").read_text(encoding="utf-8")
            m = re.search(rf"^### {re.escape(x[1])}\b.*?(?=^### |^## |\Z)", t, re.S | re.M)
            out(m.group(0) if m else f"(没有规则 {x[1]}; 有: " + " ".join(re.findall(r"^### (\S+)", t, re.M)[:60]) + ")")
        elif cmd == "cases":   # 10/24 用户令: 导师在这只票上的案例 + 正 / 负 / 平 标签
            import case_label as CL
            out(CL.summary(x[0], x[1], x[2] if len(x) > 2 else None))
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
        elif cmd == "must":   # 10/25 分级进查询: 盘前首跑放不下、只给了简版的票 → 完整必查(E 编号和常驻里一致)
            import datetime as _dt
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            import line_dirs as LDS
            code, lid = x[0], (x[1] if len(x) > 1 else "")
            import os as _os   # 10/25 C: 回放时 replay.py 设 PAPER_Q_DAY = 回放日目录(原来只认 results/_live/<今天>, 回放里查不到)
            day = Path(_os.environ["PAPER_Q_DAY"]) if _os.environ.get("PAPER_Q_DAY") else ROOT / "results" / "_live" / _dt.date.today().isoformat()
            fs = [day / LDS.ldir(lid) / "must_full.md"] if lid else LDS.line_dirs(day, "must_full.md")
            hit = None
            for f in fs:
                if f.exists():
                    mm = re.search(r"^### " + re.escape(code) + r"\b[\s\S]*?(?=^### |\Z)", f.read_text(encoding="utf-8"), re.M)
                    if mm:
                        hit = mm.group(0)
                        break
            out(hit or f"(今天没有 {code} 的完整必查存档{'(线 ' + lid + ')' if lid else ''}: 它可能本来就在常驻必查里全量给了, 或不在必查范围)")
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
