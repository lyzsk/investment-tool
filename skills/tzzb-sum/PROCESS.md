# tzzb-sum 过程记录(2026-10-02 用户立法: 过程可追溯, skill 更新/格式更新/意外都可回查)

> 追加约定: 每次跑批、格式变更、立法、事故, 在最上方加一行 `YYYY-MM-DD 事件: 经过 → 结果/产物`。
> 本文件只记"过程", 规则结论去 `skills/cb-skill/persona/rules.md`, 管线知识去 Claude 记忆。

- 2026-10-02 **tzzb-distill 建立**(串行链第三棒, 对齐 taoge 侧): 机械层零token必跑
  (profile+review+gen_cb_cases), 漂移/新标的/证伪才 LLM 审议; 与 taoge-distill 差异=行为统计 vs 语言。
- 2026-10-02 **cases.md 建立**(用户立法: 各种案例全进 cases.md, 全量按日期不截断):
  curated 反例 4 条自 rules.md 迁入 + 双尾样本库(逃顶102/卖飞78 全量, `scripts/gen_cb_cases.py` 机械重生成);
  rules.md 反例录改指针。scripts 大重组同 taoge-sum PROCESS 当日条目。
- 2026-10-02 推测层回填 sweep 进行中: `scripts/sweep_tzzb_spec.py`(内容即状态无 state 文件,
  **倒序=新的先补**, 5 日/批 headless `claude -p`, 批后逐日复检【推测】真出现才算成)。
  运行日志=`scripts/backfill_taoge/tzzb_spec_sweep.log`。17:31 进度 105/144 完成, 批13(03-09~03-13)。
  **01-21/01-22/03-06 等早期日无【推测】=还没轮到, 非漏跑**(用户抽查提出, 此条释疑)。
- 2026-10-02 §2.5 立法: 每次合成前必跑 `node scripts/quotes/fetch_cb_quotes.mjs --trends-all` 归档当日分时
  (东财分钟级只留 ~5 天, 当天不归档永远丢失; 执行质量复盘依赖)。
- 2026-10-02 字段语义纠正: pre/aftPositionPercent=**日级**字段(144/144 天恒 0=从不隔夜),
  腿级仓位方向校验假阳性刷屏 → 消融后从 gen_tzzb_md.mjs 删除, 仅保留缺日哨兵。
- 2026-10-02 硬数据层 177 天回填完成: `node scripts/gen_tzzb_md.mjs --all`(整小节覆盖保【推测】行);
  数据完整性终局核查=51 标的 0 缺日, 75 顶格=服务端重复返回第 1 页(冗余非丢失)。
- 2026-10-02 沉默边界立法: 推测层禁止复述硬数据; ⚠️数据校验标的只许描述可见腿时间特征。
- 2026-10-01 立法: 空仓日照常写小节(空仓=纪律信号, 不许跳过)。
- 2026-09-27 骨架建立(与 cb-skill 同日): 两层制=脚本硬数据(零 token) + LLM【推测】逆推层;
  双副本防漂移(改 SKILL.md 必 cp 到 .claude/skills/tzzb-sum/)。
