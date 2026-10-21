# -*- coding: utf-8 -*-
"""paper_line_graph.py — 一条 paper 线(A658)的数据 / 动作 / 规则关系图(10/20 晚用户要: "什么文件指向什么, 动作、规则、影响、输入、输出")

不是流程图: 节点 = 定时任务 / 外部行情源 / 采集器 / 数据文件 / 动作脚本 / 规则闸 / 账本产物 / 人看的出口; 边 = 触发 / 读 / 写 / 约束 / 影响。
时刻和耗时取 10/20 A658 实际运行(results/a658_chain/live-20261020 各产物时间戳 + sys_job 排程); 有 ⚠ 的是已知问题。
用法: scripts/venv/Scripts/python.exe -X utf8 docs/graph/paper_line_graph.py  → docs/graph/paper_line_a658.html(双击打开, 无 CDN)
改图 = 改下面的 N / E 两张表; 新增脚本 / 数据源时同步加节点(不加 = 图过时)
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 阶段列: 0 前夜/盘前 00:00~09:14 · 1 竞价 09:14~09:30 · 2 盘中 09:30~15:00 · 3 收盘后 15:00~18:00 · 4 晚间 18:00~24:00
PH = ["前夜 / 盘前 00:00~09:14", "竞价 09:14~09:30", "盘中 09:30~15:00", "收盘后 15:00~18:00", "晚间 18:00~24:00"]
# 类型(行带): 触发 / 外部源 / 采集 / 数据 / 动作 / 规则 / 产物 / 出口
TY = {"trig": ("定时任务 / 触发", "#7c3aed"), "src": ("外部行情源", "#0891b2"), "col": ("采集器", "#0d9488"), "data": ("数据文件", "#2563eb"),
      "act": ("动作脚本", "#ea580c"), "rule": ("规则 / 闸", "#dc2626"), "out": ("账本 / 产物", "#16a34a"), "view": ("人看的出口", "#94a3b8"),
      "scan": ("全部产物: 谁读(自动扫描)", "#eab308")}

# id, 类型, 阶段, 名称, 说明(动作 / 规则 / 输入输出 / 时刻 / 耗时 / 问题)
N = [
    # ---------------- 触发 ----------------
    ("t_md", "trig", 0, "00:00 交易日 md 生成(Java)", "tradingDayMarkdownHandler 每天 00:00; 生成 md/<季>/<日>.md 骨架(早报 / 加红电报 / 当前持仓 / 导师小节)"),
    ("t_global", "trig", 0, "07:15 外围收盘(Java)", "marketGlobalHandler; 隔夜美股 / 港股 / 期货收盘 → global_kline.jsonl"),
    ("t_panel", "trig", 0, "07:30 PanelCollect(计划任务)", "Windows 计划任务 → collect_panel.py --ensure, 07:30~15:05 每分钟"),
    ("t_cls", "trig", 0, "每 5 分钟 加红电报(Java)", "clsRedTelegraphHandler 全天每 5 分钟; 写进当天 md「加红电报」节"),
    ("t_zaobao", "trig", 0, "07:00~09:45 每 15 分钟 早报(Java)", "clsZaobaoHandler; 财联社早报挂进 md"),
    ("t_0915", "trig", 0, "08:05 A658 盘前全链", "paperChainHandler a658:0915 → run_chain.py --skill a658 --slot 0915; 10/20 实际 08:07:10 开跑, 06 08:19:06 出单(12 分钟)"),
    ("t_auction", "trig", 1, "09:14 开盘竞价采集(Java)", "marketAuctionHandler OPEN → collect_auction.py 09:15:00~09:25:40 每 15 秒"),
    ("t_0927", "trig", 1, "09:27 A658 竞价纠偏子链", "a658:0927; 10/20 09:28:40 开跑, 09:31:54 出 06(3 分钟); 只跑 02/04/05/06/拟人审"),
    ("t_mix", "trig", 2, "每 5 分钟 check md --only mix", "checkMarkdownHandler 09:00~14:55 每 5 分钟; 顺带拉起 collect_book / collect_panel / open_live / t_event, 跑 mix_plans / t_bot / t_decide / t_swing"),
    ("t_match", "trig", 2, "每分钟 撮合(Java)", "paperMatchHandler 09:00~14:59 每分钟 → matcher.mjs --once"),
    ("t_1030", "trig", 2, "10:30 A658 子链", "a658:1030; 10/20 10:31:33 开跑(闸 b/c/d 触发), 10:36:09 出 06(4.5 分钟) → 正强股份 2400 股"),
    ("t_1400", "trig", 2, "14:00 A658 子链", "a658:1400; 14:01:30 → 14:05:02"),
    ("t_1455", "trig", 2, "14:35 A658 尾盘子链", "a658:1455(cron 14:35); 10/20 14:36:50 被零 token 闸跳过(没调模型)"),
    ("t_eod", "trig", 3, "15:05 日终 EOD(Java)", "paperEodHandler → matcher.mjs --eod: 废单核销 → nav → state_digest → report"),
    ("t_tzzb", "trig", 3, "15:10~23:10 每小时 投资账本", "tzzbFetchHandler; 真人 A658 账本(nav_daily / day_positions / 逐笔腿); A658 10/20 时停在 10/16(真人没上传)"),
    ("t_market", "trig", 3, "15:35 行情库收盘入库(Java)", "marketDailyHandler; 全市场日线 / 分钟线 / 竞价 → downloads/market/<日>/ + 行情库"),
    ("t_07", "trig", 3, "15:40~17:40 / 22:30 / 23:40 07 复盘", "checkMarkdownHandler --only review07; 标签(真人账本)到了就跑"),
    ("t_settle", "trig", 3, "15:40~ 07 前: 决策结算(机械)", "10/21 起原 15:50 任务删除, 每轮 07 发起前跑 settle_decisions.py(幂等, 只做机械结算; LLM 反思已删)"),
    ("t_checkmd", "trig", 4, "18:00~23:00 每小时 check md 全量", "盘后蒸馏 / 指标 / 拓扑 / 拟人度 / 日报推微信 / report"),

    # ---------------- 外部源 ----------------
    ("s_tx", "src", 2, "腾讯 qt / ifzq", "snapshot.mjs 首选源; 子链闸批量取价; 约 1.6 次/秒 6 分钟封"),
    ("s_sina", "src", 2, "新浪 hq.sinajs.cn", "3 秒盘口 / 面板 / 竞价 / snapshot 兜底; 单次请求约 280 只封顶; 10/20 晚压测中"),
    ("s_em", "src", 0, "东财 push2 / clist", "scan.mjs 六榜 / 板块榜, 中证2000; ~25 次/5 分钟封, em_clist 连续熔断"),

    # ---------------- 采集器 ----------------
    ("c_panel", "col", 0, "collect_panel.py", "每分钟: 日经 / KOSPI / A50 连续 / 小纳指 / 上证 / 中证2000 / 国证2000 / 创业板 / 恒生科技 / 纳指ETF(溢价率 / 停牌)"),
    ("c_auction", "col", 1, "collect_auction.py", "竞价每 15 秒, 关注集约 300 只 + 指数; 9:20 前可撤段 / 9:20 后不可撤段 / 9:25 撮合"),
    ("c_book", "col", 2, "collect_book.py(3 秒盘口)", "09:14~15:01 每 3 秒 1 次批量, 约 46 只(做T 标的 + 各链持仓 / 挂单 / 计划单 + 用户持仓, 每 10 分钟刷新名单, 封顶 60)"),
    ("c_openlive", "col", 2, "open_live.py(10/20 新)", "09:25~10:30 每分钟机械判市况; 必判 09:31/09:45/10:00/10:30 + 触发 ①~④; 滞回 + 2 分钟确认"),
    ("c_market", "col", 3, "收盘采集(Java + collect_*.py)", "kline_day / kline_minute(关注集) / open15(全市场 09:31~09:45) / 竞价存档"),
    ("c_ind", "col", 4, "indicators_db.py / topology.py", "check md 晚间跑: 全市场三态 / 箱体 / EMA / ATR; 拓扑邻居"),
    ("c_kline_cache", "col", 4, "refresh_daily_cache.mjs(10/20 新)", "每晚 check md 指标之前, 读本地行情库把日线缓存整体补到最新(零网络); 原先只按需补导致大面积过期"),

    # ---------------- 数据 ----------------
    ("d_md", "data", 0, "md/<季>/<日>.md", "早报 / 加红电报(全天追加) / 当前持仓(用户写股名) / 导师 tzzb 小节 / 天哥 T-1 评盘"),
    ("d_global", "data", 0, "market/<日>/global_kline.jsonl", "隔夜外盘收盘"),
    ("d_panel", "data", 0, "market/<日>/panel_minute.jsonl", "多指数面板每分钟一行; 10/21 起才有 A 股指数(10/20 15:08 才上线)"),
    ("d_auction", "data", 1, "market/<日>/auction_live_open.json", "竞价过程汇总(原子重写); 事实包「集合竞价」节只给 0925~0959 时段"),
    ("d_book", "data", 2, "market/<日>/book_snap.jsonl", "3 秒五档; 10/20 起: 撮合按路径读、候选附分时一句话(cand_snap)、开盘实况读; ⚠ 名单每 10 分钟刷新, 候选票下单后才进名单(想法 A 待定)"),
    ("d_openlive", "data", 2, "market/<日>/open_live.json", "10/20 新: 判定记录 / 当前结论 / 结论变化"),
    ("d_kday", "data", 3, "market/<日>/kline_day.jsonl", "全市场当日日线(完整, 有 preClose / 涨跌停价); ⚠ 多数消费方不读它"),
    ("d_kmin", "data", 3, "market/<日>/kline_minute.jsonl", "关注集分钟线(收盘后); 分钟回放 / 子链闸 as-of 用"),
    ("d_ind", "data", 4, "market/<日>/indicators.jsonl", "三态 / 箱体 / ATR / EMA; 次日事实包读前一交易日这份"),
    ("d_hist", "data", 4, "market/history/kline_day/", "历史日线, ⚠ 停在 10/09(之后靠每日 kline_day 补)"),
    ("d_kcache", "data", 2, "quotes/daily/<code>.json 日线缓存", "10/20 晚整体补齐(1473/1570 到 10/20, 原只有 16 只), 之后每晚刷新; 读它的: matcher 前收兜底 / EOD 历史日 / report / daily_digest / settle / 振幅中位(run_chain / 子链闸 / t_event / open_live)"),
    ("d_snapcache", "data", 2, "quotes/live/snap_cache.json", "snapshot.mjs 的读穿缓存(盘中 20 秒 / 盘外 10 分钟); 只有 snapshot.mjs 直接读写, 撮合 / 候选价格锚 / 日终 / 事实包关注票都经 snapshot.mjs 间接用它; 不写进日线缓存(盘中价不是完整日线)"),
    ("d_tzzb", "data", 3, "tzzb/a658/(nav_daily / day_positions / change_bs)", "真人账本; 下限 / 单票上限 / 导师不动闸 / 基线 / 拟人审 / 07 的真人对照都读它"),
    ("d_persona", "data", 0, "skills/a658-skill/persona/", "rules.md / profile.md / cases.md / fingerprint.md(晚间蒸馏更新; 链 0915 前按版本锁)"),
    ("d_ruletags", "data", 0, "paper/rule_tags/a658.json", "规则方向(买 / 卖 / 持有 / 双向) + 机械触发; 下限收窄的买规则闸读它"),
    ("d_params", "data", 0, "params.yaml + chain_flags.txt", "动态仓位 / 子链闸阈值 / 因子权重 / 各开关"),
    ("d_facts", "data", 0, "paper/facts/<日>/<时段>/facts.md", "16 条链共享的事实包(每时段一份, 约 48KB); 0915 版 08:05~08:08 生成"),
    ("d_candsnap", "data", 0, "results/.../cand_snap.md", "04 之后对候选票取的价格锚(单时间点快照) + 10/20 起末尾附每只候选的分时一句话(不在盘口名单的写无)"),
    ("d_steps", "data", 0, "results/a658_chain/live-<日>/01~06", "各步产物 + contract; 子链在 slots/<时段>/; 10/20 0915: 01 08:08 / 02 08:09 / 03 08:11~08:14 / 04 08:16 / 05 08:17 / 06 08:19"),
    ("d_plans", "data", 2, "paper/plans/<日>_A-a658.md", "一行一单(时间 | 账本 | 方向 | 代码 | 价 | 量 | 有效期 | 锚 | 条件 | 理由)"),

    # ---------------- 动作 ----------------
    ("a_facts", "act", 0, "facts.mjs --slot", "读 md / 指标 / 账本 / state_digest / 龙虎榜 / 真人持仓 / 竞价 / 面板 / 开盘实况 / 箱体位置(10/20 新) + 现场拉 scan 六榜 / 期货 → facts.md; 约 3 分钟"),
    ("a_scan", "act", 0, "scan.mjs 六榜", "涨幅 / 跌幅(东财→新浪→东财延迟) · 连板梯队(东财涨停池→财联社→md 电报) · 跌停(东财→新浪跌幅榜近似) · 板块(东财→新浪) · 次新区间跌幅(东财→东财延迟→本地库 + 新浪实时价; 10/20 盘中缺 4/12 个时段, 10/21 起盘中用新浪批量现价自算)"),
    ("a_snapshot", "act", 2, "snapshot.mjs", "多源快照: 腾讯 → 东财 → 新浪(北交所 东财 → 新浪); 残缺换源, 全灭显式报错"),
    ("a_chain", "act", 0, "run_chain.py(驱动器)", "pos_constraints → ledger_prepare(下限收窄) → 子链闸(子链才有) → 01~06 各一次 claude -p(每步 1~3 分钟) → 校验 → 拟人审 → plans"),
    ("a_gate", "act", 2, "子链零 token 闸 a~f", "上一次跑过的时段以来: a 账本事件 / b 关注票动 ≥min(1.5%, 半个振幅) / c 指数动 ≥0.8pt / d 电报命中 / e 强制时段 / f 开盘实况结论变(10/20 新); 都不成立 = 跳过不调模型"),
    ("a_import", "act", 2, "matcher.mjs --import", "plans 行 → 账本挂单; 格式校验 + 拒落账闸"),
    ("a_match", "act", 2, "matcher.mjs --once", "每分钟: snapMany 取现价 → 哨兵(锚偏离或追价上限 chase_cap / 失效线 / 止损 / 涨停排板) → 改单(⚠ 挂出 N 分钟未成就机械向现价靠一半: 10/12 起 29 张只成交 11 张, 买单成交后到收盘中位 −0.70%, 待改成按事实改价) → 成交落账 + 哈希链; 10/20 起读 3 秒盘口价格路径撮合(MATCH_PATH)"),
    ("a_eod", "act", 3, "matcher.mjs --eod", "废单核销 → nav(当日用实时快照收盘; 历史日读日线缓存) → state_digest → report"),
    ("a_settle", "act", 3, "settle_decisions.py", "按持有期结算决策日志; 读 kline_day + 日线缓存"),
    ("a_07", "act", 3, "07 复盘(run_chain review)", "读 01~06 / 账本 / md / 真人账本 + 10/21 起注入归因推导链和 07 素材包(当日行情 / 导师腿 / 规则 + 相似规则 / cases 错题 / lessons / 多日结算) → 07_review + lessons + root_causes; 结论按票写回决策记忆(代替原 15:50 LLM 反思)"),
    ("a_report", "act", 4, "report.mjs / daily_digest.mjs / real_vs_chain.mjs", "人看的汇总; report / daily_digest 读日线缓存(10/20 晚补齐并每晚刷新, 原先持仓收盘停在 10/16)"),
    ("a_mix", "act", 2, "mix_plans.py(混合账本)", "按各链权重合成跟单; 市况 10/20 起读对照组最新 02(R4) / 子链 02(R5)"),
    ("a_distill", "act", 4, "晚间蒸馏 / collect_lessons", "07 lessons + 真人新操作 → persona 规则(次日 0915 生效)"),

    # ---------------- 规则 / 闸 ----------------
    ("r_floor", "rule", 0, "总仓下限 + 收窄(10/20)", "A658 真人近 5 日收盘仓位中位 96%×0.8 → 75%; 10/20 起: 连续空仓 < 真人最长 3 天 → 软下限 + 新开仓须引方向=买的规则"),
    ("r_cap", "rule", 0, "单票上限 / 新开仓大小", "真人单票最大仓位 P75; 新开仓 ≥ 真人单票中位 53%×75%"),
    ("r_idle", "rule", 0, "导师不动闸 / 追仓豁免", "低频导师基线不出手 → 不许开新仓; 链仓位比真人昨收低 ≥30% → 豁免(⚠ 真人账本滞后时用的是旧仓位)"),
    ("r_mimic", "rule", 0, "拟人审", "只审像不像本导师(仓位 / 持股数 / 时段 / 能力圈 / 持有预期); 不像退回 06 一次, 再不过降级照发"),
    ("r_evidence", "rule", 0, "02 因子表 R1(10/20)", "evidence 6 因子; stance 和因子多数方向相反 → 回炉一次"),
    ("r_reject", "rule", 2, "拒落账闸", "挂价偏离前收超板限 → 不进账本"),
    ("r_anchor", "rule", 2, "锚偏离闸(3%)", "链自报锚 vs 前收和现价都偏 >3% → 作废; 10/12 起作废 6 单若成交合计 −9711"),
    ("r_cage", "rule", 2, "价格笼子 ±2% / 涨停排板 / T+1", "连续竞价新单吃 ±2% 笼子; 涨停价挂单封板不成交; 当日买的不能卖"),
    ("r_reprice", "rule", 2, "改单(reprice)", "⚠ 挂出 N 分钟未成交 → 机械向现价靠一半(只一次), 不看任何事实; 待改"),

    # ---------------- 产物 ----------------
    ("o_book", "out", 2, "paper/books/A-a658.json", "现金 / 持仓 / 挂单 / 成交 / nav / 哈希链"),
    ("o_nav", "out", 3, "nav/ + state_digest.md", "日终净值; state_digest 给次日事实包「昨日账本状态」"),
    ("o_07", "out", 3, "07_review.md + lessons", "复盘 + 教训(进蒸馏)"),
    ("o_dec", "out", 3, "decisions/a658.jsonl + settle", "决策日志与结算(按持有期)"),

    # ---------------- 出口 ----------------
    ("v_report", "view", 4, "report.html", "收益曲线 / 持仓 / 成交"),
    ("v_wx", "view", 4, "微信日报(hermes)", "daily_digest + real_vs_chain 摘要"),
]

# (起, 止, 关系, 说明)  关系: 触发 / 读 / 写 / 约束 / 影响
E = [
    ("t_md", "d_md", "写", "00:00 建骨架"), ("t_cls", "d_md", "写", "加红电报追加"), ("t_zaobao", "d_md", "写", "早报"),
    ("t_global", "d_global", "写", ""), ("t_panel", "c_panel", "触发", "07:30 起每分钟"), ("c_panel", "s_sina", "读", "新浪批量(中证2000 走东财, 纳指ETF 走腾讯)"),
    ("c_panel", "d_panel", "写", ""), ("t_0915", "a_chain", "触发", "08:05"),
    ("a_chain", "a_facts", "触发", "开跑先生成共享事实包(16 链共用一份)"),
    ("a_facts", "d_md", "读", "早报 / 电报 / 持仓"), ("a_facts", "d_ind", "读", "前一交易日指标"), ("a_facts", "d_global", "读", ""),
    ("a_facts", "d_panel", "读", "面板过程"), ("a_facts", "d_auction", "读", "0925~0959 全量过程; 10/20 起 10:00 后每个时段给精简回顾(关注票每只一行)"), ("a_facts", "d_openlive", "读", "0927~1030 时段(10/20 新)"),
    ("a_facts", "d_tzzb", "读", "导师本人持仓"), ("a_facts", "o_nav", "读", "state_digest 昨日账本状态"), ("a_facts", "a_scan", "触发", ""),
    ("a_scan", "s_em", "读", "六榜 / 板块榜"), ("a_facts", "d_kcache", "读", "关注票日线"), ("a_facts", "d_hist", "读", "箱体位置表 60 日"), ("a_facts", "d_kday", "读", "箱体位置表补 10/09 后"),
    ("a_facts", "d_facts", "写", "facts.md / facts.json"),
    ("a_chain", "d_facts", "读", "01 起各步"), ("a_chain", "d_persona", "读", "画像 / 规则 / 案例(按 0915 前版本锁)"), ("a_chain", "d_params", "读", ""),
    ("a_chain", "d_tzzb", "读", "下限 / 单票上限 / 基线 / 候选池"), ("a_chain", "o_book", "读", "持仓 / 挂单 / 现金"), ("a_chain", "d_kcache", "读", "振幅中位(失效线放宽)"),
    ("a_chain", "a_snapshot", "触发", "04 后取候选价格锚"), ("a_snapshot", "s_tx", "读", "首选"), ("a_snapshot", "s_sina", "读", "兜底"), ("a_snapshot", "d_snapcache", "读", "读穿缓存: 盘中 20 秒内直接用(16 链 + 每分钟撮合合用一次请求)"), ("a_snapshot", "d_snapcache", "写", "缺的现取后写回"),
    ("a_snapshot", "d_candsnap", "写", "单时间点快照"), ("a_chain", "d_candsnap", "读", "06 定锚"), ("a_chain", "d_book", "读", "cand_snap 末尾分时一句话(10/20 新)"), ("a_chain", "d_steps", "写", "01~06 产物"),
    ("r_floor", "a_chain", "约束", "06 校验"), ("r_cap", "a_chain", "约束", "06 校验"), ("r_idle", "a_chain", "约束", "04 / 06"), ("r_mimic", "a_chain", "约束", "06 之后"),
    ("r_evidence", "a_chain", "约束", "02 校验"), ("r_floor", "d_ruletags", "读", "买规则方向"), ("r_floor", "d_tzzb", "读", "真人仓位 / 最长空仓段"), ("r_idle", "d_tzzb", "读", "真人昨收仓位(⚠ 滞后)"),
    ("a_chain", "d_plans", "写", "06 contract → plans 行"), ("a_chain", "a_import", "触发", "写完 plans 立刻 import"),
    ("a_import", "d_plans", "读", ""), ("r_reject", "a_import", "约束", ""), ("a_import", "o_book", "写", "挂单"),
    ("t_auction", "c_auction", "触发", ""), ("c_auction", "s_sina", "读", ""), ("c_auction", "d_auction", "写", ""),
    ("t_0927", "a_chain", "触发", "子链"), ("t_1030", "a_chain", "触发", "子链"), ("t_1400", "a_chain", "触发", "子链"), ("t_1455", "a_chain", "触发", "子链"),
    ("a_chain", "a_gate", "触发", "子链先过闸"), ("a_gate", "s_tx", "读", "批量取价(16 链共享缓存)"), ("a_gate", "d_facts", "读", "本时段 watch / 电报"), ("a_gate", "d_openlive", "读", "条件 f"),
    ("a_gate", "d_kcache", "读", "振幅中位"),
    ("t_mix", "c_book", "触发", "--ensure"), ("t_mix", "c_openlive", "触发", "--ensure"), ("t_mix", "a_mix", "触发", ""), ("c_book", "s_sina", "读", "每 3 秒 1 次"),
    ("c_book", "o_book", "读", "名单: 持仓 / 挂单"), ("c_book", "d_plans", "读", "名单: 计划单"), ("c_book", "d_book", "写", ""),
    ("c_openlive", "d_panel", "读", ""), ("c_openlive", "d_book", "读", "关注票"), ("c_openlive", "d_auction", "读", ""), ("c_openlive", "d_ind", "读", "ATR"), ("c_openlive", "d_openlive", "写", ""),
    ("a_mix", "d_steps", "读", "各链 02 市况(R4 / R5)"), ("a_mix", "a_import", "触发", "A-mix 系列"),
    ("t_match", "a_match", "触发", "每分钟"), ("a_match", "o_book", "读", "挂单"), ("a_match", "a_snapshot", "触发", "snapMany 现价"), ("a_match", "d_book", "读", "价格路径撮合 + 竞价T 卖价(10/20 新)"),
    ("a_match", "d_kcache", "读", "前收兜底"), ("a_match", "d_kmin", "读", "分钟回放模式"),
    ("r_anchor", "a_match", "约束", ""), ("r_cage", "a_match", "约束", ""), ("r_reprice", "a_match", "约束", ""), ("a_match", "o_book", "写", "成交 / 撤单 / 改单"),
    ("t_eod", "a_eod", "触发", "15:05"), ("a_eod", "o_book", "读", ""), ("a_eod", "a_snapshot", "触发", "当日收盘价"), ("a_eod", "d_kcache", "读", "历史日"), ("a_eod", "o_nav", "写", ""),
    ("t_market", "c_market", "触发", ""), ("c_market", "d_kday", "写", ""), ("c_market", "d_kmin", "写", ""),
    ("t_checkmd", "c_ind", "触发", ""), ("c_ind", "d_kday", "读", ""), ("c_ind", "d_ind", "写", "次日事实包用"),
    ("t_checkmd", "c_kline_cache", "触发", "每晚, 指标之前"), ("c_kline_cache", "d_kday", "读", "经行情库(kline_day 表)"), ("c_kline_cache", "d_kcache", "写", "整体补到最新"),
    ("t_tzzb", "d_tzzb", "写", ""), ("t_07", "a_07", "触发", ""), ("a_07", "d_steps", "读", ""), ("a_07", "o_book", "读", ""), ("a_07", "d_tzzb", "读", "真人当日"), ("a_07", "d_md", "读", "收评"),
    ("a_07", "o_07", "写", ""), ("a_07", "o_dec", "读", "07 素材包 ⑧ 多日结算"), ("a_07", "o_dec", "写", "root_causes / lessons 按票写回反思记忆"), ("t_settle", "a_settle", "触发", ""), ("a_settle", "d_kday", "读", ""), ("a_settle", "d_kcache", "读", ""), ("a_settle", "o_dec", "写", ""),
    ("t_checkmd", "a_report", "触发", ""), ("t_checkmd", "a_distill", "触发", ""), ("a_report", "o_book", "读", ""), ("a_report", "d_tzzb", "读", ""), ("a_report", "d_kcache", "读", "持仓收盘(10/20 起每晚刷新)"),
    ("a_report", "v_report", "写", ""), ("a_report", "v_wx", "写", ""), ("a_distill", "o_07", "读", "lessons"), ("a_distill", "d_tzzb", "读", "真人新操作"), ("a_distill", "d_persona", "写", "次日 0915 生效"),
    ("o_nav", "a_facts", "影响", "state_digest 被次日 08:05 的 0915 事实包读(nav 本身不读事实包)"), ("d_persona", "d_ruletags", "影响", "rule_tags --build"),
]


def scan_nodes():
    """docs/graph/asset_scan.json(asset_scan.py 静态扫描) → 每个产物一个节点; 没有扫描结果 = 空"""
    f = HERE / "asset_scan.json"
    if not f.exists():
        return []
    A = json.loads(f.read_text(encoding="utf-8"))["assets"]
    order = {"无人读": 0, "只给报表/采集": 1, "进决策": 2}
    A.sort(key=lambda a: (order[a["level"]], a["where"]))
    mark = {"无人读": "⛔ 无人读", "只给报表/采集": "◐ 只给报表", "进决策": "✓ 进决策"}
    out = []
    for i, a in enumerate(A):
        nm = lambda xs: "、".join(Path(x).name for x in xs) or "无"
        desc = (f"{a['where']} · 生产: {nm(a['writers'])} · 决策层读方: {nm(a['decision_readers'])} · 其他读方({len(a['readers']) - len(a['decision_readers'])}): "
                f"{nm([r for r in a['readers'] if r not in a['decision_readers']][:8])}" + (" · ⛔ 有人写没人读" if a["level"] == "无人读" else ""))
        out.append((f"scan_{i}", "scan", i % len(PH), f"{mark[a['level']]} · {a['name']}", desc, a["level"]))
    return out


def build():
    global N
    sc = scan_nodes()
    N = [n for n in N if n[1] != "scan"] + [n[:5] for n in sc]
    levels = {n[0]: n[5] for n in sc}
    ids = {n[0] for n in N}
    bad = [e for e in E if e[0] not in ids or e[1] not in ids]
    assert not bad, f"边指向不存在的节点: {bad}"
    lanes = list(TY)
    pos, cnt = {}, {}
    for nid, ty, ph, *_ in N:
        k = (ph, ty)
        cnt[k] = cnt.get(k, 0) + 1
    lane_h = {ty: max(cnt.get((ph, ty), 0) for ph in range(len(PH))) for ty in lanes}
    y0, y = {}, 60
    for ty in lanes:
        y0[ty] = y
        y += max(1, lane_h[ty]) * 46 + 30
    H, W, CW = y + 20, 260 + len(PH) * 300, 300
    seen = {}
    for nid, ty, ph, *_ in N:
        k = (ph, ty)
        i = seen.get(k, 0)
        seen[k] = i + 1
        pos[nid] = (200 + ph * CW + 20, y0[ty] + i * 46)
    rd = {n[0]: [e[0] for e in E if e[2] == "读" and e[1] == n[0]] for n in N}
    wr = {n[0]: [e[0] for e in E if e[2] == "写" and e[1] == n[0]] for n in N}

    def lvl(n):
        if n[1] == "scan":
            return levels.get(n[0])
        if n[1] in ("data", "out"):
            return "无人读" if wr[n[0]] and not rd[n[0]] else "有读方"
        return None
    data = {"nodes": [{"id": n[0], "ty": n[1], "ph": n[2], "name": n[3], "desc": n[4], "x": pos[n[0]][0], "y": pos[n[0]][1],
                       "nread": len(rd[n[0]]) if n[1] in ("data", "out") else None, "lvl": lvl(n)} for n in N],
            "edges": [{"s": a, "t": b, "rel": r, "note": nt} for a, b, r, nt in E], "lanes": [{"ty": t, "name": TY[t][0], "color": TY[t][1], "y": y0[t], "h": max(1, lane_h[t]) * 46 + 10} for t in lanes],
            "phases": PH, "W": W, "H": H, "CW": CW}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = HERE / "paper_line_a658.html"
    out.write_text(html, encoding="utf-8")
    print(f"写出 {out}: 节点 {len(N)} / 边 {len(E)}")


TEMPLATE = r"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>paper 线关系图 · A658(10/20)</title>
<style>
body{margin:0;font:13px/1.45 "Microsoft YaHei",sans-serif;background:#0b1120;color:#e2e8f0}
#bar{position:sticky;top:0;z-index:5;background:#111827;border-bottom:1px solid #1f2937;padding:8px 12px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
#bar label{cursor:pointer} #wrap{display:flex} #canvas{flex:1;overflow:auto;height:calc(100vh - 46px)}
#side{width:380px;border-left:1px solid #1f2937;background:#111827;padding:12px;overflow:auto;height:calc(100vh - 70px)}
.node rect{rx:6;ry:6;stroke-width:1.5;fill:#1e293b;cursor:pointer} .node text{font-size:12px;pointer-events:none;fill:#e2e8f0}
.node .badge{font-size:11px;font-weight:bold} .edge{fill:none;stroke-width:1.2;opacity:.45} .dim{opacity:.07!important} .hi{opacity:1!important;stroke-width:2.6!important}
.lane{fill-opacity:.07} .lanetxt{font-weight:bold;font-size:13px} .ph{font-weight:bold;fill:#cbd5e1}
.warn rect{stroke:#f87171!important;stroke-dasharray:4 2} .orphan rect{fill:#3f1d1d!important;stroke:#ef4444!important;stroke-width:2.4!important}
.report rect{fill:#3a2f12!important} h3{margin:4px 0 8px;color:#f8fafc} .k{color:#94a3b8} li{margin:3px 0} b{color:#f1f5f9}
</style>
<div id="bar"><b>paper 线关系图 · A658(10/20 实测时刻)</b><span class="k">点节点 = 高亮它的上下游; 再点空白取消</span>
<span id="rels"></span><label><input type="checkbox" id="onlywarn"> 只看 ⚠ 已知问题</label><label><input type="checkbox" id="onlyorphan"> 只看 ⛔ 无人读</label>
<span class="k">数据节点右上角 = 读方个数(<span style="color:#ef4444">读×0 = 有人写没人读</span>); 最下面一行 = 全项目产物自动扫描(✓ 进决策 / ◐ 只给报表 / ⛔ 无人读)</span></div>
<div id="wrap"><div id="canvas"><svg id="svg"></svg></div><div id="side"><h3>说明</h3><div class="k">节点按"类型(行) × 时间阶段(列)"摆放。边: 触发(紫) / 读(蓝) / 写(绿) / 约束(红) / 影响(灰虚线)。带 ⚠ 的节点是已知问题。</div></div></div>
<script>
const D=__DATA__;const NS="http://www.w3.org/2000/svg";const svg=document.getElementById("svg");
svg.setAttribute("width",D.W);svg.setAttribute("height",D.H);
const RC={"触发":"#a78bfa","读":"#60a5fa","写":"#4ade80","约束":"#f87171","影响":"#94a3b8"};
const el=(t,a,p)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);(p||svg).appendChild(e);return e};
const tc=TY=>D.lanes.find(l=>l.ty===TY).color;
D.lanes.forEach(l=>{el("rect",{x:0,y:l.y-8,width:D.W,height:l.h,fill:l.color,class:"lane"});const t=el("text",{x:10,y:l.y+16,fill:l.color,class:"lanetxt"});t.textContent=l.name});
D.phases.forEach((p,i)=>{const t=el("text",{x:200+i*D.CW+20,y:36,class:"ph"});t.textContent=p;el("line",{x1:200+i*D.CW+8,y1:44,x2:200+i*D.CW+8,y2:D.H,stroke:"#334155","stroke-dasharray":"3 4"})});
const byId={};D.nodes.forEach(n=>byId[n.id]=n);const BW=250,BH=34;
const eg=el("g",{});const edges=D.edges.map(e=>{const a=byId[e.s],b=byId[e.t];const x1=a.x+BW,y1=a.y+BH/2,x2=b.x,y2=b.y+BH/2;
 const sx=x2>=x1?x1:a.x, ex=x2>=x1?x2:b.x+BW; const mx=(sx+ex)/2;
 const p=el("path",{d:`M${sx},${y1} C${mx},${y1} ${mx},${y2} ${ex},${y2}`,stroke:RC[e.rel],class:"edge","stroke-dasharray":e.rel==="影响"?"5 4":"", "marker-end":""},eg);
 const tt=el("title",{},p);tt.textContent=`${a.name} —${e.rel}→ ${b.name}${e.note?"  ("+e.note+")":""}`;return {e,p}});
const ng=el("g",{});const nodes=D.nodes.map(n=>{const cls="node"+(n.desc.includes("⚠")?" warn":"")+(n.lvl==="无人读"?" orphan":"")+(n.lvl==="只给报表/采集"?" report":"");
 const g=el("g",{class:cls,transform:`translate(${n.x},${n.y})`},ng);
 el("rect",{width:BW,height:BH,stroke:tc(n.ty)},g);const t=el("text",{x:8,y:21},g);const nm=(n.desc.includes("⚠")&&n.ty!=="scan"?"⚠ ":"")+n.name;t.textContent=nm.length>30?nm.slice(0,29)+"…":nm;
 if(n.nread!==null&&n.nread!==undefined){const b=el("text",{x:BW-6,y:13,"text-anchor":"end",class:"badge",fill:n.lvl==="无人读"?"#ef4444":"#60a5fa"},g);b.textContent="读×"+n.nread}
 g.addEventListener("click",ev=>{ev.stopPropagation();focus(n.id)});return {n,g}});
const rels=document.getElementById("rels");Object.entries(RC).forEach(([k,c])=>{const s=document.createElement("label");s.innerHTML=`<input type=checkbox checked data-r="${k}"> <span style="color:${c}">■</span>${k}`;rels.appendChild(s)});
rels.addEventListener("change",apply);document.getElementById("onlywarn").addEventListener("change",apply);document.getElementById("onlyorphan").addEventListener("change",apply);
let cur=null;svg.addEventListener("click",()=>{cur=null;apply();side(null)});
function focus(id){cur=id;apply();side(id)}
function apply(){const on=new Set([...rels.querySelectorAll("input:checked")].map(x=>x.dataset.r));const ow=document.getElementById("onlywarn").checked,oo=document.getElementById("onlyorphan").checked;
 const nb=new Set();if(cur){nb.add(cur);edges.forEach(({e})=>{if(!on.has(e.rel))return;if(e.s===cur)nb.add(e.t);if(e.t===cur)nb.add(e.s)})}
 edges.forEach(({e,p})=>{const vis=on.has(e.rel);p.style.display=vis?"":"none";p.classList.toggle("hi",!!cur&&(e.s===cur||e.t===cur));p.classList.toggle("dim",!!cur&&!(e.s===cur||e.t===cur))});
 nodes.forEach(({n,g})=>{const w=n.desc.includes("⚠");g.classList.toggle("dim",(cur&&!nb.has(n.id))||(ow&&!w)||(oo&&n.lvl!=="无人读"))})}
function side(id){const s=document.getElementById("side");if(!id){s.innerHTML='<h3>说明</h3><div class="k">点任意节点看它的动作 / 规则 / 输入 / 输出 / 时刻 / 已知问题。</div>';return}
 const n=byId[id];const ins=D.edges.filter(e=>e.t===id),outs=D.edges.filter(e=>e.s===id);
 const li=(arr,f)=>arr.map(e=>`<li><span style="color:${RC[e.rel]}">${e.rel}</span> ${f(e)}${e.note?` <span class=k>(${e.note})</span>`:""}</li>`).join("")||"<li class=k>无</li>";
 s.innerHTML=`<h3>${n.name}</h3><div class=k>${D.lanes.find(l=>l.ty===n.ty).name} · ${D.phases[n.ph]}</div><p>${n.desc}</p>
 ${n.nread!==null&&n.nread!==undefined?`<p><b>读方 ${n.nread} 个</b>${n.lvl==="无人读"?' <span style="color:#ef4444">⛔ 有人写没人读</span>':""}: ${D.edges.filter(e=>e.t===id&&e.rel==="读").map(e=>byId[e.s].name).join("、")||"无"}</p>`:""}
 <b>上游(谁触发 / 约束它, 它读什么)</b><ul>${li(ins,e=>byId[e.s].name+" →")}</ul><b>下游(它触发 / 写 / 约束 / 读谁)</b><ul>${li(outs,e=>"→ "+byId[e.t].name)}</ul>`}
side(null);
</script></html>"""

if __name__ == "__main__":
    build()
