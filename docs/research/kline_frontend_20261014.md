# 东财 / 同花顺网页 K 线前端：实现与指标口径（2026-10-14，为将来的 inv-ui 做准备）

> 来源：公开网页前端的 JS（quote.eastmoney.com 个股页、stockpage.10jqka.com.cn），用 curl 和 REA 无头抓包取得，读完只记**参数、口径和实现要点**，不搬源码（版权）。对照脚本：`scripts/temp/rea_1014/ind_cmp.mjs`。

## 1. 他们用什么画

| | 东财 quote.eastmoney.com | 同花顺 stockpage.10jqka.com.cn |
|---|---|---|
| 图表库 | **自研 canvas**：`emcharts.dftzj.com/ec/3.18.1/emcharts.min.js`（约 950KB，含分时/K线/筹码，内嵌 lodash）+ 页面包装 `quotekchart/1.0.6.js` | **开源 klinecharts**（Apache-2.0，canvas；bundle 里带它的 toolbar 样式类名和全套内置指标）+ AntV G2 画辅助图；Next.js 页面 |
| K 线数据 | `push2his.eastmoney.com/api/qt/stock/kline/get`（JSONP；klt=周期，fqt=复权，lmt=根数；初始拉「可见柱数 + 24」根，拖动时再按 smplmt 拉全量） | `quota-h.10jqka.com.cn/fuyao/common_hq_aggr/quote/v1/single_kline`（POST JSON，`adjust_type:"forward"` 默认前复权；直连 403，要 token，**我们不用**） |
| 默认复权 | 库默认 `cfq:0`（不复权；页面可覆盖，未核） | 前复权 |
| 默认可见柱数 | `scale.pillar:30`（最少 10），柱宽占比 0.7 | klinecharts 默认 |

**inv-ui 选型建议**：直接用 **klinecharts**（同花顺网页同款，Apache-2.0，内置的中国式指标默认参数就是下表的「同花顺」列），或者用 TradingView 的 lightweight-charts（Apache-2.0，更轻，指标要自己算）。数据走我们自己的 kline_day/kline_minute 库，不依赖对方接口。东财那套是自研闭源，只参考口径。

## 2. 默认指标与参数

| 指标 | 东财（quotekchart titleKeys + 计算代码） | 同花顺（klinecharts calcParams） | 我们 `scripts/quotes/indicators.mjs` |
|---|---|---|---|
| 主图均线 | MA5/10/20/60（另算 30；量能 MA5/10） | MA 5,10,20,30,60 | MA5/10/20/60 ✅ |
| EXPMA | 12, 50 | EMA 6,12,20 | — |
| BOLL | 20, 2（总体标准差，除以 N） | 20, 2 | — |
| SAR / BBI | SAR(步长 0.02) / BBI | SAR 2,2,20 / BBI 3,6,12,24 | — |
| MACD | 12,26,9；**首根 close 作 EMA 种子**，DIF₀=DEA₀=0，柱=2×(DIF−DEA) | 12,26,9 | 12,26,9（SMA 种子）——**数值一致** ✅ |
| KDJ | 9,3,3；首根 K=D=RSV（不是通达信的 50） | 9,3,3 | — |
| RSI | **6/12/24，Wilder 平滑** SMA(x,N,1) | 6,12,24 | **RSI14 简单均值** ❌ 口径不同 |
| WR | 10, 6 | — | — |
| DMI | PDI/MDI/ADX/ADXR（14,6） | 14,6 | — |
| BIAS | 6,12,24 | 6,12,24 | — |
| OBV | OBV + MA30 | 30 | — |
| CCI | **14**，TYP=(H+L+C)/3 | **20** | — |
| ROC | 12, 6 | 12, 6 | — |
| 东财独有副图 | 两融差额（LRCE）、资金流（ZJL：超大/大/中/小单） | — | — |
| 默认副图 | `indexv:"CMA"`（主图均线），`indexh:"RSI"`（第一副图） | VOL + MACD | — |

## 3. 颜色与布局（东财）
- 涨红跌绿：`rise:"red"`, `fall:"green"`；背景 `#ffffff`，边框 `#666`，虚线 `#ccc`，文字 `#333`，平盘 `#666`。
- 均线色 `colorsMA = [#376CFF, #DD9900, #FF00FF, #008000]`，对应 MA5/10/20/60。
- 副图线色 `colorsIndex = [#a0a0a0, #f4aa0a, #ff1dff, #007130]`；量能 `colorsTrading = [#FE59FE, #323232, #FF00FF]`。
- 筹码色：获利 `#5a8df8`，均价线 `#fa8d0d`，套牢 `#FF0000`。
- 纵向分区：K 线区、量能区、指标区、底部 minimap（拖动缩略图，line `#6EB4FF`/fill `#E4EFFF`）。
- 字体 12px Arial/微软雅黑；padding 左 60、右 65；十字光标实线 2 / 虚线 3，`#666`；最高/最低价有引线标注（maxin）。
- 交互：拖拽平移、滚轮缩放（柱数 10 起）、折叠副图、点击切换指标、tooltip 弹窗（popWin）、两融/资金流副图点击跳详情。

## 4. 筹码分布（东财 cyq 算法，可自己复现）
东财在前端用 K 线现算，不调接口。要点如下：
1. 价格轴：窗口内最高到最低等分 150 档（`fator=150`，步长至少 0.01）。窗口 = 全部历史，或者最近 `range` 根。
2. 逐日迭代：
   - 先把所有档位的筹码 ×(1−换手率)，换手率取 K 线第 9 个字段 /100，上限 1。
   - 再把当日成交按**三角分布**分到 [最低, 最高] 档位：峰值在当日均价 (O+C+H+L)/4，面积 = 换手率；一字板（H=L）全部堆在一档。
3. 输出：
   - 获利比例 = 当前收盘价以下的筹码占比。
   - 平均成本 = 累计 50% 分位价。
   - 90%/70% 筹码区间，以及集中度 = (高−低)/(高+低)。
4. 前提：我们的 kline_day 要有换手率字段。现在库里有没有这列未核，进 TODO。

## 5. 对照验证结果（`ind_cmp.mjs`，本地 downloads/quotes/daily 日线，src=east、adjusted=true）

| 票 | 东财式 MACD 柱 | 我们 | 东财式 RSI14(Wilder) | 我们 RSI14(简单) | 东财 RSI6 |
|---|---|---|---|---|---|
| 002714 | −0.340 | −0.340 | 46.52 | 42.12 | 40.22 |
| 000002 | 0.209 | 0.209 | 76.69 | 78.92 | 83.30 |
| 301682 | −0.680 | −0.680 | 35.99 | 45.00 | 26.23 |
| 605336 | −0.012 | −0.012 | 55.54 | 58.50 | 61.64 |

- **MACD**：窗口 120 根以上，种子差异已经衰减到 0.001 以内，结论一致。
- **RSI**：差 2~9 个点，而且东财屏幕上显示的是 6/12/24，没有 14。如果导师或用户报的是「东财 RSI」，我们的数字对不上。
- **建议（待用户定）**：indicators.mjs 改为 RSI6/12/24 Wilder，并加 KDJ(9,3,3)、BOLL(20,2)，全部按东财口径。改动约 30 行，facts 文本会变，所以要通知下游。
- **未核**：复权口径（东财页面实际用的 fqt）、分时图（均价线算法、5 日分时、昨收基线、量柱颜色），这些在 emcharts 的分时模块里，这次没展开。将来做 inv-ui 分时页时，用 REA 抓页面截图对照。
