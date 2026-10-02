---
name: tzzb-sum
description: "Use when 合成同花顺投资账本高手的每日操作进 stocks md: 跑 scripts/tzzb/gen_tzzb_md.mjs 生成硬数据层(零token), LLM 补【推测】思维逆推层, 整小节覆盖写入 ## 复盘 → ### 同花顺投资账本 → #### <高手名>(每日15:10抓取后/用户喊合成投资账本时)"
---

# 投资账本高手操作合成(两层: 硬数据 + 【推测】逆推)

> 📜 过程记录(跑批/格式变更/立法/事故)= 本目录 `PROCESS.md`, 每次有过程性事件就追加一行(2026-10-02 用户立法)。

> ⚠️ 双副本防漂移(同 taoge-sum 9/29 实测教训): 本文件是 canonical; headless `claude -p` 实际加载
> `.claude/skills/tzzb-sum/SKILL.md`, **每次编辑后必须 `cp skills/tzzb-sum/SKILL.md .claude/skills/tzzb-sum/SKILL.md`**。

上游 `tzzbFetchHandler`(quartz, cron `0 10 15-23 ? * *`, hasNavDay 幂等跳过)已完成:
fetch_tzzb.mjs 抓取 → `downloads/tzzb/<ledger>/{nav_daily.json, change_bs_*.json, position.json}` 落盘
→ syncFromRawJson 增量入 `tzzb_record` 表(trade/nav_day/position_snap/bs_leg 四口径, 增量去重不覆盖)。

本 skill = 把落盘原料消化进 stocks md 的 `#### <高手名>` 小节, 供复盘与日后反推。**无 DB 状态机——
整小节覆盖即幂等**, 重复合成不产生副作用。

## 纪律(不可违反)

1. **两层分离**: 硬数据层=脚本产出(数字禁止手改, 要改就改脚本重跑); 推测层=LLM 写, **逐条标【推测】**(立法)
2. **幻觉防控**: 推测层只准从硬数据+原始 payload 字段(prePositionPercent/aftPositionPercent/totalCost/标的特征)
   逆推; 数据里没有的标的/价格/时间绝不出现, 推不出就少写, 不硬凑
3. `#### <高手名>` 小节内容只可能是本 skill 的产出 → 合成即**整小节覆盖**(幂等), 无需任何标记
4. **空仓日照常写**(净值行+无操作)——空仓=纪律信号, 不许跳过(2026-10-01 用户立法)
5. 不改 downloads/ 任何文件, 不直接写 DB
6. **实盘隐私立法**: 用户自己的成交/账户明细永远不进 stocks md(git 文件); 本 skill 只写高手分享页的公开数据
7. **格式机械可验**(同 taoge-sum 立法): 小节内禁止 `#####` 子标题, 校验:
   `awk '/^#### <高手名>$/{f=1;next} /^#{2,4} /{if(f)exit} f' <md> | grep -c '^##### '` 应为 0

## 步骤

### 1. 读高手清单

`scripts/tzzb/tzzb_ledgers.json` 每行一位: `{ledger, name, key, user_key}`。ledger=抓取/原料目录标识, name=md 小节名。

### 2. 生成硬数据层(零 token)

```bash
node scripts/tzzb/gen_tzzb_md.mjs --ledger <ledger> --date <yyyy-MM-dd>
```

产出: 净值行(链算日收益+过夜状态) + round-trip 明细(FIFO配对, 转债=张/正股=股, 封顶10笔) + 汇总(胜率/平均单笔/平均持仓/名义本金) + ⚠️过夜仓警告。
数据校验: change_bs 分页服务端会重复返回第 1 页(冗余非丢失, 10/2 全量核查 51 标的 0 缺日)。
截断/数据矛盾由脚本机械判定并输出 `⚠️ 数据校验` 标记——LLM 只读标记, 禁止自己数数推断完整性。

### 2.5 归档当日行情(机械, 不可再生——每次合成必做)

```bash
node scripts/tzzb/fetch_cb_quotes.mjs --trends-all   # 当日有腿标的的分钟级分时归档(已存在自动跳过)
```

**分钟级行情东财只留 ~5 天, 当天不归档就永远丢失**(2026-10-02 用户立法: 日后做执行质量复盘——
卖飞/逃早/更优操作——依赖此数据)。日线缺失标的(新债)顺手 `node scripts/tzzb/fetch_cb_quotes.mjs --kline --code <code>`。
日线级复盘随时可跑: `scripts/venv/Scripts/python.exe scripts/tzzb/review_cb_daily.py`(卖分位/卖飞上限/持收增量)。

### 3. 补【推测】思维逆推层(LLM)

素材: 当日腿的原始 json(`downloads/tzzb/<ledger>/change_bs_*.json` 里 trans_date 当日的记录)。
逆推维度(有货才写, 每条带数据锚点):

- **进出时点**: 集合竞价进/开盘秒出(9:25买+9:30:0x卖) = 竞价套利; 尾盘进 = 隔夜博弈; 秒级持有 = 盘口 scalp
- **仓位节奏**: pre/aftPositionPercent 是**日级字段**(当日开盘前/收盘后仓位, 非腿级)——恒 0=日内归零纪律
  (144/144 天从不隔夜, 10/2 全量实证); 连续多笔同标的 = 反复撸一只
- **选债特征**: 价格区间(低价债/高价债)、正股联动、当日是否热点板块(对照 md 收评/涨停分析节)
- **风格对照**: 与历史日对比(今天笔数/持仓时长 vs 平均), 反常即重点

沉默边界与负面约束(2026-10-02 立法):

- **禁止复述**: 硬数据层已有价格/数量/时间 → 推测层只许输出意图归因, 复述数据=违规
- **数据矛盾禁推**: 小节带 `⚠️ 数据校验` 标记的标的, 禁止对其做完整性外的事实断言, 只许描述可见腿的时间特征

### 4. 挂载(整小节覆盖)

目标: `stocks/<year>S<quarter>/<date>.md` → `## 复盘` → `### 同花顺投资账本` → `#### <name>`。
md 无此骨架(老文件) → 先跑 `node scripts/md/migrate_md_template.mjs` 补骨架, 再写; 当天 md 不存在 → 跳过并在输出里说明。
多高手 = 多个 #### 小节并列, 各写各的。

### 5. 校验

跑纪律 7 的 awk 检查; 硬数据层数字抽查一笔对原始 json。

## 小样例(2026-09-30 真实产物)

```markdown
净值 14768.8249 · 日收益 +0.43% · 空仓过夜

- 澳弘转债(111024): 09:25:00 买 490张@215.3000 → 09:30:03 卖 490张@216.2836 **+0.46% · 持仓 5分03秒 · 名义 10.6万**

汇总: 1 笔 round-trip · 胜率 1/1 · 平均单笔 +0.46% · 平均持仓 5分03秒 · 名义本金 10.6万

【推测】集合竞价 9:25 买入、开盘 3 秒卖出: 典型的竞价套利——赌竞价定价偏低, 开盘流动性涌进来就抛(锚点: 两腿时间戳)
【推测】单笔 10.6 万名义 ≈ 小仓位试单, 全胜日出清不恋战(锚点: aftPositionPercent=0, 当日仅此一笔)
```
