# 人读版回测 harness — 建造 STATE(2026-09-28 04:40-05:10 建)

## 资产清单
- `scripts/plan-a/backtest/harness_human.py` — 编排器(窗口选择/事实采集/ABC 三组/七环节/结算/曲线/报告骨架)。`python scripts/plan-a/backtest/harness_human.py` 直接跑; `--fresh` 无视账本重跑。
- `scripts/plan-a/backtest/replay/factpack.mjs` — 事实采集桥: `bars`(复用 kline.mjs 分层缓存+多源+抖动) + `resolve`(名称→代码: 腾讯 smartbox 主/东财 suggest 备, 转债 smartbox 不索引必走东财; name_cache.json 缓存)。
- 产物目录: `scripts/plan-a/backtest/runs/human-<窗口起>_<窗口止>/`(facts/ a_extract/ b_llm/ c_chain/ persona_snapshot/ ledger.json trades.csv equity.csv equity.png report.md harness.log STATE.md)。

## 关键口径(用户拍板+数据现实)
- 窗口=md_checklist.md 里 ✅+🧠 最密连续交易日簇, 运行时算(当前=2025-08-13..15 共 3 天; 沉淀继续后重跑会自动扩簇, ≤7 天)。
- 日线粒度。2025 窗口分钟线已超出腾讯历史上限(m60=8 个月, 实测只能到 2026-02) → BS 点只有日期无分时, 报告如实标注。
- 成交=次日开盘价(照抄者最早能跟的时点); 限价单日内触及才成交; 费用买万2.5/卖万7.5; 单票=净值20%整百股; 股票T+1/转债(11/12)T+0; 初始 100 万。
- A 组=机械提取(已冒烟验证: 能识别无操作日+拒绝把踏空感叹当操作); B=纯 LLM 基线; C=taoge-skill 七环节(分析→辩论×2→方案→风控→终裁→复盘), persona 物理快照进 runs 目录。

## 血泪坑(已立法进代码注释)
1. **claude -p 经 cmd /c 传含双引号/换行的 prompt 会被 cmd 解析烂** → agent 收空 prompt 回"已就绪请说任务", exit=0 假成功。修法=直调 `claude.exe`(npm node_modules bin 下)+list argv。distill 链 prompt 无引号所以一直没炸, 是 latent 不是不存在。
2. smartbox 响应名字字段有时是字面 `\uXXXX` 转义, 先反转义再匹配; 转债它直接返回 `v_hint="N"`。
3. factpack 输出 bar t 已切 8 位 YYYYMMDD(缓存原件是 12 位带时分)。
4. 账本路径: distill_state.json 在 `scripts/`(不是 scripts/backfill_taoge/)。
5. k3 agent 写文件有时不写——claude() 校验=哨兵+文件存在且>50B 双闸, 失败重试一次后放弃记 log。

## 断点续跑
ledger.json 记 `日期:组:环节` 粒度; 中断重跑自动跳过已完成。token 预算闸 MAX_CALLS=70(约 80min), 超出收尾出部分结果。

## 不自信点(如实)
- C 组 7 环节×天数 的 k3 指令遵循率只验证了 A 组一环; 06:08 首跑若某环节连续失败, harness 会跳过该日 C 组后续环节(prev_ok 闸), 报告里该日 C 显示"(缺文件/未产出)"——如实呈现, 不补假。
- 窗口只有 3 天时统计意义弱, 报告结论按"示意性"措辞。
- B 组基线没有持仓记忆外的限制, 可能全场空仓——也是有效对照。
