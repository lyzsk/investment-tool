# 2026-11-01 live v2 交互、机械雷达与遗留项验收

## 动态 DecisionPack / 咨询

- `decision_pack.py` 必要检索：levels/peers/themeof/cases/events/pattern/themetop，转债另有cbpath+similar；fast真实覆盖7/7。window重计算归slow，超过120秒明确记missing_slow，不拖住fast。
- `mentor_consult.py` 复用 chain_steps.build_01/persona；候选表只留当前标的，其余按需 `./q`。无固定KB上限，但只读命名查询。
- 土豆skill真实fast/slow均完成，同 sid `3ddaaac1-ccd6-4933-9be6-bd91efb25eb9`。fast原始答复“正股不在土豆交易范围”，slow进一步限定“不能扩大成相关转债也不做”，逐条给shared/different。
- fast经历Markdown/类型错误，经过一次格式修正和离线归一化；slow的invalid_if为list，离线归一化恢复。未把失败格式冒充成功。fast三轮总成本$0.913195，slow $0.189643，后续已减少重复分析。
- `confidence.py` 机械cap：独立样本、同期基准、实际成本、反例、退出、样本外和必要覆盖；模型只能降档。低/候选也允许推送，并带缺失原因。
- 连续market_state/decision_windows覆盖趋势、转强候选、竞价修复、预先转强和持仓风险，不只连板/断板。

- 桃哥fast $0.610444：退潮后弱势修复观察，不盲接；芷影fast $0.532772：更偏等重新走强/冲板接力；刘忆青fast $0.602404：不符合常规连板焦点入口，等焦点回归和放量右侧。四位答案人格差异明确，不是共用模板。
- 桃哥一次通过；芷影/刘忆青经历格式错误后均用已有回复离线归一化，没有额外重跑。confidence.value等常见类型已纳入机械归一化。

## 无人值守机械雷达与两池

- `radar.py` 接入原signals：有效事件→结构化状态/窗口→decision_windows.jsonl→独立自动采集段→原Pusher；每票30分钟、每天≤6条，零模型token，不自动交易。
- 缺情境从最近完成交易日真实行情补建；仍缺则pending_context。
- collect_book：T−1种子+T日实时涨停/炸板、对应转债、拓扑邻居和邻居转债；signals按活跃度选盯盘池；雷达继续回写后续跟踪。
- 正股涨停映射转债已接通，真实断言10/30澳弘电子→澳弘转债111024进入watch_codes。
- 低/候选推送带缺证据，供复盘，不强行高置信。

## viewer与实盘

- 券商流水号前缀导致user_trades=0，新增共享broker_trades解析器；10/30六笔实盘已进入DATA.user。
- consult fast/slow进入原账本导航；orders只画“系统候选(未执行)”，没有明确价格不伪造BS点；非交易日也能看咨询。
- 当前统一入口包含10/29、10/30、11/01，默认10/30实盘视角。

## 用户复盘与U53

- 海洋王周四应接回/周五卖已入candidate；yang核心按整个字辈。
- 澳弘10:35用户考虑B：正股涨停+转债回落+福新妖债类比，结果最高+18.19%、收+7.87%，不倒填为当时确定；福新10/26以analog连接，下一次同类成功才升已核销。
- 凯众只记跌停被翘起、转债可能套利但快且容错低，不升规则。
- U53收盘复算：海洋王100.0218%、大业股份100.1133%，都严重异动；大业仅过线0.1133点，用户“可能绕开”与数据差异保留。

## 遗留机械项

- 惯性拓扑：related_inertia独立产物避免related_yao覆盖；7只写入盘中自动名单。
- 托单/压单：10/22~10/28回放，托单n=898方向12%(基准37%)、压单n=190方向44%(基准63%)，不转信号，未抓到U49来源样本。
- 低照样本着本：D1股票1151、D2股票105、D3股票750；D2 +1%触及63.8%，但D1/D3收盘均值仍负，分开盘中/收盘口径。
- market_beta：5/10/20日1分钟相关并列，海洋王/大业/百洋/新华已生成，避免固定窗口。
- 导师时间×市况：全导师写入 `downloads/tzzb/mentor_regime.json` 与 `docs/research/mentor_regime.md`，包含均值/中位/P10/P90/最好/最差/n。
- 情境+近期程序闸：rules_lint新增缺情境/缺近期窗口，--strict用于新沉淀，旧规则只标不拦。
- 单次冲高卖法n=988：现行均值-0.56%优于两份卖-0.87%；时间上限-1.70%、缩量退出-1.20%，不上线，负结果保留。

- `preflight.py --date 2026-11-02` 全部通过：次日种子池、前日3秒录像、signal自测、澳弘转债映射、LIVE_V2_MODEL=0、01增量、推送dry、viewer实盘。

- 咨询逻辑chain已显式保留：01=chain_steps.build_01；02=连续market_state；03=slow反方/最强反对；04=指定导师fast/slow；05=机械风控；06=只有明确要求挂单才输出orders，并复用原rule_gate G1~G7。不是恢复六段独立模型调用。
- 持仓咨询读取real_start并排除601988；真实断言当前账户含002241/600785且不含601988。建议单缺账户/数量/合法价格会拒绝，G5无盘口时明确未校验。
- `consult_config.json`：09:20~10:30默认fast_slow，其余默认slow_only；fast timeout120s/low effort，slow300s/medium effort。auto先输出fast并flush，再做slow；无fast时slow可独立深审。

- 新增 S19首次冲板候选、S20首次跌停候选：60秒动量+动态价格带+成交额/盘口确认，T日触过板不重复。构造测试全过；10/30 10点前真实回放S19 9只、S20 10只，已微信解释“预测候选不是事实”。
- K线top1文字与MEDIA图片均已推：歌尔股份、中国银行、新华百货；图片脚本 `push_top1_images.py` 每票日K+五日仅top1。中国银行首次因预测生成日>案例日被漏，已修为按当前日期取最新预测。

## 不自信点

- 四位导师fast均已验收，slow目前只完成土豆；其他导师的slow仍待真实复核。
- window重查询在120秒内仍可能失败，slow必须保留missing而不是假装相似案例存在。
- 雷达当前依赖已通过原闸的signal和最近完成日情境，尚未证明候选窗口能提高收益；先影子/少量推送。
- 新增统计样本集中近期，不能直接当稳定alpha。
