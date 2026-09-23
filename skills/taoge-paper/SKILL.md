---
name: taoge-paper
description: "Use when 桃哥paper试跑的三种会话: evening(晚间解读视频→沉淀规则→产出次日watchlist) / checkpoint(被哨兵唤醒做盘中裁决) / close(收盘对账)。无DB过渡期, scripts/taoge-paper/。"
---

# 桃哥 paper 试跑工作流(7天: 9/21-24, 9/28-30)

核心纪律:
- **T日盘中只用 ≤T-1 晚的沉淀**(桃哥只在交易日盘后发稿, 盘中无新信息)
- **不说"桃哥竞价"**——桃哥是学习对象; 竞价/触发/裁决都是策略自己的模块, 自主迭代
- **桃哥几乎从不空仓(用户原话 99/999)**: 他说"少参与"时手里也有5只票。paper 零仓位必须书面论证"桃哥此刻也会空仓", 论证不出就默认带 buy 触发+仓位计划。规则是他思维的抽象——目的是理解/学习/反思/进化, 不是收集规则条文
- **每日必须有"模拟盘实战思考"**: 盘中场景复盘(关键决策点: 我会怎么判 vs 他怎么做 vs 实际走势) + 次日持仓作战计划(带仓位/出场/证伪线), 写进 journal。可以盘中有想法直接通过微信 k3: 记录
- 决策即写 hashchain.log 防作伪; 数据洞记 holes.log 不编造
- 规则唯一来源: `scripts/taoge-paper/rules_seed.json`(R1-R13, 各带 learned_before); 盘中不发明规则, 新规则只能晚间沉淀追加
- live 模式 sentinel 绝不自动成交; buy/sell 触发一律唤醒本 skill 的 checkpoint 模式裁决
- **追认成交(retro-approval, 9/22 确立)**: checkpoint 因信息不足降级 notify 的 buy, 用户事后确认前提成立(如龙头封板)→ 按系统既定口径(触发 bar 的下一根 m5 开盘价)补入 paper_state, 标注 retro_approved_by/retro_note; 若结算已跑要同步更正 equity.csv 当行(去重+改数), 并重发一条"paper结算更正"推送——推送错了必须更正, 不许装没发生
- **防守≠空仓（2026-09-22 用户指令修正, learned_before=20260922）**: 桃哥本人不可能空仓——防守期 watchlist 也必须产出 ≥1 条 buy 候选（条件苛刻也要写），满足 R 系列条件的票允许 ≤10% 仓位试错；禁止"零开仓"式纯观察
- 所有路径根: `C:/Users/admin/dev/investment-tool/scripts/taoge-paper/`

## 决策智能体通用纪律（2026-09-22 用户立法，桃哥/k3-inv 双修）

1. **结论可复算**：概率 = 案例先验 + Σwi×fi 因子加权，因子打分快照存档，禁止"感觉式概率"
2. **因子一致性<0.6 → 禁给>50%**，改输出形态预判+低自信声明
3. **反锚定**：新证据不得让概率单日跳>5pt
4. **对手盘**：主导持仓者激励分析（基金按收盘申赎→会操纵尾盘/做季末市值/拉高出货接回）
5. **幻觉防控（多教师多学生架构）**：蒸馏必须保留 决策时刻 info_cutoff + 因子打分快照 + 反例；奖励因子=预测vs实际的分档误差（非简单对错）；反馈写回案例卡；任何结论可回放推导链

## 模式一: evening(每晚手动, 交易日 20:00 后)

输入: 当晚桃哥视频(可能还没有——他发稿时间不定, 没有就跳过解读直接复盘)
步骤:
0. **同步当日微信对话**(2026-09-22 用户指令): `node wechat_sync.mjs` → `wechat/YYYYMMDD.md`(用户盘中和 kimi 的全部发言=用户盘中所想)。场景复盘升级为**三方对照: 用户盘中判断 vs Claude/哨兵 vs 桃哥**——用户判对的要承认(9/22 用户 10:10 预判大阴线, 我的 watchlist 无开盘卖出信号), 判错的归因。k3-inv 相关的用户指令同步写进 k3-inv STRATEGY §8
1. 若当晚有新视频: 走 bilibili-taoge 标准管线,  checklist(9/21-22 踩坑后定版):
   - **发现**: `x/web-interface/archive/related?bvid=<上一期>` BFS 一跳(search 接口漏最新视频), 过滤 owner.mid=625315686 取最新
   - **下载**: `node fetch_taoge.mjs --bvid <BV>` → m4a+meta 落 downloads/
   - **转写**: `venv/Scripts/python.exe transcribe.py downloads/<BV>.m4a --out downloads/txt/<BV>.txt` — **必须写进 downloads/txt/ 目录**, 放根目录 correct_names 看不到(9/21 坑: 转写躺了一天没纠错没注入)
   - **纠错**: `venv/Scripts/python.exe correct_names.py txt txt_fixed`
   - **worklist**: downloads/worklist.json 按 `"YYYY-MM-DD": [{bvid,title,pubdate,duration}]` 补当天条目(inject 的数据源, 缺了不注入)
   - **解读**: 读 txt_fixed 转写, 产出 `downloads/analysis/YYYY-MM-DD.json`(schema: date/bvid/title/market_view/mentions[]/operations_today[]/style_rules[]/tomorrow_implication; **operations_today 必须是数组**, inject 要 .join)
   - **注入**: `node inject_md.mjs --replace --dir txt_fixed` — 每日 md 由定时任务预建空 `### 桃哥` 小节, 不加 --replace 会被幂等跳过(9/22 坑); 9/18 手工精修版受保护不被覆盖
2. 对照 rules_seed.json 沉淀: 新规则→追加(带 learned_before=当天); 已有规则被证伪→标注, 不删; 被兑现→补 evidence
3. 产出次日 `watchlist/YYYYMMDD.json`:
   - 逐条对照 R1-R13, 每个 item 的 conditions 必须是**机械可判定**(time_window/price_above/price_below/pct_above/pct_below/amount_gt/vol_ratio_gt), 不许写"看着强"这种条件
   - **pct 类条件对竞价段一律叠 time_window≥09:25**(9/22 坑: 09:15-09:20 可撤单段指示价=假信号, 新华传媒"假开板"虚触发)
   - buy 触发必须能回答: 这是哪条规则? learned_before ≤ 明天? 桃哥本人此刻会买吗(拿视频原话当证据)?
   - 每个 item 写 source 字段追溯到 analysis JSON 的具体条目
   - 零 buy 的 watchlist 是例外不是常态(见核心纪律"桃哥不空仓"与"防守≠空仓")
   - 持仓的退出计划优先于新开仓: 有仓先写 sell 触发, **撤退单默认三档**(9/23 新华都教训: 只挂"冲高撤"遇到低开低走全天等不到): ①早盘反弹/回水上撤 ②破位止损撤(硬价) ③尾盘 14:30 兜底无条件撤; 再写 buy 候选
4. 回顾今天 decisions/*.json: 今天的裁决哪些对哪些错, 错的归因到规则还是执行, 写进当日 close 笔记
5. **写盘中场景复盘**(journal): 挑 2-4 个当日关键决策点(竞价/异动/尾盘), 每个写: 我当时会怎么判 → 他实际怎么做 → 走势验证 → 差距在哪(信息/映射表/盘感/纪律) → 怎么补。这是理解桃哥的核心功课, 比规则入库重要

产出: analysis JSON + 次日 watchlist + (可选)规则追加。微信推送: 合并成 1 条「明日盯盘单」。

## 模式二: checkpoint(盘中被哨兵唤醒, headless claude -p)

输入: sentinel 唤醒参数(触发 item id + 当时快照), wake_requests.jsonl 有记录
步骤:
1. 读触发 item 的 source 和对应规则(rules_seed.json)
2. 读 paper_state.json 当前现金/持仓
3. 裁决: approve(给 qty/price 口径) / reject(给理由) / downgrade-to-notify
4. 写 decisions/<item_id>_<HHMM>.json: {verdict, rule_id, info_cutoff: 唤醒时刻, reasoning ≤3句} —— **先写决策文件再碰任何行情数据**
5. 如需推送微信: 合并当天所有提醒, 全天上限 2-3 条(竞价合并/重大异动/收盘), 间隔 ≥100s, 走 hermes CLI

约束: checkpoint 会话只做裁决不做研究; 单次 ≤ 2 轮工具调用; 不许联网搜索(盘中时效假象)。**哨兵唤醒 prompt 已附关联票实时快照(sentinel lastQuotes 机制, 9/22 加)**: 裁决前提需要跨票验证时(如 R10 要看龙头封板)先看 prompt 附的快照, 有就直接判, 没有才降级人工确认——不要无理由降级(9/22 新华都裁决因拿不到龙头数据降级, 追认后浮盈+4.05%, 链路是对的但慢了一天)。**降级 notify 是合法裁决不是失败**: 信息不足时降级=把判断权交还人, 比盲批强。

## 模式三: close(收盘后, 15:06 自动结算后手动或晚间会话前半段)

步骤:
1. 确认 `node paper_settle.mjs` 已跑(15:06 计划任务): 读 equity.csv 最新 NAV, db_bound/market_quote_daily.jsonl 今日行数
2. 对账: decisions 里的 approve 是否都成交(paper_state.json fills), notify 是否该发都发
3. 行情质量: holes.log 今天有没有洞; raw/ 快照断档时段
4. 写当日 close 笔记到 `journal/YYYYMMDD.md`: NAV/超额/触发清单/裁决对错/明日关注点
5. 进入 evening 模式

## 模式四: inbox 问答【已废弃 2026-09-22】

~~链路: 用户微信发 `k3: 问题` → hermes gateway 落 agent.log → 哨兵 tail 到 → 唤醒本会话 → 回复写 replies/ → 哨兵调 hermes send 推回。~~

**微信问答/指令已由 hermes(kimi-k3) 直连接管**：微信→iLink bot→hermes gateway→kimi，本来就是直达，无需任何中转。"k3:"前缀和"k3回复"标题约定同时废除——用户认准的回复方就是 hermes/kimi 本人。Claude Code 只保留晚间重会话和脚本建设职责(经 hermes 唤起或文件接力)。

## 数据分层(清库纪律)

- `db_bound/*.jsonl` — 列名=未来 DB 表结构(taoge_video/taoge_analysis/taoge_rule/taoge_backtest_run/decision/trade/market_quote_daily), 假期迁移进 MySQL 后可删
- `raw/` — 行情原始流, 结算后可删
- `watchlist/` `decisions/` `journal/` — 保留, 是策略迭代资产
- `paper_state.json` — 唯一真相源, 手动改它=作弊

## 坑与状态(hermes 侧补充 2026-09-21, 9/22 增补)

- **kline bar 成交额字段是 `vol`(股)不是 `v`(手)**, 且无 amount → 统一 shares()/barAmt() 归一(9/18 回放实踩, 否则成交额恒0触发不了条件)
- mkline 的 `b[8]` 成交额时有时无 → 一律缺省估算
- **腾讯竞价时段字段行为未经实盘验证** — 竞价模块(09:24:50 出预期→09:26 验证)按 best-effort 解析+raw 全落盘+异常记洞, 不硬编
- **新股无历史 kline**: mkline 双源都查不到(sz301686 9/22 实踩)→ 按"昨收=发行价, 无历史均量"降级, pct 可用/vol_ratio 失效, 哨兵会发一条"部分票回补失败"告警, 属预期行为不用修
- **`install_tasks.ps1` 已运行**(TaogePaperSentinel 09:12 / TaogePaperSettle 15:06 已注册, 经 run_hidden.vbs 隐藏启动)
- 哨兵回放命令: `node sentinel.mjs --replay <date>`; 产物归档 rehearsal/<date>/
- **结算推送与追认的时序**: 15:06 结算推送按当时 paper_state 出数; 15:06 后的追认成交要在晚间会话更正 equity.csv 当行(去重+改数)并补发"paper结算更正"(9/22 实踩)
- **告警=队列不是一次性**: alerts/ 目录是 outbox, hermes 限流失败退避 15 分钟重投, delivered.log 去重; 盘中告警可能因 kimi 占用 iLink 配额迟到, 不会丢
