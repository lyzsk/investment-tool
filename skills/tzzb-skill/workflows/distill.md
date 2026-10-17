# tzzb-skill · distill 工作流（高手行为 → persona 反向沉淀, 统一入口）

> 路由来源: SKILL.md。
> **路由表**: `--ledger buchitudou0`(默认) = 土豆纯转债, 走下方机械统计+五闸门流程, 沉淀 → buchitudou0-skill/persona/；
> `--ledger liuyiqing|lianghuaxiaohao|a658|bianbenling|xingjianye` = 五位混合高手(10/7 起陆续扩到 tzzb_ledgers.json 全部 kind=pos 非土豆账本, 10/15 新增 antoo/zhiyingjuexin), 走**LLM 提取流程**,
> 沉淀 → `skills/<ledger>-skill/persona/`（**skill 名==ledger id**, 10/7 命名立法, 无映射表）;
> lianghuaxiaohao 产出标"(程序化嫌疑)"。本文件是唯一 tzzb 蒸馏入口。

## 输出纪律(10/17 A14③, 全分支适用)

- persona 文件只写**变更/新增**的条目: 新规则、样本数+1、验证记录行、状态改动、修订记录行; 不整段重写/重排没变的内容, 不把 md 原文复述进 persona(证据锚点=日期+≤30 字原话或数字)。
- 改 rules.md/profile.md/cases.md 一律用 Edit 局部替换/追加, 不用 Write 整文件重写。
- 过程说明与最终回复不复述小节/素材包内容; 最终回复每人只列改动清单(如 `R6 样本+1 / 新增 R11 [待验证] / 无改动`) + 哨兵行。

## LLM 提取流程(--ledger 五人版)

0. **机械层先行(10/6 立法, "超越 K3"重构)**: `python scripts/tzzb/gen_tzzb_profile.py --ledger <ledger>` 重跑统计底座——规则里的数字必须来自此输出(手写数字=违规); 桶胜率/出手率/首买通道漂移超阈才进 LLM 审议(对齐土豆分支形态: 机械日常, LLM 审漂移)
0.3 **素材包先行(10/17 A14②)**: 会话开头一次 Bash 生成本会话全部账本的素材包 `scripts/venv/Scripts/python.exe -X utf8 scripts/md/build_distill_pack.py --skill <ledger1>,<ledger2>,... --date <目标日>`(零 token, 秒级); 逐人处理时先 Read `downloads/distill_pack/<目标日>/<ledger>.md`, 内含 ①当天本人小节全文 ②收评 + 涨停分析/龙虎榜同票行 ③近 5 个交易日本人同票记录 ④同票规则全文(带 rules.md 行号) + 待验证规则索引 ⑤画像目录。包里有的不再自己 grep/cat md 与 rules; 包里标"未展开/截断"的、或核销还需要的其他规则, 再按 0.5 的索引法按行号补读。某人 PACK_FAIL/脚本非 0 退出 = 该人照旧按 0.5 读原件。
0.5 **读取走索引(10/15 A13②)**: 先读 `persona/rules_index.md`(每条规则一行+行号)与 `persona/profile_index.md`(画像目录+行号), 对照目标日小节判断本次要核销/修改哪几条规则、哪几节画像, 再用 `grep -n "^#\{3,4\} R<n> " persona/rules.md` 定位、按行区间 Read 只打开这些节; **禁止整文件读 rules.md/profile.md/cases.md**(cases.md 只 grep 目标日日期, 机械双尾区很大: antoo 200KB); 新增规则写在 rules.md 规则区末尾; 改完 rules.md 后跑 `node scripts/md/gen_rules_index.mjs --skill <ledger>` 刷新索引(索引缺失的账本才允许读全文)
1. 核销: 该高手 rules.md `[待验证]` vs 目标日 md(小节+收评/涨停分析/电报)——兑现/打脸/不动三态+样本数
2. 提取: 硬数据+【推测】行分流——行为节奏→profile; 带态度操作→rules(市场/入场/出场/仓位四区); 反常操作→cases; 推测层择优并入证据链
3. **五闸门准入(10/6 对齐 buchitudou0-skill)**: 竞争假设≥2 并列/证据链三环/置信度三级/证伪条款机械可判/反例优先; 每条规则标消费分级 [可跟]/[画像]/[教训]——速览行只输出[可跟]
   - **逆推动机一律给概率分布(10/16 晚用户立法)**: 从成交逆推"为什么"(如同日先后买两只=换方向/走势拿不准两边押/本来就计划试两只…)时, 列出互斥且穷尽的竞争假设, 各给百分比, **合计必须=100%**, 且必含一项"其他/证据不足"(不许为凑整把它压成 0, 证据弱就让它大); 每个假设写①支持证据(时间间隔/仓位大小/板块关系/先买那只后来卖没卖/当日大盘与热点)②它若成立后续应看到什么(可证伪的后果, 如"换方向→首只 1~2 日内卖出"); 后续数据验证了哪个后果, 在 cases/rules 里回写概率修正(样本累计后按命中率校准), 不改原始记录
4. 防串扰铁律: 只读该高手小节+该高手 persona; 画像未建=留白禁借他人; 证据锚点必带; 样本≥2 才入 rules; 哨兵 `DISTILL_OK {日期} {ledger}`
5. **持仓行为规则类(10/7 §H-3 遗留)**: 五人 rules 重审——day_positions 真实仓位(平均仓位%/满仓日/逆回购节奏)与 gen_tzzb_review 执行质量(卖分位/卖飞/持收增量)已进统计层, 持仓类规则以此两源数字为准重写

---

# 土豆分支(默认): 机械统计+五闸门

> 建立: 2026-10-02(用户拍板: tzzb 对齐 taoge 三棒链, 但形态不同——桃哥 distill 语言(重 LLM),
> 土豆 distill 行为统计(重机械, LLM 只审漂移))。
> 串行链: tzzb-fetch(Java cron) → **tzzb-skill sum 工作流**(腿→md 小节) → **tzzb-skill distill 工作流**(md/腿→buchitudou0-skill rules 核销)。

## 与 taoge distill 的本质差异

| | taoge distill | tzzb distill(土豆分支) |
|---|---|---|
| 原料 | 语言(他说了什么) | 行为(他做了什么, 秒级腿) |
| 核销主体 | LLM 逐条读 md 判断 | **机械统计重跑+阈值比对**(零 token) |
| LLM 出场 | 每日 | 仅漂移/新标的/证伪触发时 |
| 目的地 | taoge-skill/persona | buchitudou0-skill/persona/(rules.md + cases.md) |

## 流程(两步, 顺序不可换)

### 第一步: 机械层(零 token, 每日必跑)

```bash
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_profile.py --ledger buchitudou0          # 画像全量重跑(435 腿统计+T-1联动)
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_review.py --ledger <ledger> --json scripts/temp/review_<ledger>_<MMDD>.json   # 10/8 修: 原 scripts/backfill_taoge/ 目录已随重构删除(写彼路径=FileNotFoundError); 现 JSON 工件落 scripts/temp/(如 review_buchitudou0_1008.json)
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_cases.py --all            # 六人 cases.md 双尾区(直连 review 引擎; 土豆 curated/五人 LLM 叙事区保留)
```

比对 rules.md 各 R 的记录值, 漂移阈值(任一命中→第二步):
- 胜率/盈亏比漂移 ±3pp 以上; 首买通道分布(09:25/09:30死窗/追单)漂移 ±5pp
- **新标的首次入场**(滚动熟票池换血=R4 活体信号, 必报)
- 出现 rules.md 任一条"证伪条件"描述的实例(如午后开仓/持仓>5分钟成簇/单笔名义>20万成簇)
- 显著卖飞/逃顶新增样本与既有结论矛盾(如逃顶样本出现在大涨日)

无漂移: 只把 rules.md 各 R 的"验证状态"样本数刷成最新, 收工(静默, 不打扰)。

### 第二步: 核销层(LLM, 仅触发时)

1. 对触发涉及的规则逐条过五闸门(buchitudou0-skill/persona/rules.md §五闸门), 结论只许:
   兑现(样本数+1, 追加验证记录行) / 打脸(降级或作废但不删除, 移 cases.md curated 区立案) / 欠定保留
2. 新模式要进 rules.md 必须过完整五闸门模板(竞争假设≥2 + 可证伪条款), 否则只进 cases.md
3. **反例优先**: 他违反自己规则的操作优先记 cases.md curated——反例比正例更校准画像

## 纪律

1. **时间纪律**: 核销=用后见验证前瞻规则, 天然无未来函数; 但写"决策原因"类推断仍只许 T-1 及更早信息
2. 机械层数字禁止手改(要改就改脚本重跑); LLM 只写核销结论与验证记录
3. 📜 过程性事件(漂移核销/规则废立)追加到 `skills/tzzb-skill/PROCESS.md`(与 sum 共用一份过程账)
