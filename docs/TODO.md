# investment-tool TODO（唯一工作清单, 2026-10-07 重组）

> 目标函数: 策略收益养活 Claude 订阅费（10 万本金: Pro≈年化 1.8% / Max$100≈9.1% / Max$200≈19%）
> 消费约定: **人读=前半（§1-§4）, AI 读=后半（§5 起）**; ✅ 项不存 git, 细节看 git log
> 优先级: ★★★=10/8 首跑必须 / ★★= 窗口期 / ★= 等触发; 【PC1】= 绑本机 / 【PC2✓】= 笔记本可干 / 【用户】= 人动手

---

# §1 待用户裁决（最优先, 阻塞下游）

1. **SESSDATA 回填范围**: 卢本圆 273 稿/趋势天哥 524 稿的历史回填需 cookie(解释已给 10/7: 日常发现链无 cookie 可跑, 回填翻空间列表 API 才要)。建议各回填近 2-3 月（30-60 稿）不回全量。
2. **9/28 链 0915 污染决策标注**: 建议只在 TODO 记录, 不动历史产物。
3. **量化实验研究时机**: PC1 攒 2 周原料后。

# §2 10/7 PC1 清单（用户手动, 顺序）

1. `git pull`（PC2 commit+push 后; 跨机数据照 docs/跨机数据清单.md 拷 2 项: downloads/tzzb + downloads/quotes/daily; **勿拷 books/plans**）
2. 插 DB: `sql/paper_sys_job_seed.sql`（13 行含 Review）+ `sql/bilibili_2ups_seed.sql`（cron 已 10/7 定稿, 只需 status 1→0）+ **tzzb 正名**: UPDATE tzzb_record SET ledger='buchitudou0' WHERE ledger='bchitudou0';（不执行则新旧分裂两套, hasNavDay 幂等失效）
3. 重启 application（新 handler/模板/fetch_bilibili.mjs 更名生效）
4. bilibili 三 UP 首跑: 桃哥 job 自跑; 卢本圆/趋势天哥首发现验证（sys_job_log）; VISION_DONE 后 lubenyuan/qushitiange 两 skill 合成+persona 冷启动（10/7 跑完=3 个 bilibili skill 就绪; 沉淀量预测: 趋势天哥≈5 稿, 卢本圆≈0 稿除非当天发）
5. `node scripts/quotes/kline.mjs --from-corpus` 全量日线回补（后台 ~10min）
6. books 检查: matcher --init 幂等; PC1 真实账本保留
7. （建议）PC2 清理测试账本: `rm -rf scripts/dfcf/paper/{books,plans,facts}`

# §3 10/8 首跑（A 级）

- A-taoge 全时刻表 13 job 自动跑: 信号源=全员速览节 / 撮合=四哨兵+价格笼子 / 06 反空仓契约（条件单主形态）
- **首跑观察点**: ①速览节是否被 01 逐源回应 ②发哥刹车是否被 02 回应 ③cand_snap 价格锚 ④废单率 ⑤07 复盘 20:00 自动跑 ⑥勘误表实际跳过
- 前提: 10/7 全部完成

# §4 持续线（日常/等发令）

| # | 项 | 归属 |
|---|---|---|
| 1 | backfill 下载层 45 待办（PAUSE 开关） | PC1 用户 |
| 2 | 夜跑 distill 断点 2026-07-07（账本 distill_state.json） | PC1 |
| 3 | 回放帧 16 例+taoge-sum 回放帧过滤规则+distill 人工审核 | PC2✓ |
| 4 | tzzb: ①五闸门审议首跑 ②op 字段破译 ③转债情绪 ④cb 分时验证 | PC1 |
| 5 | cls wjzt 解析器 23 天 PARSE_FAIL | PC1 |
| 6 | PaperChainHandler exit 3 频率→是否自动续链 | 等首跑 |
| 7 | persona 反问（方案 B 已落） | 等首跑 |
| 8 | fage 权重定级（核销 alpha 后） | 等 2-3 周 |
| 9 | 牧原做 T（30 日振幅现算/R-PNL-TRUE 账户级） | PC1 用户 |
| 10 | TODO 0.7 缺日回填两洞（tzzb-skill(sum) 扫描+fetch_quotes --date 补腿） | PC2✓ |

---

# §5 批判性审视（10/6 自审, 结构性风险按危害排序）

1. **目标函数偏离（最重）**: 100% 工程投入, 零产出在 "明天买什么"。10/8 首跑= 硬 deadline, 再拖反馈闭环断裂。
2. **推测层质量债**: 40 段盲审=good 30/fair 8/poor 2, 3 冲突（10/7 done, 明细 tzzb_review_all.json）; 格式契约已立法（列表式+ 锚点必带, 写进 tzzb-sum 10/7）。剩: 3 冲突段修正。
3. **rules 重审**: day_positions+review 已进统计层（10/7: profile 持仓维度+gen_tzzb_review 六人执行质量复核 436/126/435/84/23/16 trip）; **剩五人 rules 重审**（持仓行为规则类重写——LLM 活, 晚链做）。盲审 40 段: good 30/fair 8/poor 2, 3 段与真实持仓冲突（土豆 9/22 sweep 产+ 刘念青 9/23 编造, 已知污染段清单在 tzzb_review_all.json）。
5. **东财限频实战风险**: scan 挂= 链中止且 misfire=2 丢弃不重试。对策: 首跑日盯 facts 日志; 中期= 降级用昨日数据+ 标注。
6. **速览信噪比未实测**: 9241 字六源塞 01, 注意力稀释风险。对策: 10/8 观察项。
7. **IC 样本量**: 预测性 -0.365(n9)/LLM 重打 0.1503(n34)——小样本不下死结论; 权重全标 "暂定", n≥30 再定。
8. **两套账本风险**: PC1 真实 /PC2 测试同名, 人肉防护。对策: matcher --init 打印签名供确认。
9. **TODO 治理**: 保持 "活跃+存档一行"; 历史靠 git log; 不往 §0 堆已完成叙述。

# §6 架构立法（已定, 执行参照）

- **多决策者**: 所有信号源 skill（tzzb 六用户 /bilibili 三 UP/ 未来公众号）未来各自独立决策链（workflows/chain.md 同构, 七步暂定）; 一期 A-taoge 主链先行（速览= 跨源上下文）, persona 攒厚逐个接链。
- **成长触发器**（每 skill 通用）: rules.md>15 KB 建 rules_index（gen_rules_index.mjs 泛化）; 溯源→references/; 五人 rules 少= 语料形态+ 沉淀轮数, 晚链持续增厚。
- **导师扩张走信号层不走账本层**（arena 10/6 拍板）: 新导师进 01 facts 加权, 不开新账本; 归因用信号层软归因; C 线升级 C-arena; A-taoge/A-cb 保留分账; 一期不动。
- **数据源 switch-case 注册表**（10/5 立法）: 快照 5 源 / 日线 3 源 / 榜单多源+ 电报连板备源; 禁单源直连; 分时东财独占记档。
- **md=当天腿忠实记录**（10/6 立法）: 日内做 T 完整行 / 跨日卖出单行 / 新建仓 (持仓); 仓位=day_positions 真实百分比（推算仅 fallback, 残差股数禁现）; 逆回购展示保留 API 原值含负号（负=T-1 借出回笼镜像, 10/7 用户破译）; 2026 起空节保留（= 信息）, 2025 无数据期骨架删除。
- **skill 目录结构+命名立法**（10/7）: SKILL.md 只做薄路由（身份卡+触发+路由表）, 工作流全文 workflows/*.md 按任务载入（渐进披露, 防上下文爆炸）; skill 名==数据源标识（tzzb=ledger id / bilibili=UP 拼音全名; buchitudou0=10/7 正名[K3 原拼 bchitudou0 丢 u, 全链含 DB 已对齐]）; 双副本用 `scripts/sync_skills.mjs` 同步（编辑 skills/ 后必跑, 目标独有目录脚本不动）。
- **工作纪律+思维八法**（memory 持久）: 不跑偏 / 不偷懒 / 不遗忘; 第一性 / 对抗审查 / 消融 / 奥卡姆 / 列不自信点 / 独立思考 / 批判性 / 高内聚低耦合。
- **git 禁写**（memory 持久）: 只读 git; 改完必 grep 验证落盘（10/6 转义静默失败教训）。

# §7 paper 设计（§E 精存）

> 目的: 不动真钱证明 skill 可靠; 多账本归因。目录 scripts/dfcf/paper/（状态 gitignore）。机械层全建（matcher 六子命令+ 四哨兵+ 价格笼子 / facts v4 导师速览 / report / 驱动器 selftest PASS / 9/28 回放冒烟 $5.69 全链 / Quartz 3+1 handler+seed）。
> **架构**: 事实层共用（零 token）→ 决策层分账（稀疏 LLM）→ 执行层全自动。6 账本 A/B/C × taoge/cb; plans 带 source+facts_version; book 哈希链。
> **A 级时刻表**: 09:15 全链→09:27 纠偏→09:30-45 机械→09:45/10:00/10:30 确认→11:27 定位→12:30 午间链→13:00-03 机械→14:00/14:30→14:55 尾盘。
> **决策契约**: 立即单 / 条件单（主）/ 空仓+ 触发条件; 废单率= 质量度量; 盘中改单= 版本链。
> **参数**: params.yaml; 基准态总仓≤3 成 / 单票≤1.5 成 / 留≥4 成现金; 转债= 全仓单票+ 机械出。
> **回放记录**: C-taoge +6.71% / C-cb +5.15% / A-taoge -0.75%（9/28-30）; B 线回放期空仓; A-cb 二期。
> **证明节奏**: 1-2 周笔记分卡→3-4 周净值门槛→cb 真腿次日对照。
> **未决**: A-cb 时机 / token 日预算 / facts 刷新频率 / 首跑 vs backfill 时序。
> **已知不自信**: cb 纸面上限 / B 线选择偏差 / C 线自觉 / 14:55 两分钟执行窗 / 盘前链零实盘验证。

# §8 后排大活【全 ★】

1. 存储层 Phase 1（Java 实体+DDL 附录 A）→ 2. TaogeAnalysisController（AI→DB 事务入口）→ 3. 账户感知（等语料）→ 4. 第 5 梯队语料（moni/tgb）→ 5. 结构件 P1 → 6. hermes 链路+ 全量回测+ 拟人化 → 7. watchlist 桥+ 票房方法论。

---

# 附录（AI 参考, 不变）

**A. market_quote_daily DDL / taoge 实体要点**: 见 git 历史（10/7 前版本附录 A 全文）。
**B. ProcessBuilder 四条**: 项目根工作目录 / 双流防死锁 /venv 优先 /misfire 策略。
**D. 纪律红线八条**: learned_before+info_cutoff+m5 开盘价 / AI 不进 Java / 4 周门槛 / R-PNL-TRUE 账户级 / R-FACTOR<0.6 禁>50% / 审计哈希链 / 月胜率>60%+ 回撤<10% / 主剧本>50%。
**E. 业界参考**: TradingAgents 辩论制 / AI Hedge Fund 规则集 / AlphaArena 风控>预测+ 净值唯一 / Qlib 闭环。

# 跨机数据清单（2026-10-06 识别 · gitignored 但持久有用的数据）

> 范围：gitignored 且 "持久有用+持续更新" 的数据。MySQL（bilibili_video/tzzb_record/sys_job）天然 PC1，不算文件拷贝。
> 结论：**需拷 PC1 只有 2 项**；**1 项绝对不拷**（PC2 测试账本会覆盖 PC1 真实回放账本）。

| # | 路径 | 内容 | 现状 | 拷 PC1？| 同步机制 |
|---|---|---|---|---|---|
| 1 | `downloads/tzzb/<ledger>/` | 6 账本腿 / 流水 /nav/day_positions.json/state.json | PC2 有全量 | **要** | 一次手工拷；此后 PC1 增量（含 day_positions 主链④增量） |
| 2 | `downloads/quotes/daily/` | 个股 / 指数日线（多源归档，IC/A2 共用） | PC2 有 | **要** | 一次拷；双机各自增量幂等 |
| 3 | `scripts/dfcf/paper/{books,plans}/` | 模拟盘账本 | **PC2=测试垃圾** | **⚠ 绝不拷** | PC1 有 9/28-30 真实回放账本；PC2 建议删 |
| 4 | `scripts/dfcf/paper/facts/` | facts 快照 | 各机独立 | 不要 | 每 slot 现生成 |
| 5 | `scripts/dfcf/paper/nav_*.csv` | EOD 净值 | PC1 真实 | 不要 | PC1 单机 |
| 6-14 | downloads/cls · downloads/bilibili · results/ · downloads/quotes/{cb,stock} · snapshots/ · backfill_taoge/ · venv/ · uploads/ | PC1 常驻单机 | — | — | 时效性 / 隐私 / 永久档案各归 PC1 |

**10/7 操作**: 拷 2 项（合并不覆盖）+ PC2 删测试 books/plans/facts。
**识别方法**: `git status --ignored --short | grep '^!!'` → "持久有用？持续更新？单机时效？" 三问分类；新增 ignored 数据目录时追加一行。
