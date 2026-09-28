# Claude Code → hermes 交接单:2026-09-27 晚(回测全面铺开 + 回填启动 + 微信通道打通)

## ① 今天建了什么(都是 git 内文件,可直接读)

| 资产 | 路径 | 一句话 |
|---|---|---|
| taoge-skill | `skills/taoge-skill/` | 桃哥人格画像+决策规则(persona/profile+language+rules),语料=现有 240 篇 stocks md 的桃哥小节;定位=盘中任意节点可触发的完整决策链(事实走代码,人格只做判断) |
| replay 回测引擎 | `scripts/plan-a/backtest/replay*.mjs` | 8 模块,决策落盘+哈希链后才碰当日行情,LLM 只进盘前+收盘两节点,headless claude -p 温度 0 |
| A 组回测成品 | `scripts/plan-a/backtest/runs/replay-260629_260926/A/` | 20260629→260924 全区间:+5.55%,8 笔 4 round-trip 全胜,回撤-0.06%(同期上证约-4.6%);⚠️有效样本只有 8 天(结构化`#### 解读`9/14 才存在),统计上证明不了什么 |
| 回填脚本 | `scripts/backfill_taoge.py` | 699 索引/323 待办,产物=results 四件套;今晚已启动(特例 --ignore-window),新增 auto-md 钩子:每天 results 完成即 headless claude 写回当天 stocks md |
| taoge-sum 定稿 | `skills/taoge-sum/SKILL.md` | 9/24 定稿五大 bullet 全收 `### 桃哥` 下;新增批量改写分支(回填日期无 DB 行,不 curl) |
| tzzb API | (记忆+待建 `skills/cb-skill/`) | 不吃土豆0 的 174 条调仓/胜率/净值可匿名拉(capital.hexin.cn,key+user_key 即凭证) |

## ② 正在跑的两个后台(明早你盘中前应有结果)

1. **C/D 组 replay 跑批 ✅ 已完成(23 点前)**: A +5.55%(8笔4胜) / C 裸LLM -12.59%(40笔) / D persona -18.63%(55笔)。对比产物=`scripts/plan-a/backtest/runs/replay-260629_260924/compare/`(equity-compare.png 三曲线+买卖票名标注, daily_detail.xlsx 每日三组买卖明细)。读法: 训练污染下 C/D 绝对收益不可信, 信号=C→D 差值(persona 组多交易 15 笔、胜率更高 52% vs 40% 但亏更多——人格让它"更像桃哥地频繁操作"却没带来收益); A 有效样本仅 8 天。用户盘中若问结论, 照此口径答, 别吹 A 的 +5.55%。
2. **回填挂机**(日志 `scripts/backfill_taoge/backfill.log`, nohup 主进程存活): 逐条 视频→results→自动写 md。⚠️2026-09-18 用户手工精修永不覆盖。~~replay 窗口冻结~~ **已解禁(9/27 23:00, C/D 已跑完)**: 窗口内 9/15-17/21-23 已按新模板重写, 9/18/9/24 除外; 连带影响=窗口内旧 `#### 解读` 已消失, 未来重跑 A 组需 planner 适配新格式。
3. **md 回写检查表**: `scripts/backfill_taoge/md_checklist.md`(results↔md 一一对应, ✅/⬜/⏳/⏭ 四态), 重跑 `scripts/backfill_taoge/gen_md_checklist.py` 取最新。⚠️教训: vision.json 完成判据键是 `ocr` 不是 `pages`(scan_done 曾因此漏判 31 天, 已修为两键兼容)。

## ③ 关键认知(用户今天拍板的)

- **训练数据污染**:LLM 权重里有 2025-2026 市场记忆,info-cutoff 滤不了 → C/D 绝对收益不可信,**C→D 差值有效**(污染抵消),A 组无污染。replay=驾校模拟器,前瞻对照=路考。
- **证据锚定**:C/D 每条决策必须带 evidence 引用信息包内容,引不出不许下单(smoke 已实证拦下两起幻觉)。
- **回测对照组=三组**:A 照抄桃哥 / C 裸LLM / D persona;B 机械规则砍掉(taoge-paper 实盘在跑);E 一致率只是指标。

## ④ hermes 侧今天新增的能力

- `hermes send --to weixin "..."` 实测可用(网关在线),Claude 晚间任务完成后会通过它推汇总。
- 你的 MEMORY.md 已加"Claude 资产地图"条目:Claude 记忆目录/CLAUDE.md/handoff/skills/runs 全部纯文本直接可读。**用户明天不在 PC 前,你盘前先读本交接单 + `C:\Users\admin\.claude\projects\C--Users-admin\memory\MEMORY.md` 索引,即同步到今天。**

## ⑤ 明日(9/28 周一)盘前提醒

- C/D + compare 结果应已出,用户可能要微信看结论摘要(三组收益+每日买卖区别)。
- 回填在跑,GPU 守卫>6000MiB 会让路,不与盘中任务抢卡。
- taoge-skill 前瞻对照首跑被回测插队,用户尚未拍板何时跑。
- 实盘隐私立法不变:账户明细只在 `scripts/dfcf/snapshots/`,git 文件一律不写。

— Claude Code 2026-09-27 晚
