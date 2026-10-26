# Kronos / YYKline / KChartView 代码学习笔记

## 一、Kronos(K 线基础模型)
- 本地: `C:\Users\admin\dev\Kronos-master`(只读)。AAAI 2026, arXiv 2508.02739。读了 README、`model/kronos.py` 的类/函数结构与 `predict()`、`finetune/config.py`、examples 目录清单。
- 机制: ①**分层离散 tokenizer**(BSQ 量化, s1/s2 两级 bits)把 OHLCV+成交额(+时间戳: 分/时/星期/日/月)编码成 token; ②decoder-only Transformer 自回归生成未来 token, 再解码回 OHLCV。
- 规格: mini 4.1M(上下文 2048)/ small 24.7M / base 102.3M(上下文 512)/ large 499M(未开源)。
- **归一化 = 只用输入窗口自身的均值/标准差做 z-score, 再 clip ±5**(`predict()` 里 `x_mean, x_std = np.mean(x), np.std(x)`)——这就是"按个股自身近期波动动态归一化", 与我们动态阈值同一思路。
- 微调样例: qlib `csi300`, lookback 90, predict 10, 训练 2011~2022, 回测 2024-07~2025-06。examples 有 A 股日线批量预测脚本。
- 和本任务的关系: **它不做形态/事件识别**, 是"整段 K 线 → 未来路径分布"的生成模型; `sample_count` 多路径采样可直接给出未来 N 日的分布(P10/P90)。
- 我的判断: 可作为将来"形态信号 vs 模型预测"的对照基准, 但需 GPU、需在本库数据上自己做样本外检验, 论文指标不能直接当真。**本次未运行**(遵守 GPU 暂停协议且非本任务必需)。

## 二、YYKline(iOS/macOS K 线绘制库)
- 本地: `C:\Users\admin\dev\YYKline-master`(Objective-C)。读了 README 与 Painter 目录清单。
- 只有绘制 + 指标(MA/EMA/BOLL/KDJ/MACD/RSI/WR/成交量/分时), **没有任何形态识别、阈值或威科夫逻辑**。对本任务价值仅在"指标口径"。

## 三、KChartView(Android K 线控件)
- 本地: `C:\Users\admin\dev\KChartView-master`(Java)。读了 README、`DataHelper.java`(指标计算)。
- 指标口径(**与同花顺/通达信一致, 可作为我们指标实现的对照**):
  - RSI(6/12/24): `MaxEma=(Rmax+(N−1)·前值)/N`, `AbsEma` 同理, RSI = MaxEma/AbsEma×100(即 SMA(N,1) 平滑, 不是 Wilder 的 14)
  - KDJ(9,3,3): RSV 用 9 日高低; K=(RSV+2K')/3, D=(K+2D')/3, J=3K−2D
  - MACD(12,26,9): EMA12=前×11/13+今×2/13, EMA26=前×25/27+今×2/27, DEA=前×8/10+DIF×2/10, **柱=(DIF−DEA)×2**
- 同样**没有形态识别**。

## 结论
五个代码项目里, 真正做"机械识别"的只有两个威科夫项目; 三个其它项目分别提供"动态归一化的生成式基准(Kronos)"和"国内指标口径(KChartView/YYKline)"。
