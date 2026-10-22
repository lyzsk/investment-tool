# 审计：代码复用 / 重复合并 / 各目录用途（10/17 晚，主会话做；零 token，只读）

> 你 20:45 要求："审计代码复用程度、哪些重复可以合并、每个目录下用到的东西是干嘛的"，并要求在主会话里做、别多开 agent。
> 统计脚本 `scripts/temp/audit_1017/reuse_dir_audit.py`（结果 `reuse.json`）。范围：scripts/ 下 176 个脚本（不含 venv / models / temp）。
> "被引用"= 文件名或模块名出现在 scripts/、Java 源码或 skill 工作流里（生产链路能调到它）；没被引用 ≠ 没用，可能是手动工具。
> **本报告只是审计和建议，一行代码都没改。**

## 一、一页结论

1. **公共库用得还不够**：
   - 统一交易规则模块 `a_rules` 只有 17 个脚本在用，同类逻辑（板块判断、涨跌停幅度、手续费、代码 → 市场）还有十几处各写一份。这就是 E22 说的"品种识别只留一份"的问题，审计证实了。
   - 统一请求层 `req_guard` 有 17 个脚本在用，另有约 18 个脚本自己发网络请求或自己写 sleep/jitter。
2. **同名函数在 3 个以上文件各写一份的有 43 个**，最值得合并的 6 组：
   - `sleep/jitter`（12+20 处）
   - md 标题归一 `canon`（7 处）
   - md 小节挂载 `mount`（4 处）
   - `md_path`（5 处）
   - 读写 jsonl（market 域 5 处）
   - 手续费 `fee`（5 处，应统一走 `a_rules.fees`）
3. **整块复制的代码不多**：最明显的是 `slot_profile.py` 和 `t_profile.py`，有 6 段 8 行以上的代码相同（长期 × 近期混合的那套）。其次是 `fetch_cls_zaobao.mjs` 和 `fetch_wechat.mjs` 的 md 挂载段，以及 `quotes/client.mjs` 与 `scan.mjs` / `rotation.mjs` 的 HTTP 取数。
4. **176 个脚本里有 48 个没有被任何生产链路引用**：
   - 约 1/3 是**手动工具**，要保留，例如整日重跑、深度蒸馏、挂单推断、指数时点表抓取。
   - 约 1/2 是**一次性脚本或探针**，任务已完成，可以归档。例如 10/7、10/8 那批重跑脚本，md 批量修补脚本，`tzzb/browser/probe1~6`。
   - 其余是**实验**，例如量化小号逆向 v2。
5. **数据堆在代码目录里**：`scripts/dfcf/paper/` 有 18MB，其中账本备份就有 6 份（`books.bak-*`），另外还有 facts、mimicry、plans、weights 等十几个产物目录。按我们"代码在 scripts、数据在 downloads / results"的约定，这些属于数据。挪动牵涉的引用很多，**建议在 10/23 稳定后单独做一次**，不和别的改动混在一起。
6. **顶层还有几个目录没写进 README**：
   - `skills_versions/`：画像版本快照，11MB
   - `uploads/`：Java 上传目录，138MB
   - `logs/`：3MB
   - `node_modules/`
   
   用途要写进 README。

## 二、各目录是干嘛的（scripts/ 按域）

| 目录 | 脚本数（其中被生产链路引用） | 代码行 | 干什么 | 产物去哪 | 谁用 |
|---|---|---|---|---|---|
| `tzzb/` | 37（23） | 13.9k | 同花顺投资账本：抓取、md 硬数据层、画像 / 指纹 / 统计模型、挂单推断、深度蒸馏、候选筛选、小节排序 | `downloads/tzzb/`、`skills/<导师>-skill/persona/` | Java 抓取任务、check md、决策链 |
| `dfcf/`（含 `paper/`） | 42（33） | 11.9k | paper 模拟盘全套：撮合、账本、facts、混合账本、权重、拟人度、反思、质量开关、报告；另有实盘盯盘和结算（隐私区 snapshots） | 账本和产物都在 `scripts/dfcf/paper/` 下（见结论 5） | Java paper 任务、决策链、check md |
| `chain/` | 11（3） | 6.4k | 决策链驱动器 `run_taoge_chain.py`（主体，约 5600 行）+ 持有期、教训汇总；其余是 10/7~10/8 的一次性重跑脚本 | `results/<链>_chain/` | Java paper 任务、07 排队器 |
| `market/` | 10（10） | 3.1k | 行情库采集：日线、分钟、竞价、外围、复权因子、开盘 15 分钟、历史回补、指数成分时点表、调样调度 | `downloads/market/`、行情库 | Java 行情任务、check md |
| `md/` | 14（9） | 2.5k | 每日 check md 编排、07 排队、素材包、画像 / 规则索引；另有 5 个一次性修补脚本 | `md/`、`skills/*/persona/*_index.md` | Java check md 任务 |
| `lib/` | 8（8） | 2.1k | 公共模块：交易规则 `a_rules`、请求层 `req_guard`、模型调用 `claude_call`、导师登记表 `mentors`、用量日报 | — | 全项目 |
| `backfill_bilibili/` | 10（4） | 2.1k | B站历史补跑引擎和状态；另有巡航、冷启动等一次性编排 | `results/bilibili/` | 手动补跑、check md |
| `bilibili/` | 6（5） | 2.0k | B站视频管线：发现、下载、ASR / 视觉、素材包、UP 操作统计 / 指纹 | `downloads/bilibili/`、`results/bilibili/` | Java B站任务 |
| `lhb/` | 10（8） | 1.7k | 龙虎榜抓取、入库、席位画像、导师 × 席位对照 | `downloads/lhb/`、行情库 | check md、Java 入库 |
| `cls/` | 6（6） | 1.2k | 财联社：早报、涨停池、电报相关 md 处理 | `downloads/cls/`、`md/` | check md、Java |
| `quotes/` | 7（6） | 0.8k | 行情获取客户端：K 线、分时、指标、期货 | `downloads/quotes/` | 撮合、facts、盯盘 |
| `wechat/` | 3（3） | 0.2k | 公众号抓取和挂载（发哥） | `downloads/wechat/`、`md/` | hermes、手动 |
| `hermes/` | 3（3） | 0.3k | 微信桥接、跨机转发 | — | 你在微信里用 |
| `skills_ver/` | 1（1） | 0.9k | 画像版本化 / 回滚 | `skills_versions/` | check md |
| `health/` | 1（1） | 0.3k | 每日健康检查 | — | check md |
| `claude_profile/` | 1（1） | 0.2k | 多 key 轮换、开关文件 `chain_flags.txt`、并发数 | — | 决策链 |
| `holders/` | 1（0） | 0.3k | 公募 / 牛散抓取（你定远期再做，目前不跑） | `downloads/holders/` | 无 |
| 根目录 | 5（4） | 0.8k | `scan.mjs` 六榜扫描、`rotation.mjs` 板块轮动、`sync_skills.mjs`、节假日抓取、`bg_tasks.ps1`（后台任务总览，手动） | — | facts、盯盘 |
| `temp/` | — | — | 临时脚本、备份、沙盒（10/23 后清理，见 TODO 三） | — | **审计发现 Java / check md 不引用 temp，安全**；但 `ab_a4`、`onboard_*` 是今晚明天还要用的 |

顶层其他目录：

| 目录 | 大小 | 干什么 |
|---|---|---|
| `downloads/` | 约 8.5GB | 原始数据层：B站原料 3.7GB（30 天自动清理）、行情 3.2GB（含历史日线 2.9GB）、tzzb / lhb / cls / wechat / quotes 等 |
| `results/` | 319MB | 加工结果：B站转写与视觉、各链运行目录、蒸馏草稿 |
| `md/` | 43MB | 每日复盘 md（429 个），给人看，也是语料 |
| `skills/` | 22MB | 每位导师的 skill（SKILL.md、workflows、persona） |
| `skills_versions/` | 11MB | 画像版本快照（**README 没写**） |
| `docs/` | 1.1MB | TODO + research（41 篇）+ archive + rules |
| `inv-*` | — | Java：stock（业务）、common（工具）、system（定时 / 系统）、admin（后台） |
| `sql/` | 112KB | 表结构（investment_market / investment_tool） |
| `uploads/` | 138MB | Java 上传目录（**README 没写**，内容未细查） |
| `logs/` | 3MB | 应用日志 |

## 三、可以合并的重复（按收益排序）

| # | 重复内容 | 现在在哪 | 建议合并到 | 收益 | 风险 |
|---|---|---|---|---|---|
| 1 | 代码 → 市场 / 板块 / 品种、涨跌停幅度、手续费（`board`、`boardTypeOf`、`limit_pct`、`symbol_of`、`fee`、`isIdx`、`is_repo`…） | 十几处：up_ops_stats、mentor_scope、screen_candidates、seat_profile、backfill_history、backfill_fill_minutes、ledger_limits、t_profile、mentor_model、matcher、replay_daily、collect_daily、kline.mjs、snapshot.mjs… | `scripts/lib/a_rules.py/.mjs`（已有正确实现） | **最高**：撞码、科创量 ×100、转债 ±10% 三次事故都出在这一层 | 中：每处改完要对比结果一致，逐个自测 |
| 2 | 网络请求 + sleep / jitter / 重试 | 12 个 mjs 各写 `sleep`、`jitter`，约 18 个脚本自己发请求 | `scripts/lib/req_guard`（已有间隔 / 抖动 / 熔断 / 日预算） | 高：限速口径统一，封禁事故减少 | 中：各源节奏要先在 `req_guard_sources.json` 配好 |
| 3 | md 处理：`canon`（7 处）、`mount` 小节挂载（4 处）、`md_path`（5 处）、`section` | md/、cls/、wechat/、lhb/、tzzb/ | 新建 `scripts/lib/mdkit.py/.mjs` | 中：md 小节规则统一（例如今天的同花顺排序） | 低 |
| 4 | jsonl 读写、原子写（`write_jsonl` / `read_jsonl` / `wjson` / `_jl`） | market 5 处、paper 6 处 | `scripts/lib/io.py` | 中：今天审计查出的"非原子写"一类问题一次解决 | 低 |
| 5 | `slot_profile.py` 与 `t_profile.py` 的"长期 × 近期收缩混合"（6 段相同） | dfcf/paper | 抽成 `paper/profile_mix.py` | 低～中 | 低 |
| 6 | HTTP 取数 `fetchJson` / `fetchBuf` | quotes/client.mjs、scan.mjs、rotation.mjs | `quotes/client.mjs` | 低 | 低 |
| 7 | 模型调用两套：`claude_call.py`（公共）和驱动器自己的 `call_claude` | lib、chain | 保留两套（驱动器要会话复用 / 分叉 / 并发槽），**只把重试、计费、错误分类抽成共用** | 中：今天自更新重试就得改两处 | 中：驱动器是周一实盘主路径，必须等稳定后再动 |

## 四、可以归档的脚本（一次性 / 探针 / 已被替代，任务已完成）

- `chain/`：`rerun_tzzb_batch1/2/3.sh`、`rerun_tzzb_b1v2/b3v2.sh`、`resume_1007_night.sh`（10/7~10/8 一次性重跑）；`apply_plan_a.py`（方案 A 已合入）
- `tzzb/`：`browser/probe1~6.mjs`（10/14 反爬探针，结论已进 api.md）、`expand8_follower.sh`、`final_gate.sh`（10/7 一次性调度）
- `md/`：`dedup_review_sections.mjs`、`strip_neg_ledger_sections.mjs`、`fix_spacing.py`、`sync_review_sections.mjs`（10/7 一次性修补）；`lhb/add_fupan_old_md.mjs`
- `backfill_bilibili/`：`coldstart_chain.sh`、`cruise_loop.py`（巡航已取消）、`reset_for_new_skill.py`
- `dfcf/paper/`：`reset_books.mjs`（10/8 发令枪）、`rebuild_days.mjs`（10/11 一次性重建）
- 建议做法：移到 `_archive/scripts-oneoff-20261017/`（项目外，和今天早上那批一样），不删；README 记一笔。**等你点头再挪**，和 10/23 的 temp 清理一起做。

**保留的手动工具**（没被定时调用，但要留着）：
- `rerun_day.py`、`top_chains_report.py`、`replay_daily.mjs`
- `distill_history.py`、`order_inference.py`、`backfill_fill_gaps.py`、`tudou_deep.py`
- `mentor_overlap.py`、`gen_players.mjs`、`up_fingerprint.py`
- `holdings_ask.py`、`live_settle.py`
- `indicators.mjs`、`pre_market.py`、`bg_tasks.ps1`
- `fetch_holders.py`（远期）

这批建议在 README 里单独列成"手动工具"一节。

## 五、建议的执行顺序（都不急，周一实盘稳定后）

1. **10/19~10/23 不动结构**：先看周一实盘和今天上线的改动是否稳。
2. **10/23 后（零 token，约半天）**：
   - 归档一次性脚本；
   - README 补上 `skills_versions/`、`uploads/`、手动工具清单；
   - 清理 `scripts/temp/` 和 `scripts/dfcf/paper/books.bak-*`。
3. **再下一步（零 token，约 1 天，逐个自测）**：
   - 合并第三节第 1 项（品种识别 → `a_rules`）、第 3 项（`mdkit`）、第 4 项（`io`）；
   - 然后第 2 项（请求层）。
4. **最后（风险最高，单独做）**：
   - paper 产物目录从 `scripts/dfcf/paper/` 挪到 `downloads/paper/` 或 `results/paper/`；
   - 驱动器的模型调用共用化。

## 六、我不确定的

- "被引用"是按文件名 grep 的：被同名字符串误命中会算成"有引用"，通过动态拼路径调用的会漏算。所以"零引用"清单我逐个看过首行说明才分的类，但没逐个确认没人手动在用。
- "自写同类逻辑"的识别是用正则粗筛的（例如出现 `0.0005` 就算印花税），有误报；第三节第 1 项的"十几处"是人工核过前几处后的估计。
- `uploads/` 138MB 的内容没细看。
