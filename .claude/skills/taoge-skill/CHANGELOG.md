# taoge-skill CHANGELOG（B6 小件, 2026-10-05 建）

> 记 persona/workflow/契约层的实质变更(格式演进/立法/事故修复); 日常核销样本不记(在 rules.md 验证记录里)。

- 2026-10-05 【C7③】盲审 prompt 加⑥价格锚核对维度（读 cand_snap：数值出当日理论区间=FAIL；"回踩"挂高于现价类语义矛盾=issue）。
- 2026-10-05 【C9】盲审回炉 06 校验败不再直接 abort：再给一次带原因回炉；trigger_price 支持 `Z*系数` 公式价（resolve_px 前收代换）。
- 2026-10-05 【会话讨论落地】06 prompt 加"推翻上游是职责而非失误"授权（任务独立性不靠上下文独立）。
- 2026-10-04 【C7①②/C10】04 加 code→驱动器拉 cand_snap 价格锚；v06 挂价出理论区间=回炉；plans 加 cond 列（cancel_below/stop_below）+matcher 四哨兵（顶一字拒买/失效撤单/止损市价出/价格锚越界拒单）；matcher 加价格笼子 ±2% 废单。
- 2026-10-03 【B3】rules_index 分级加载落地（239KB 禁入 context，索引常驻+grep 按需）；facts 一字封死 🔒 标注。
- 2026-10-02 【E】chain 驱动器重建（run_taoge_chain.py，契约源=chain.md）；9/28 回放冒烟全链通过（$5.69/46万token）。

- 2026-10-07: 目录结构化——SKILL.md 瘦身为薄路由(365→130 行), sum/distill 工作流全文迁 workflows/{sum,distill}.md(渐进披露立法); 上下游引用不变(claude -p /taoge-skill(sum) 照常)。
