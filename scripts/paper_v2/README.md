# paper v2（10/22 一天的"策略执行器"：每条线一个常驻 Python 进程 + 每次触发直连 API 跑 01→06；10/22 收盘后停用，EXEC_FLEET=0）

事故复盘 `docs/research/paper_incident_20261022.md`；代码与产物快照 `_archive/paper_v1v2_20261022/`。**文件还在原位置**（理由同 v1 清单），v3 稳定后按本清单搬进本目录。

| 文件 | 作用 | v3 复用情况 |
|---|---|---|
| `scripts/dfcf/paper/exec_base.py` | 执行器：3 秒盘口撮合、事件触发、记账 | **撮合 / 记账部分 v3 复用**（拆出来进 paper_line） |
| `scripts/dfcf/paper/exec_fleet_v2.py` | 拉起 / 守护各执行器 | v3 另写 |
| `scripts/chain/chain_steps.py` | 直连 API 跑 01→06 | **persona()（规则去路径依赖、案例逐行匹配）v3 复用**；直连 API 调用不用 |
| `scripts/chain/chain_lookup.py` | 脚本替模型查料 | v3 必查项的底子 |
| `scripts/lib/claude_api.py` | 直连 API 客户端（并发闸 + 首字看门狗） | v3 不用（缓存不命中，见 TODO 第三节） |
| `scripts/dfcf/paper/facts_pack.py`、`exec_curve.py`、`se_dayreplay.py`、`se_dayview.py`、`se_dayinject.py`、`books_ext.py` | 事实包 / 曲线 / 回放 / 回放页 / 注入演示 / 导出到 report | 回放引擎和 books_ext v3 复用 |
| `results/_live/<日>/se_*` | v2 产物 | report.html 读 |
