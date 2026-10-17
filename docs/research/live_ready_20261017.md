# 实盘链路收口（10/17 凌晨，① agent）——周一 10/19 08:05 0915 链首跑前

> 任务来源：`scripts/temp/agent_plan_1017.md` 第①节。噪声带实验 00:19 出完报告（`docs/research/noise_band_20261016.md`）后才动的实盘文件。
> 本轮没有发同花顺请求、没写业务库、没碰 git、没在 09:15–15:00 发请求；行情源只在 00:3x 发了约 8 次单票快照（核对行情日期字段用）。
> 沙盒全部带 `CHAIN_RUN_TAG`（live1017 / live1017off / live1017fix），run_dir 在 `results/<链>_chain/asof-20261016-live1017*`，没覆盖 `asof-20261016`。

## 1. 改了什么

| 文件 | 改动 | 备份 |
|---|---|---|
| snapshot.mjs / matcher.mjs / run_taoge_chain.py / live_watch.mjs / kline.mjs | **交易规则实盘补丁**（`scripts/temp/rules_patch/apply_rules.py --apply`）：板限、涨停价、价格笼子、费用、成交量单位统一走 `scripts/lib/a_rules`——转债 ±20%（原 10%，即健壮性 H4）、笼子补"10 个价位"、ETF/转债不设笼子、转债/ETF 卖出不收印花税、盯盘均价单位、驱动器 06 申报数量闸（主板 100 股整数倍/科创 200 股起/转债 10 张） | `scripts/temp/rules_bak/*.pre_apply_20261017002542` |
| run_taoge_chain.py（自测夹具） | 上面补丁的驱动器自测有一项挂了：宁德时代 30 股的单子被新的申报数量闸正确拦下（30 股本来就不能报），所以把夹具改成 400 股、价位 28.65（只改测试数据，不改校验逻辑） | `scripts/temp/live1017_bak/run_taoge_chain.py.orig_0017` |
| matcher.mjs | **H2**：分钟线缓存键改成带市场前缀的代码（sh000001 上证指数和 sz000001 平安银行原来会混成一组）。沙盒复现：旧版把 000001 卖单按 **3720.51 元**成交（就是指数点位），新版不成交、留着交给日线兜底；正常票（300413）照常成交 | 同上 |
| snapshot.mjs | **H3（源头）**：三个行情源都把"行情属于哪个交易日"带出来（腾讯 f[30]、东财 f86、新浪 f[30]，00:3x 实测三家都是 2026-10-16），标 `stale`（行情日期早于今天=盘前/休市）；新增 `todayPrevClose()`；命令行模式（驱动器 cand_snap 用）盘前把"前收"改成上一交易日收盘（原值留在 `sessionPrevClose`）。**原字段不动**（baselines 把快照当当日 K 线用，要原来的口径） | 同上 |
| matcher.mjs | **H3（拒落账闸）**：前收按快照的交易日取——当天的行情用 prevClose；行情停在上一交易日就用 last（那天的收盘）；日期更早、或没有日期又没开盘的，不信快照，改走日线，**而且要求日线最新一根 = 上一交易日**，不是就先补档，补不上就拒，拒因写"前收日期不符"。复现：10/09 星见野 600241 挂 11.17 → 前收取 10.69（10/08 收盘），通过（原来取 9.72，算出偏离 14.9% 被拒）；周一的单 600148 挂 17.50 → 前收取 16.28（10/16 收盘），通过（旧版取 14.8，偏离 18.2% 被拒） | 同上 |
| facts.mjs | H3：盘前的"关注票实时快照"标题标明"行情停在 X 日收盘，价格=今日前收，涨跌幅/高低是那一天的，今天还没开盘"；每行标"(=今日前收)" | 同上 |
| mix_plans.py / rerun_day.py / ledger_limits.py / replay_daily.mjs | 这几处自己抄了一份费用算法，统一改成调 `a_rules.fees`（和 matcher 一致：佣金万 2.5、最低 5 元，印花税只收股票卖出）。ledger_limits 原来去找 `_AR.fee`，这个函数不存在，所以一直在用本地那份老算法 | `scripts/temp/live1017_bak/*.orig_0017` |
| run_taoge_chain.py | **沙盒发现的约束冲突（已修）**：低频导师今天"导师不动、链也不动"这道闸关着（不许开新仓），同时满仓型导师又有总仓下限硬约束，两条叠在一起，凑仓只能加仓已有持仓。星见野链 10/16 被逼着把 66% nav 压进中国银行（导师从来不碰银行），拟人审连驳三轮还是没解。修法：闸关着的那天，总仓下限改成软约束（`pc["ledger_soft_floor"]`）。用同一份数据重跑星见野：软下限放行、不再硬凑，拟人审第 2 轮通过 | `run_taoge_chain.py.pre_floorfix_*` |
| run_taoge_chain.py（自测） | 自测开头把 `CHAIN_CONSISTENCY` 固定为 0。原因：chain_flags.txt 把言行一致性打开后，自测会读到实盘的开关，账本约束用例里的假票被"引用核对"误拦，挂 13 项 | — |
| run_taoge_chain.py / matcher.mjs / chain_flags.txt | 按主会话转达，最后合入了 ② 的决策质量补丁（`scripts/temp/b_patch/apply_quality.py --apply`）。它的 6 个新开关（PRICE_RULES/SLOT_BUDGET/T_PROFILE/SIMILAR_DAYS/OVERRIDE_LOCK/RULE_CHECK）**都是 0，没开** | `scripts/temp/b_bak/*.pre_quality_20261017_013437` |
| chain_flags.txt | 6 个开关置 1（见 §2） | `scripts/temp/live1017_bak/chain_flags.txt.orig_0017` |

没改的：`collect_minute.py`（健壮性 H1 的 Python 部分 10/16 晚已经改好：缺得多就换服务器补抓，补完仍不够就不写 DONE、退出码 1）；`minute_supplement.py` 的 H2 部分 10/16 晚也已修。kline.mjs 和 live_watch.mjs 只打了交易规则补丁。

自测：`run_taoge_chain.py --selftest` **PASS**（读的是实盘 chain_flags，开关已开）；`mix_plans --selftest` PASS（35 项）；`a_rules.mjs/.py --selftest` PASS；改过的 .mjs 全部 `node --check` 通过。

## 2. 开了哪些开关（chain_flags.txt，下次跑链就生效，不用重启）

`CHAIN_INLINE_CTX=1`、`CHAIN_SHARED_PREFIX=1`、`CHAIN_MAIN_SESSION=1`、`CHAIN_CONSISTENCY=1`、`CHAIN_REFLECT_TRIGGER=1`、`CHAIN_LEDGER_CONSTRAINTS=1`。6 个全开，理由见 §3。② 的 6 个新开关是 0。

## 3. 沙盒验证（10/16 事实包，as-of；花费 $81.5）

起点：用 `rerun_day.prep` 建的沙盒（实盘账本去掉 10/16 当天，回到 10/15 收盘；facts/2026-10-16 原样拷入，和噪声带实验同一口径）。没有直接复制 `rerun_20261016/sb`，因为那份账本里已经有 10/16 当天的单，直接拿来跑 0915 会重复下单。另外换了一层外壳 `scripts/temp/live1017_sb/chain_wrap.py`：回炉日志只写 run_dir；偏离触发读沙盒里的 reflection/ 目录（放的是 10/16 那份触发文件，改名成 10/15，好让 10/16 的回放能读到）。

| 运行 | 内容 |
|---|---|
| live1017 | 6 开关全开：桃哥 / 刘忆青 / ST之狼 / 星见野 0915 全链 + 刘忆青、ST之狼 10:00 子链（先分钟线撮合到 10:00） |
| live1017off | 同一把 key 的对照：只关 A6 三个降本开关，另三个照开；刘忆青、ST之狼 0915 |
| live1017fix | 修完下限冲突后，星见野 0915 重跑 |

**① 串链：0。** 共享开头只含公共部分（零 token 检查：facts.md 原文有 19 行账本、19 个 ### 小节；共享开头里账本 0 行、导师小节 0 个，只留发哥/财联社三节，约 36KB）。会话转写检查（`check_leak.py`，只看消息正文和工具结果，不算 Claude Code 自带的 gitStatus/技能清单）：本次 33 个会话，每个会话里只出现自己那条链的 run_dir、自己的 `A-<链>` 账本名和自己导师的画像特征行，别人的一次都没出现；共享开头那个会话一个导师都没有。

**② 回炉 / 超时 / 成本**

| 链 | 开关全开 $ / 用时 | 回炉 | 同一把 key、A6 关 $ / 用时 | 噪声带（开关全关、别的 key） |
|---|---|---|---|---|
| 桃哥 | 18.96 / 19min | 0 | — | 14.2 / 12.1 / 24.6 |
| 刘忆青 | 7.61 / 14min | 0 | 7.94 / 22min | 6.5 / 7.6 / 10.9 |
| ST之狼 | 10.88 / 16min | 04 回炉 1 次（卖中国银行的单写了 hold_days=0） | 10.45 / 21min（同样 04 回炉 1 次、同样的原因） | 6.0 / 6.8 / 15.5 |
| 星见野 | 15.11 / 22min（拟人审 3 轮，见下） | 04 回炉 1 次（候选缺 play 字段） | — | 5.5 / 7.9 |
| 星见野（修后） | 7.14 / 17min | 0（拟人审 2 轮） | — | — |
| 子链 10:00 | 刘忆青 1.87 / 5min，ST之狼 1.58 / 6min | 0 | — | — |

- 没有超时。0915 回炉 2 次/4 链，都和开关无关：hold_days=0 关掉开关照样出现；缺 play 是账本约束的候选池校验，一次就改对了。账本约束的 06 硬约束全部"通过"，没有回炉——模型看了约束块，一开始就照着下单。回算里说的"88% 出单会被退回"在这一天没出现。
- **成本：A6 三个开关这几天省不了钱，也不更贵**：同一把 key 下，刘忆青 7.61 vs 7.94、ST之狼 10.88 vs 10.45。按设计，分叉会话应该读到共享开头的缓存（10/14 实测 read≈36k），这次分叉只读到 0~5.6k，各步还有大量不走缓存的输入（in 几十万 token）；关掉 A6 那组同样有大量不走缓存的输入。本次全程走的都是 `gravitex` 这套配置，我判断是网关这几天缓存命中差（噪声带 r3 也是这样，贵 70%），不是开关本身的问题。**墙钟时间 A6 开着快 5~8 分钟**（材料内联，省掉 Read 往返）。
- 偏离触发：桃哥、星见野的 04/06 注入了提示（801/501 字）；刘忆青、ST之狼在 10/16 的触发文件里本来就没触发，所以没注入，这是对的。
- 言行一致性：8 次检查都是"一致"，没有因此回炉；ST之狼"03 偏多却账面净卖 9%"写了理由（卖的是能力圈外的银行遗留仓）。
- override 记了 7 条（`sb/overrides/2026-10-16.jsonl`）。

**③ 拟人审退回率**：0915 开关全开的 4 条链里，3 条一次通过；星见野 3 轮都驳回，最后降级照发、单子标【未过盲审】——根因就是上面那个约束冲突（0915 修前退回 1/4 链）。修后重跑星见野：第 1 轮驳回（要给遗留的中国银行挂纯止损卖单，被判不像导师），第 2 轮改成不出手、通过。子链两条都没有新买单，按规则跳过拟人审。A6 关的对照组 2 条都一次通过。

## 4. 周一 10/19 要盯什么

1. **08:05 0915 首跑**：16 条链同时用共享开头——第一条抢到锁的链建会话，其余等它建好再分叉；会话信息存在 `scripts/dfcf/paper/facts/2026-10-19/0915/.prefix_session.json`。看每条链日志有没有"共享开头会话已建/本链开头会话已建"；如果出现"共享开头会话构建失败"，会自动退回只内联，不影响出单。
2. **盘前前收**：0915 链出单 import 时（约 08:25~09:00）日志应该出现"前收按快照日期: … 行情停在 2026-10-16(上一交易日)收盘"；`import_rejects.csv` 里不应再有"前收 X"对不上上一交易日的拒单。cand_snap.md 每行应带"·盘前(行情停在2026-10-16收盘…)"。
3. **拟人审退回和【未过盲审】单数**，重点看满仓型 + 低频导师（A658/边学/星见野/宣秋）：日志应该出现"今天导师不动闸关着 → 总仓下限按软约束执行"，不该再有被逼加仓银行/宽基的单。
4. **成本**：盯 `token_log.csv` 的 in_tokens。in 持续几十万、cache_read 很低，就是网关缓存不灵，A6 省不了钱；换一把缓存正常的 key 再看。
5. **06 申报数量闸**（新）：科创板不足 200 股、主板不是整百、转债不是 10 张整数倍的单会回炉，看回炉原因里有没有"不合申报规则"。
6. 转债链（A-cb/B-cb）：板限按 20% 算，+10% 附近不再被当成封板；卖出不收印花税。

## 5. 需要主会话 / 用户做的事

- **H1 Java 补丁（用户粘贴后重启 application）**：`scripts/temp/live1017_patch/H1_java_minute_coverage.md`——对账改成按"分时覆盖的票数 ≥ 关注集 95%"判；importMinute 再看一遍 manifest 里的缺失数。Python 侧已经不写残缺的 DONE，所以这条是加固，不急。
- **6 个 skill 的 profile_index 已过期**（深度蒸馏改了 profile.md，驱动器对失配的节**不注入**）：a658 2 节、daxingdaxingdadangxing 7 节、gaogailvfuli 6 节、stzhilang 4 节、xingjianye 2 节、zhiyingjuexin 4 节（检查脚本 `scripts/temp/live1017_sb/check_profile_index.py`）。周一 08:05 前要跑 `scripts/venv/Scripts/python.exe -X utf8 scripts/md/gen_profile_index.py --skill <名>`（增量，只重标改过的节，要调模型，约 $0.9/个）。skills/ 不在我的可改范围，没跑。
- 交易规则补丁的 research 组（order_inference/mentor_model/seat_profile）没打，要等占用它们的 agent 结束：`apply_rules.py --group research --check` → `--apply`。
- 小问题（不挡周一）：04 的 hold_days 校验要求卖出遗留仓也写正整数，两组都因此回炉一次（每次约 $0.9）。可以考虑卖单 hold_days 允许 0；驱动器现在由我负责，不过这属于行为改动，没定之前没动。
- 发现：10/16 23:32 有人跑的 `scripts/temp/a6_leak` 没带 CHAIN_RUN_TAG，覆盖了 `results/{xingjianye,stzhilang,control}_chain/asof-20261016`。

## 6. 不自信点

- **A6 省钱的结论受网关影响**：只比了一天、两条链，用的是同一把 key 下的 1 对 1；"网关缓存差"是推断，没单独验证（应该在缓存正常的 key 上再比一次）。省钱只是这三个开关的预期收益；串链检查没问题，所以照用户 A13 的决定开了。
- **主会话模式**下，04/06 能看到本链 02 的完整推理（E27 说的"更自我一致、更少自我纠错"），一天的样本看不出这个效应。
- 腾讯行情盘前什么时候切换到新交易日、切换后 f[4] 是不是马上变成昨收，没在交易日早上实测过。代码按行情日期判断，切换前后两种情况都能处理；但万一某个源切了日期、数据却还是旧的，这种情况看不出来。周一 08:15 看日志。
- 下限冲突修法比较粗：闸关着那天整条链改成软下限，没有区分"已有持仓在不在导师风格内"。如果已有持仓本来就是导师风格的票，原来硬凑是对的，现在可能偏轻仓。
- 偏离触发在沙盒里用的是 10/16 收盘后算的触发文件，喂给 10/16 盘前，有后见之明；只验证了"能注入、注入了什么"，没验证效果。
- 沙盒 4 条链、1 天，没覆盖转债链（buchitudou0 不走言行一致性检查，A6 对它也是关的）和 B站另两位 UP。

## 交接

- 已完成：§1 全部、§2 开关、§3 验证、② 质量补丁合入（6 个开关为 0）、真驱动器 selftest PASS（01:3x，读实盘开关）。
- 未完成 / 留给主会话：§5 前三条（Java 粘贴、profile_index 重标、research 组规则补丁）。
- 回滚：开关回滚 = `cp scripts/temp/live1017_bak/chain_flags.txt.orig_0017 scripts/claude_profile/chain_flags.txt`，再把 ② 追加的 6 行补回去（或直接用 `scripts/temp/b_bak/chain_flags.txt.pre_quality_20261017_013437` 再把 6 个开关改回 0）；代码回滚 = 用 §1 表里对应的备份按顺序拷回（rules_bak → live1017_bak → b_bak 的时间顺序）。
- 沙盒与工具：`scripts/temp/live1017_sb/`（run.py 跑链、analyze.py 成本/回炉、check_leak.py 串链、check_floor_fix.py 下限修复、check_prefix.py 共享开头内容、check_profile_index.py 画像索引）。
