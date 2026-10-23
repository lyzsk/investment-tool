# paper v1（旧链：每位导师一条 claude -p 决策链，按时段 0915 / 0927 / 1000 / 1030 跑；10/22 收盘后停用）

**文件还在原位置没搬**（10/22 晚核过：matcher.mjs 被 38 个文件引用、facts.mjs 35 个、run_chain.py 24 个（含 Java PaperChainHandler），盘后夜里整体搬家风险太大）。本文件是清单，v3 稳定后（预计周末）再按清单物理搬进本目录。

| 文件 | 作用 | 还有谁在用 |
|---|---|---|
| `scripts/chain/run_chain.py` | v1 决策链驱动器（01→07） | Java PaperChainHandler（定时 153~156 已停） |
| `scripts/dfcf/paper/facts.mjs` | 事实包构建 | v2 / v3 也读事实包（共用，搬时要改路径） |
| `scripts/dfcf/paper/matcher.mjs` | 旧账本撮合 / EOD | 做 T 三本账（中行 / 纳指）还在用 |
| `scripts/dfcf/paper/books/A-*.json` | 旧账本 | report.html、拟人度、T 线 |
| `scripts/dfcf/paper/mix_plans.py`、`event_chain.py`、`reflect_trigger.py`、`slot_*.py`、`decision_memory.py`、`pack07.py` | 混合账本 / 事件子链 / 时段 / 决策记忆 / 07 素材 | check md 夜间流程部分调用 |
| `skills/*/workflows/chain.md` | 旧链提示词 | 无 |
