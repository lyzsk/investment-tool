# WyckoffPro(V3.1)代码学习笔记 —— 威科夫事件机械化参考 ①

- 本地: `C:\Users\admin\dev\WyckoffPro-main`(只读)。基于孟洪涛《威科夫操盘法》+ DeepSeek "反向证伪"。读了: `engine/thresholds.py`、`engine/signal_detector.py`(全文)、`engine/phase_fsm.py`(状态转移+TR 更新)、`engine/channel.py`、`engine/nine_tests.py`(前 60 行)、`engine/weis_wave.py`(接口)、`config/default.yaml`、README、`doc/威科夫操盘法_孟洪涛版_深度学习指南.md`(目录)
- 一句话: **把每根 K 线对 13 种事件各打一个 0~1 "似然分"(多维加权), 再用有限状态机(11 个阶段)按事件序列推进**

## 一、阈值怎么定(值得借鉴)
`AdaptiveThresholds(lookback=120)`: **每只股票用自己近 120 日的分位数**——
| 阈值 | 定义 |
|---|---|
| climax 量 | volume 95 分位 |
| climax 振幅 | amplitude=(高−低)/前收 的 95 分位 |
| Spring 最大穿透 | ATR20 × 1.5 |
| ST/SC 量比 | 0.60(固定) |
| 低量测试 | volume 20 分位 |
| JOC 放量 | volume 85 分位 |
| VDB | 振幅/量 90 分位 |
→ 和用户"参数按个股自身动态定"一致; 我们的 definitions.md 沿用"分位数+ATR 倍数"思路。

## 二、事件打分(signal_detector.py)
- **SC** = 0.30·min(量/95分位,1) + 0.25·(是否创 60 日新低) + 0.20·(阴线实体/下影形态) + 0.25·(趋势=DOWN)
- **AR** = SC 后 1~15 根、阳线、相对 SC 缩量、离 SC 低点反弹幅度(5% 满分)
- **ST** = 接近 SC 低点(穿透以 ATR 计) + 量/SC量 < 0.6 + 不深穿(<2ATR)
- **Spring** = 穿透 TR 下沿 0~1.5 ATR + 收盘收回下沿 + 量 < 1.5×20日均量
- **SOS/SOW** = 阳(阴)线 + 量/20日均量(1.5 倍满分) + 收盘突破(跌破)TR 边界
- **UT** = 最高价越过 TR 上沿 0~2 ATR + 收盘回到上沿下 + 量 ≥ 1.2×均量
- **JOC** = 收盘 > Creek + 量 ≥ 85 分位 + 突破距离 ≥ 0.5 ATR
- **BC** = 量 95 分位 + 60 日新高 + 振幅 95 分位 + 趋势=UP
- 趋势(`_build_context`): 收盘 vs MA20 **±2% 固定带** → UP/DOWN/SIDEWAYS
- 记录门槛似然 ≥ 0.30, 告警 ≥ 0.60

## 三、TR 箱体与 Creek/Ice
- TR 上/下沿 = **近 60 日最高价 85 分位 / 最低价 15 分位**, 每天 0.9 旧 + 0.1 新做平滑, 只在 ACC/DIS 阶段更新。
- Creek = TR上沿 × 0.97, Ice = TR下沿 × 1.03(**固定 3%**); channel.py 另用线性回归 ±2σ 作超买超卖线。

## 四、阶段 FSM
MKD → ACC-A(SC/AR/ST 等停止信号) → ACC-B(ST/VDB 且持续 ≥5 天) → ACC-C(Spring) → ACC-D(SOS 且收盘 > TR上沿×0.98) → ACC-E(JOC) → MKU(收盘 > TR上沿×1.1); 派发对称。另有"反面证据积分 ≥71 紧急反转"。

## 五、我发现的问题(批判)
1. **很多"动态"其实是固定常数**: Creek/Ice ±3%、趋势 MA20±2%、ST 量比 0.6、Weis 波 2% 反转、TR 宽度上限 25%——对 20cm 创业板和 5% ST 一视同仁。
2. **UTAD 被限定在"ACC"(吸筹)阶段才计算**(`if "ACC" not in phase_code: return 0`), 这与威科夫定义相反(UTAD 是派发末期), 疑似 bug。
3. 配置里 `a_share_adapt.limit_up_as_bc / limit_down_as_sc` **代码中无任何引用**——A 股涨跌停适配实际没有实现。
4. 打分权重(0.30/0.25/…)全是拍的, 仓库内 `backtest/` 只有框架, **没有任何事件级前瞻收益统计**。
5. TR 用 60 日分位而不是摆动高低点, 在趋势段也会产出"箱体", 需靠 FSM 阶段过滤。

## 六、可借鉴到 definitions.md 的
- 分位数阈值 + ATR 穿透度量(✓ 采纳)。
- 事件"似然分"而非 0/1(✓ 作为 kline-skill 的输出形式建议, 但回测先用 0/1 硬规则以便统计)。
- FSM 思路(✓ 作为阶段识别的骨架, 但转移条件要改为"事件+确认")。
