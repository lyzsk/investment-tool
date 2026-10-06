# tzzb-skill · distill 工作流（高手行为 → persona 反向沉淀, 统一入口）

> 路由来源: SKILL.md。
> **路由表**: `--ledger buchitudou0`(默认) = 土豆纯转债, 走下方机械统计+五闸门流程, 沉淀 → buchitudou0-skill/persona/buchitudou0/；
> `--ledger liunianqing|lianghuaxiaohao|a658|bianbenling|xingjianye` = 五位混合高手, 走**LLM 提取流程**,
> 沉淀 → `skills/<ledger>-skill/persona/`（**skill 名==ledger id**, 10/7 命名立法, 无映射表）;
> lianghuaxiaohao 产出标"(程序化嫌疑)"。本文件是唯一 tzzb 蒸馏入口。

## LLM 提取流程(--ledger 五人版)
0. **机械层先行(10/6 立法, "超越 K3"重构)**: `python scripts/tzzb/gen_tzzb_profile.py --ledger <ledger>` 重跑统计底座——规则里的数字必须来自此输出(手写数字=违规); 桶胜率/出手率/首买通道漂移超阈才进 LLM 审议(对齐土豆分支形态: 机械日常, LLM 审漂移)
1. 核销: 该高手 rules.md `[待验证]` vs 目标日 md(小节+收评/涨停分析/电报)——兑现/打脸/不动三态+样本数
2. 提取: 硬数据+【推测】行分流——行为节奏→profile; 带态度操作→rules(市场/入场/出场/仓位四区); 反常操作→cases; 推测层择优并入证据链
3. **五闸门准入(10/6 对齐 buchitudou0-skill)**: 竞争假设≥2 并列/证据链三环/置信度三级/证伪条款机械可判/反例优先; 每条规则标消费分级 [可跟]/[画像]/[教训]——速览行只输出[可跟]
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
| 目的地 | taoge-skill/persona | buchitudou0-skill/persona/buchitudou0/(rules.md + cases.md) |

## 流程(两步, 顺序不可换)

### 第一步: 机械层(零 token, 每日必跑)

```bash
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_profile.py --ledger buchitudou0          # 画像全量重跑(435 腿统计+T-1联动)
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_review.py --ledger buchitudou0 --json scripts/backfill_taoge/review_cb_daily.json   # 10/7 泛化版(六人含跨日; 原 review_cb_daily=K3 日内单土豆口径, 退役存档)
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_cases.py --all            # 六人 cases.md 双尾区(直连 review 引擎; 土豆 curated/五人 LLM 叙事区保留)
```

比对 rules.md 各 R 的记录值, 漂移阈值(任一命中→第二步):
- 胜率/盈亏比漂移 ±3pp 以上; 首买通道分布(09:25/09:30死窗/追单)漂移 ±5pp
- **新标的首次入场**(滚动熟票池换血=R4 活体信号, 必报)
- 出现 rules.md 任一条"证伪条件"描述的实例(如午后开仓/持仓>5分钟成簇/单笔名义>20万成簇)
- 显著卖飞/逃顶新增样本与既有结论矛盾(如逃顶样本出现在大涨日)

无漂移: 只把 rules.md 各 R 的"验证状态"样本数刷成最新, 收工(静默, 不打扰)。

### 第二步: 核销层(LLM, 仅触发时)

1. 对触发涉及的规则逐条过五闸门(buchitudou0-skill/persona/buchitudou0/rules.md §五闸门), 结论只许:
   兑现(样本数+1, 追加验证记录行) / 打脸(降级或作废但不删除, 移 cases.md curated 区立案) / 欠定保留
2. 新模式要进 rules.md 必须过完整五闸门模板(竞争假设≥2 + 可证伪条款), 否则只进 cases.md
3. **反例优先**: 他违反自己规则的操作优先记 cases.md curated——反例比正例更校准画像

## 纪律

1. **时间纪律**: 核销=用后见验证前瞻规则, 天然无未来函数; 但写"决策原因"类推断仍只许 T-1 及更早信息
2. 机械层数字禁止手改(要改就改脚本重跑); LLM 只写核销结论与验证记录
3. 📜 过程性事件(漂移核销/规则废立)追加到 `skills/tzzb-skill/PROCESS.md`(与 sum 共用一份过程账)
