# K 线 / 威科夫 / 周期 学习目录(skills/market-skill/references/kline_study)

> 2026-10-24 建。学习 agent 产出, **全部是草稿, 未接入实盘线**。总报告见 `docs/research/kline_study_20261024.md`。

## 书(16 本, 含用户中途补充 10 本)
| 文件 | 材料 | 读的程度 | 一句话 |
|---|---|---|---|
| book_wyckoff_meng.md | 2029《威科夫操盘法》孟洪涛 | **全文精读**, 看图 ~15 张 | 威科夫事件/阶段定义的主依据 |
| book_vpa_coulling.md | 6530《量价分析》库林 | 第 4~6 章精读, 7~9 章要点 | "确认 vs 异常"、孤立支点定箱体、突破量能 |
| book_nison_new.md | 7766《日本蜡烛图技术新解》尼森 | 全文 | 位置比形态重要; 窗口; 乖离率; 三线反向/砖形/钥匙图 |
| book_morris.md | 6632《蜡烛图精解》第 3 版 + 9960 典藏版差异 | 第 1~2、5~11 章精读, 3~4 章识别标准 | 可编程阈值 + 70 万样本统计(多数≈50%) |
| book_marks_cycle.md | 4437《周期》马克斯 | 1~3、7、8、12~14 章 | 周期位置改变概率分布; 心理钟摆; 市场温度 |
| book_natenberg_volatility.md | 671《期权波动率与定价》 | 第 4、14、18 章 | 日σ=年化/16、波动率均值回复与圆锥、厚尾 |
| book_market_sense.md | 6724《市场真相》施瓦格 | 第 2、6~8 章 | 市场无效但难战胜; 回测与后见之明陷阱 |
| book_quant_strategy.md | 1800《量化投资策略》托托里罗(10/24 晚补) | 第 1~2、9 章精读, 其余读小结 | 五分位因子检验框架; 价格动量因子(52 周范围/7 月 RS/28 周 RSI) |
| book_python_finance.md | 7515《Python 金融大数据分析》希尔皮斯科(10/24 晚补) | 第 3、6、10、11 章精读, 语法/绘图/Web 等只看标题 | 厚尾/VaR/波动聚集; 据此复核显著性口径与做 T 振幅 |
| book_zero_quant.md | 7388《零起点 Python 大数据与量化交易》 | 第 2、4~10 章(8~10 章 10/24 晚补读) | 回测口径对照; 书中海龟/KDJ/RSI/MACD 规则放进我们口径回测 |
| book_caopanshou.md | 721《操盘手Ⅰ》花荣(小说) | 交易相关段落 | 主力如何制造 K 线和量 |
| book_elliott_wave.md | 7330《艾略特波浪理论》(10/25 主会话读, 看图 11 张) | 第一部分 1~7 章精读 + 第二部分通道 / 调整 / 三角形 / 延长浪 / 时间价格 + 交替规则 | 五浪三浪 + 通道线 + 调整形态预示强度; 可机械化的是 zigzag 分段 / 通道 / 调整量递减, 数浪级别主观 |
| book_dorsey_five_rules.md | 295《股市真规则》 | 前 2 章 | 价值投资视角, 作零假设 |
| book_flash_boys.md | 6738《高频交易员》 | 要点 | 幻影流动性/暗池 |

### 第二批(10/25, 9 份笔记 / 11 本书; 总报告 `docs/research/books_20261025.md`, 可回测假设 H01~H28)
| 文件 | 材料 | 读的程度 | 一句话 |
|---|---|---|---|
| book_aldridge_hft.md | 7102《高频交易（原书第 2 版）》奥尔德里奇 | 第 3、4、9~12 章精读 | OFI / 交易方向判别 / "成交后报价回不回来"区分有无信息, 落到 3 秒五档口径 |
| book_kirkpatrick_vol1.md | 10028《经典技术分析（第 3 版）》**上册**(下册缺, 不再找) | 第 8、13 章精读 | 突破五种过滤(推荐 ATR)、吊灯 / 时间止损、市场宽度指标(参数须在 A 股重估) |
| book_elder.md | 177《以交易为生》+ 7607《走进我的交易室》+ 6748《以交易为生Ⅱ》埃尔德 | 三重滤网 / 脉冲 / 止损章精读 | 顺大势逆小势的三重滤网; 脉冲红 bar 禁买; 止损放精确前低、安全区 / 尼克止损公式 |
| book_lingbo_probability.md | 6918《概率游戏（升级版）》凌波 | 第二、三章全文 | A 股 T+1 本土短线常识(尾盘买、回踩 MA10、假阴线), 全书无统计 |
| book_heima_boduan.md | 6860《黑马波段操盘术（升级版）》凌波 | 第二、四、六、八章精读 | MA10"黑马线"完整用法 + 唯一带回测表的 A 股系统(2 只自选票, 可信度低, 待全市场复现) |
| book_wangning_violent_k.md | 6351《暴力K线擒大牛》王宁 | 定义 + 十种组合 + 十种顶部 | A 股游资形态词典(点头送客 / 空中飞人 / 横盘突击 / 涨停基因), 只有赢家案例 |
| book_murphy_intermarket.md | 6228《跨市场交易策略（典藏版）》墨菲 | 第 1、16 章精读 | 跨市场 = 滚动相关 + 比率线, 关系会变; 对短线只用隔夜外围和风格比率 |
| book_edwards_magee.md | 2818《股市趋势技术分析（第 10 版）》爱德华兹 & 迈吉 | 约 1/3(形态 / 缺口 / 止损 / 测算) | 3% 收盘突破、形态高度作最小目标; "缺口必补"是迷信, 可直接检验 |
| book_clenow_trend.md | 3552《趋势交易》克列诺 | 第 3~5 章 | 突破 + 均线过滤 + 3ATR 追踪持有到止损、ATR 定仓、参数平原 |
## 代码项目(5 个, 只读)
| 文件 | 项目 |
|---|---|
| code_wyckoffpro.md | WyckoffPro: 120 日分位自适应阈值 + 13 事件似然分 + 11 阶段 FSM |
| code_wyckoff_trading_agent.md | WyckoffTradingAgent: 摆动点箱体、A 股涨跌停处理、带成本的前瞻检验 |
| code_kronos_charts.md | Kronos(K 线基础模型) / YYKline / KChartView(只有绘图与指标口径) |
## 网页(4 个)
全部打不开(WebFetch 被域名安全校验拦截), 见 open_questions.md。

## 产出
- `definitions.md` 机械定义草案(箱体分日线/分钟级; K 系列 8 个、W 系列 9 个)
- `backtest.md` 回测结论(§七 为第二轮); 原始表 `backtest_tables.md` / `backtest_extra.md` / `backtest_minute.md` / `backtest_factor.md`(动量因子五分位) / `backtest_zwquant.md`(零起点书中规则) / `stat_inference.md`(显著性口径复核, §八) / `stat_tails_amplitude.md`(尾部/VaR/做 T 振幅)
- `open_questions.md` 冲突、不确定、读不到的材料、待拍板事项
- `img/` 21 张代表图(含《Python 金融大数据分析》qq 图与 VaR 对比图; 含《量化投资策略》图 2.3 回测模板、图 9.1 计算周期扫描、图 9.9 52 周范围滚动超额)(威科夫结构/Spring 三类/派发、尼森弹簧线/十字位置/迭创新高、库林孤立支点/突破量能/放量止跌、莫里斯统计表)
- 脚本 `scripts/kline_study/`: extract_epub.py · db_ro.py(只读连接) · load_daily.py · kline_defs.py · backtest_daily.py · analysis_extra.py · backtest_minute_box.py · factor_quintile.py · backtest_zwquant.py · stat_tails_amplitude.py · stat_inference.py
- 本地缓存(不入库): `C:\Users\admin\dev\_kline_extract\`(书的全文抽取、图片、行情 parquet)
- skill 草稿(建议, 等用户看完报告再定): `skills/kline-skill/`
