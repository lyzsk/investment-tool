# 混合账本 dry-run 2026-10-12 ~ 2026-10-16(mix_plans.py --dryrun, 2026-10-16 19:40 生成, 零 token, 不写账本)

口径: 读实盘 books/ 里各导师链当日挂单(按 slot 时刻逐段回演), 三本混合账本在内存里从 10 万起跑; 成交=日线保守近似(买 low≤挂价且非一字涨停 / 卖 high≥挂价 / T+1), 不分挂单时刻(会高估午后单成交率); Hedge 学习每日 EOD 后更新(状态存临时目录)。
已知前视: similarity.json(拟人度 delta)只有最新一份, 回演前几天也用了它; 其余(命中率 d1<D、nav、导师真人净值、龙虎榜昨日)均 as-of。

## 摘要(人读, 10/16 晚)

- 5 天出单(BUY/SELL 行, 同价同量不重出): A-mix 26/11, A-mix-eq 38/13, A-mix-lhb 27/12; 日线近似成交 14/18/16 笔。前两天(10/12-13 有主线/普跌、≥2 链同买 19/8 只)出单集中, 10/15-16 普跌日导师链同买票只有 2~3 只, 主规则 BUY=0, 只剩卖出
- 末日 nav(日线近似, 只作冒烟): A-mix 99,432 / A-mix-eq 99,461 / A-mix-lhb 99,412——5 天里三本差异很小, 符合"样本少=近等权"的预期, 不能当业绩证据
- 单票仓位小: 目标=Σw×链挂单占比, 多数票只有 1~5% nav(100~500 股), 混合账本大部分时间是现金; 等权本更碎(28 次"金额不足一手")
- lhb 本与主本只差 1 单(机构/北向放行 1 次; 拉萨天团减半 0 次), 龙虎榜修正在这 5 天几乎没起作用
- 卖出 v1 有"没有任何导师链持有→按昨收挂卖"的分支: 混合账本成交了但看好链自己没成交的票, 次日就会被清掉(三本合计全期 14 单属于这类, 10/14-15 占 10 单), 是否保留待定
- 权重: 拟人度 delta≤0 减半覆盖了 9/13 条导师链(其中多条 delta 恰为 0=没数据也被减半), 是目前权重差异的最大来源

## 2026-10-12  市况=有主线 {'有主线': 13, '无主线退潮': 3}  T=0.91  龙虎榜用 2026-10-09(72 只)

- 导师链当日 BUY 票 32 只, 其中 ≥2 链同买 19 只; slot 11 个
- 权重前 3: liuyiqing 12.7%、qushitiange 9.9%、chong5000w 8.1%; 最低 3.2%; 高权重集合 3 条
- Hedge 学习: 等权均值 +0.07pp; 超额最大 stzhilang +2.31pp / 最小 taoge -3.14pp
- **A-mix**: BUY 13 / SELL 0 单, 成交 4 废 3, EOD nav 100,533; 未出单原因 {'不准入': 47, '金额不足一手/已持够/现金不足': 4, '同价同量单已挂(不重出)': 17}
- **A-mix-eq**: BUY 15 / SELL 0 单, 成交 5 废 2, EOD nav 100,610; 未出单原因 {'金额不足一手/已持够/现金不足': 28, '不准入': 25, '同价同量单已挂(不重出)': 13}
- **A-mix-lhb**: BUY 14 / SELL 0 单, 成交 5 废 3, EOD nav 100,518; 未出单原因 {'不准入': 46, '金额不足一手/已持够/现金不足': 4, '同价同量单已挂(不重出)': 17}

## 2026-10-13  市况=普跌 {'普跌': 8, '有主线': 6, '无主线退潮': 2}  T=0.88  龙虎榜用 2026-10-12(68 只)

- 导师链当日 BUY 票 19 只, 其中 ≥2 链同买 8 只; slot 7 个
- 权重前 3: stzhilang 11.2%、liuyiqing 9.6%、xingjianye 8.0%; 最低 3.2%; 高权重集合 3 条
- Hedge 学习: 等权均值 -0.98pp; 超额最大 lubenyuan +1.35pp / 最小 liuyiqing -1.86pp
- **A-mix**: BUY 11 / SELL 1 单, 成交 5 废 2, EOD nav 100,123; 未出单原因 {'不准入': 17, '同价同量单已挂(不重出)': 4}
- **A-mix-eq**: BUY 15 / SELL 0 单, 成交 5 废 1, EOD nav 100,186; 未出单原因 {'不准入': 12, '金额不足一手/已持够/现金不足': 3, '同价同量单已挂(不重出)': 2}
- **A-mix-lhb**: BUY 11 / SELL 2 单, 成交 6 废 2, EOD nav 100,103; 未出单原因 {'不准入': 17, '同价同量单已挂(不重出)': 4}

## 2026-10-14  市况=有主线 {'有主线': 15, '无主线退潮': 1}  T=0.85  龙虎榜用 2026-10-13(62 只)

- 导师链当日 BUY 票 24 只, 其中 ≥2 链同买 8 只; slot 10 个
- 权重前 3: qushitiange 12.8%、lubenyuan 10.4%、xingjianye 9.8%; 最低 3.0%; 高权重集合 3 条
- Hedge 学习: 等权均值 -0.56pp; 超额最大 zhiyingjuexin +1.50pp / 最小 cb -2.18pp
- **A-mix**: BUY 2 / SELL 4 单, 成交 3 废 3, EOD nav 100,497; 未出单原因 {'不准入': 26, '同价同量单已挂(不重出)': 3}
- **A-mix-eq**: BUY 5 / SELL 5 单, 成交 2 废 7, EOD nav 100,410; 未出单原因 {'金额不足一手/已持够/现金不足': 6, '不准入': 17, '同价同量单已挂(不重出)': 3}
- **A-mix-lhb**: BUY 2 / SELL 4 单, 成交 3 废 3, EOD nav 100,476; 未出单原因 {'不准入': 26, '同价同量单已挂(不重出)': 3}

## 2026-10-15  市况=普跌 {'普跌': 12, '有主线': 1}  T=0.82  龙虎榜用 2026-10-14(68 只)

- 导师链当日 BUY 票 7 只, 其中 ≥2 链同买 3 只; slot 6 个
- 权重前 3: lubenyuan 17.6%、zhiyingjuexin 11.5%、antoo 9.7%; 最低 3.0%; 高权重集合 3 条
- Hedge 学习: 等权均值 -0.66pp; 超额最大 taoge +0.83pp / 最小 a658 -2.62pp
- **A-mix**: BUY 0 / SELL 1 单, 成交 0 废 1, EOD nav 99,921; 未出单原因 {'不准入': 7}
- **A-mix-eq**: BUY 0 / SELL 3 单, 成交 2 废 1, EOD nav 99,775; 未出单原因 {'不准入': 4, '金额不足一手/已持够/现金不足': 3}
- **A-mix-lhb**: BUY 0 / SELL 1 单, 成交 0 废 1, EOD nav 99,900; 未出单原因 {'不准入': 7}

## 2026-10-16  市况=普跌 {'普跌': 15}  T=0.79  龙虎榜用 2026-10-15(60 只)

- 导师链当日 BUY 票 13 只, 其中 ≥2 链同买 2 只; slot 8 个
- 权重前 3: lubenyuan 13.9%、qushitiange 9.4%、stzhilang 9.2%; 最低 3.0%; 高权重集合 3 条
- Hedge 学习: 等权均值 -0.55pp; 超额最大 qushitiange +0.55pp / 最小 a658 -1.61pp
- **A-mix**: BUY 0 / SELL 5 单, 成交 2 废 3, EOD nav 99,432; 未出单原因 {'不准入': 14}
- **A-mix-eq**: BUY 3 / SELL 5 单, 成交 4 废 3, EOD nav 99,461; 未出单原因 {'不准入': 11}
- **A-mix-lhb**: BUY 0 / SELL 5 单, 成交 2 废 3, EOD nav 99,412; 未出单原因 {'不准入': 14}

## 汇总

| 日期 | 账本 | BUY | SELL | 成交 | EOD nav |
|---|---|---|---|---|---|
| 2026-10-12 | A-mix | 13 | 0 | 4 | 100,533 |
| 2026-10-12 | A-mix-eq | 15 | 0 | 5 | 100,610 |
| 2026-10-12 | A-mix-lhb | 14 | 0 | 5 | 100,518 |
| 2026-10-13 | A-mix | 11 | 1 | 5 | 100,123 |
| 2026-10-13 | A-mix-eq | 15 | 0 | 5 | 100,186 |
| 2026-10-13 | A-mix-lhb | 11 | 2 | 6 | 100,103 |
| 2026-10-14 | A-mix | 2 | 4 | 3 | 100,497 |
| 2026-10-14 | A-mix-eq | 5 | 5 | 2 | 100,410 |
| 2026-10-14 | A-mix-lhb | 2 | 4 | 3 | 100,476 |
| 2026-10-15 | A-mix | 0 | 1 | 0 | 99,921 |
| 2026-10-15 | A-mix-eq | 0 | 3 | 2 | 99,775 |
| 2026-10-15 | A-mix-lhb | 0 | 1 | 0 | 99,900 |
| 2026-10-16 | A-mix | 0 | 5 | 2 | 99,432 |
| 2026-10-16 | A-mix-eq | 3 | 5 | 4 | 99,461 |
| 2026-10-16 | A-mix-lhb | 0 | 5 | 2 | 99,412 |

合计: A-mix BUY 26 / SELL 11 / 成交 14; A-mix-eq BUY 38 / SELL 13 / 成交 18; A-mix-lhb BUY 27 / SELL 12 / 成交 16

## 全部生成的 plans 行

```
2026-10-12 - 09:15 | A-mix | BUY | 002212 | 7.41 | 200 | day | 7.56 | - | mix[main] 4链共识(高权重1); 目标1.85%nav(上限24%); 链: chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、stzhilang4%
2026-10-12 - 09:15 | A-mix | BUY | 002805 | 19.44 | 100 | day | 19.44 | - | mix[main] 2链共识(高权重2); 目标2.17%nav(上限30%); 链: liuyiqing13%、qushitiange10%
2026-10-12 - 09:15 | A-mix | BUY | 300364 | 23.98 | 200 | day | 24.47 | - | mix[main] 6链共识(高权重1); 目标5.31%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 09:15 | A-mix | BUY | 600812 | 6.03 | 500 | day | 6.03 | - | mix[main] 4链共识(高权重3); 目标3.02%nav(上限27%); 链: liuyiqing13%、qushitiange10%、chong5000w8%、antoo7%
2026-10-12 - 09:15 | A-mix | BUY | 601118 | 6.95 | 300 | day | 7.16 | - | mix[main] 7链共识(高权重2); 目标2.76%nav(上限26%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 09:15 | A-mix | BUY | 603533 | 25.44 | 100 | day | 25.44 | - | mix[main] 8链共识(高权重1); 目标4.62%nav(上限26%); 链: liuyiqing13%、antoo7%、lianghuaxiaohao5%、xuanqiucaijing5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 09:27 | A-mix | BUY | 601118 | 6.95 | 400 | day | 7.16 | - | mix[main] 7链共识(高权重2); 目标3.03%nav(上限26%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 10:00 | A-mix | BUY | 002675 | 13.06 | 100 | day | 13.89 | - | mix[main] 2链共识(高权重1); 目标1.33%nav(上限26%); 链: qushitiange10%、xuanqiucaijing5%
2026-10-12 - 10:00 | A-mix | BUY | 300364 | 24.47 | 200 | day | 24.47 | - | mix[main] 6链共识(高权重1); 目标5.37%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 13:00 | A-mix | BUY | 300364 | 24.95 | 200 | day | 24.47 | - | mix[main] 6链共识(高权重1); 目标5.25%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 14:00 | A-mix | BUY | 603533 | 25.48 | 200 | day | 25.44 | - | mix[main] 9链共识(高权重1); 目标5.21%nav(上限26%); 链: liuyiqing13%、antoo7%、lianghuaxiaohao5%、xuanqiucaijing5%、daxingdaxingdadangxing4%、bianbenling4%、a6584%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 14:55 | A-mix | BUY | 300364 | 25.5 | 100 | day | 24.47 | - | mix[main] 4链共识(高权重1); 目标3.51%nav(上限24%); 链: chong5000w8%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 14:55 | A-mix | BUY | 601118 | 7.16 | 400 | day | 7.16 | - | mix[main] 6链共识(高权重2); 目标2.99%nav(上限25%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 09:15 | A-mix-eq | BUY | 000710 | 11.07 | 100 | day | 11.3 | - | mix[eq] 2链共识; 目标1.25%nav(上限22%); 链: gaogailvfuli6%、stzhilang6%
2026-10-12 - 09:15 | A-mix-eq | BUY | 002212 | 7.41 | 200 | day | 7.56 | - | mix[eq] 4链共识; 目标2.10%nav(上限24%); 链: lianghuaxiaohao6%、daxingdaxingdadangxing6%、stzhilang6%、chong5000w6%
2026-10-12 - 09:15 | A-mix-eq | BUY | 300364 | 23.98 | 200 | day | 24.47 | - | mix[eq] 6链共识; 目标5.89%nav(上限25%); 链: taoge6%、lianghuaxiaohao6%、xingjianye6%、xuanqiucaijing6%、chong5000w6%、zhiyingjuexin6%
2026-10-12 - 09:15 | A-mix-eq | BUY | 600812 | 5.85 | 300 | day | 6.03 | - | mix[eq] 4链共识; 目标1.94%nav(上限27%); 链: qushitiange6%、liuyiqing6%、chong5000w6%、antoo6%
2026-10-12 - 09:15 | A-mix-eq | BUY | 601118 | 7.01 | 400 | day | 7.16 | - | mix[eq] 7链共识; 目标3.09%nav(上限25%); 链: qushitiange6%、lianghuaxiaohao6%、bianbenling6%、daxingdaxingdadangxing6%、gaogailvfuli6%、stzhilang6%、chong5000w6%
2026-10-12 - 09:15 | A-mix-eq | BUY | 603533 | 25.44 | 100 | day | 25.44 | - | mix[eq] 8链共识; 目标4.70%nav(上限25%); 链: liuyiqing6%、lianghuaxiaohao6%、bianbenling6%、daxingdaxingdadangxing6%、gaogailvfuli6%、xuanqiucaijing6%、stzhilang6%、antoo6%
2026-10-12 - 10:00 | A-mix-eq | BUY | 300364 | 24.47 | 200 | day | 24.47 | - | mix[eq] 6链共识; 目标5.96%nav(上限25%); 链: taoge6%、lianghuaxiaohao6%、xingjianye6%、xuanqiucaijing6%、chong5000w6%、zhiyingjuexin6%
2026-10-12 - 10:00 | A-mix-eq | BUY | 300369 | 10.22 | 100 | day | 10.43 | - | mix[eq] 4链共识; 目标1.62%nav(上限26%); 链: taoge6%、lianghuaxiaohao6%、bianbenling6%、xuanqiucaijing6%
2026-10-12 - 10:30 | A-mix-eq | BUY | 603533 | 25.48 | 200 | day | 25.44 | - | mix[eq] 9链共识; 目标5.45%nav(上限25%); 链: liuyiqing6%、lianghuaxiaohao6%、a6586%、bianbenling6%、daxingdaxingdadangxing6%、gaogailvfuli6%、xuanqiucaijing6%、stzhilang6%、antoo6%
2026-10-12 - 13:00 | A-mix-eq | BUY | 300364 | 24.95 | 200 | day | 24.47 | - | mix[eq] 6链共识; 目标5.87%nav(上限25%); 链: taoge6%、lianghuaxiaohao6%、xingjianye6%、xuanqiucaijing6%、chong5000w6%、zhiyingjuexin6%
2026-10-12 - 13:00 | A-mix-eq | BUY | 600812 | 6.03 | 300 | day | 6.03 | - | mix[eq] 4链共识; 目标1.97%nav(上限27%); 链: qushitiange6%、liuyiqing6%、chong5000w6%、antoo6%
2026-10-12 - 14:00 | A-mix-eq | BUY | 002212 | 7.56 | 300 | day | 7.56 | - | mix[eq] 5链共识; 目标2.59%nav(上限23%); 链: lianghuaxiaohao6%、daxingdaxingdadangxing6%、gaogailvfuli6%、stzhilang6%、chong5000w6%
2026-10-12 - 14:00 | A-mix-eq | BUY | 603533 | 25.94 | 200 | day | 25.44 | - | mix[eq] 9链共识; 目标5.72%nav(上限25%); 链: liuyiqing6%、lianghuaxiaohao6%、a6586%、bianbenling6%、daxingdaxingdadangxing6%、gaogailvfuli6%、xuanqiucaijing6%、stzhilang6%、antoo6%
2026-10-12 - 14:55 | A-mix-eq | BUY | 300364 | 25.5 | 100 | day | 24.47 | - | mix[eq] 4链共识; 目标4.29%nav(上限24%); 链: lianghuaxiaohao6%、xuanqiucaijing6%、chong5000w6%、zhiyingjuexin6%
2026-10-12 - 14:55 | A-mix-eq | BUY | 601118 | 7.08 | 400 | day | 7.16 | - | mix[eq] 6链共识; 目标3.12%nav(上限24%); 链: qushitiange6%、lianghuaxiaohao6%、daxingdaxingdadangxing6%、gaogailvfuli6%、stzhilang6%、chong5000w6%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 002212 | 7.41 | 200 | day | 7.56 | - | mix[lhb] 4链共识(高权重1); 目标1.85%nav(上限24%); 链: chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、stzhilang4%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 002805 | 19.44 | 100 | day | 19.44 | - | mix[lhb] 2链共识(高权重2); 目标2.17%nav(上限30%); 链: liuyiqing13%、qushitiange10%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 300364 | 23.98 | 200 | day | 24.47 | - | mix[lhb] 6链共识(高权重1); 目标5.31%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 600400 | 3.98 | 200 | day | 3.98 | - | mix[lhb] 1高权重链+昨日龙虎榜机构/北向净买; 目标0.98%nav(上限31%); 链: liuyiqing13%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 600812 | 6.03 | 500 | day | 6.03 | - | mix[lhb] 4链共识(高权重3); 目标3.02%nav(上限27%); 链: liuyiqing13%、qushitiange10%、chong5000w8%、antoo7%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 601118 | 6.95 | 300 | day | 7.16 | - | mix[lhb] 7链共识(高权重2); 目标2.76%nav(上限26%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 09:15 | A-mix-lhb | BUY | 603533 | 25.44 | 100 | day | 25.44 | - | mix[lhb] 8链共识(高权重1); 目标4.62%nav(上限26%); 链: liuyiqing13%、antoo7%、lianghuaxiaohao5%、xuanqiucaijing5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 09:27 | A-mix-lhb | BUY | 601118 | 6.95 | 400 | day | 7.16 | - | mix[lhb] 7链共识(高权重2); 目标3.03%nav(上限26%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、bianbenling4%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 10:00 | A-mix-lhb | BUY | 002675 | 13.06 | 100 | day | 13.89 | - | mix[lhb] 2链共识(高权重1); 目标1.33%nav(上限26%); 链: qushitiange10%、xuanqiucaijing5%
2026-10-12 - 10:00 | A-mix-lhb | BUY | 300364 | 24.47 | 200 | day | 24.47 | - | mix[lhb] 6链共识(高权重1); 目标5.37%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 13:00 | A-mix-lhb | BUY | 300364 | 24.95 | 200 | day | 24.47 | - | mix[lhb] 6链共识(高权重1); 目标5.25%nav(上限25%); 链: chong5000w8%、taoge8%、xingjianye6%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 14:00 | A-mix-lhb | BUY | 603533 | 25.48 | 200 | day | 25.44 | - | mix[lhb] 9链共识(高权重1); 目标5.21%nav(上限26%); 链: liuyiqing13%、antoo7%、lianghuaxiaohao5%、xuanqiucaijing5%、daxingdaxingdadangxing4%、bianbenling4%、a6584%、stzhilang4%、gaogailvfuli3%
2026-10-12 - 14:55 | A-mix-lhb | BUY | 300364 | 25.5 | 100 | day | 24.47 | - | mix[lhb] 4链共识(高权重1); 目标3.51%nav(上限24%); 链: chong5000w8%、lianghuaxiaohao5%、xuanqiucaijing5%、zhiyingjuexin4%
2026-10-12 - 14:55 | A-mix-lhb | BUY | 601118 | 7.16 | 400 | day | 7.16 | - | mix[lhb] 6链共识(高权重2); 目标2.99%nav(上限25%); 链: qushitiange10%、chong5000w8%、lianghuaxiaohao5%、daxingdaxingdadangxing4%、stzhilang4%、gaogailvfuli3%
2026-10-13 - 09:15 | A-mix | BUY | 001330 | 7.68 | 300 | day | 7.67 | - | mix[main] 3链共识(高权重1); 目标2.78%nav(上限16%); 链: liuyiqing10%、qushitiange6%、a6583%
2026-10-13 - 09:15 | A-mix | BUY | 002343 | 6.7 | 200 | day | 6.69 | - | mix[main] 2链共识(高权重1); 目标1.94%nav(上限20%); 链: liuyiqing10%、a6583%
2026-10-13 - 09:15 | A-mix | BUY | 601988 | 6.97 | 800 | day | 6.97 | - | mix[main] 6链共识(高权重1); 目标5.83%nav(上限26%); 链: xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 09:15 | A-mix | SELL | 002805 | 20.75 | 100 | day | 18.86 | - | mix[main] 卖v1: 持有它的 1 条导师链全部已出卖单: liuyiqing
2026-10-13 - 09:27 | A-mix | BUY | 601398 | 8.48 | 400 | day | 8.44 | - | mix[main] 4链共识(高权重1); 目标4.07%nav(上限22%); 链: stzhilang11%、daxingdaxingdadangxing7%、qushitiange6%、lianghuaxiaohao5%
2026-10-13 - 09:27 | A-mix | BUY | 601988 | 6.97 | 1100 | day | 6.97 | - | mix[main] 8链共识(高权重2); 目标8.29%nav(上限21%); 链: stzhilang11%、xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、qushitiange6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 10:00 | A-mix | BUY | 002692 | 5.19 | 500 | day | 5.24 | - | mix[main] 3链共识(高权重1); 目标2.97%nav(上限25%); 链: liuyiqing10%、chong5000w7%、taoge4%
2026-10-13 - 10:00 | A-mix | BUY | 601595 | 27.6 | 100 | day | 27.21 | - | mix[main] 4链共识(高权重1); 目标3.43%nav(上限22%); 链: liuyiqing10%、lubenyuan8%、antoo7%、zhiyingjuexin6%
2026-10-13 - 10:00 | A-mix | BUY | 601988 | 7 | 1300 | day | 6.97 | - | mix[main] 9链共识(高权重3); 目标9.35%nav(上限20%); 链: stzhilang11%、liuyiqing10%、xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、qushitiange6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 11:00 | A-mix | BUY | 601595 | 27.25 | 100 | day | 27.21 | - | mix[main] 4链共识(高权重1); 目标3.42%nav(上限22%); 链: liuyiqing10%、lubenyuan8%、antoo7%、zhiyingjuexin6%
2026-10-13 - 14:00 | A-mix | BUY | 002692 | 5.19 | 600 | day | 5.24 | - | mix[main] 4链共识(高权重1); 目标3.48%nav(上限25%); 链: liuyiqing10%、chong5000w7%、taoge4%、a6583%
2026-10-13 - 14:55 | A-mix | BUY | 601398 | 8.49 | 500 | day | 8.47 | - | mix[main] 5链共识(高权重1); 目标5.06%nav(上限27%); 链: stzhilang11%、daxingdaxingdadangxing7%、chong5000w7%、qushitiange6%、lianghuaxiaohao5%
2026-10-13 - 09:15 | A-mix-eq | BUY | 001330 | 7.67 | 300 | day | 7.67 | - | mix[eq] 3链共识; 目标2.75%nav(上限17%); 链: qushitiange6%、liuyiqing6%、a6586%
2026-10-13 - 09:15 | A-mix-eq | BUY | 002343 | 6.69 | 200 | day | 6.69 | - | mix[eq] 2链共识; 目标1.85%nav(上限21%); 链: liuyiqing6%、a6586%
2026-10-13 - 09:15 | A-mix-eq | BUY | 002692 | 5.14 | 200 | day | 5.24 | - | mix[eq] 2链共识; 目标1.36%nav(上限26%); 链: taoge6%、chong5000w6%
2026-10-13 - 09:15 | A-mix-eq | BUY | 601398 | 8.42 | 300 | day | 8.44 | - | mix[eq] 3链共识; 目标2.71%nav(上限30%); 链: qushitiange6%、lianghuaxiaohao6%、daxingdaxingdadangxing6%
2026-10-13 - 09:15 | A-mix-eq | BUY | 601988 | 6.95 | 800 | day | 6.97 | - | mix[eq] 6链共识; 目标5.63%nav(上限26%); 链: lubenyuan6%、lianghuaxiaohao6%、xingjianye6%、daxingdaxingdadangxing6%、xuanqiucaijing6%、zhiyingjuexin6%
2026-10-13 - 09:27 | A-mix-eq | BUY | 601398 | 8.42 | 400 | day | 8.44 | - | mix[eq] 4链共识; 目标3.59%nav(上限25%); 链: qushitiange6%、lianghuaxiaohao6%、daxingdaxingdadangxing6%、stzhilang6%
2026-10-13 - 09:27 | A-mix-eq | BUY | 601988 | 6.95 | 1000 | day | 6.97 | - | mix[eq] 8链共识; 目标7.46%nav(上限22%); 链: qushitiange6%、lubenyuan6%、lianghuaxiaohao6%、xingjianye6%、daxingdaxingdadangxing6%、xuanqiucaijing6%、stzhilang6%、zhiyingjuexin6%
2026-10-13 - 10:00 | A-mix-eq | BUY | 002692 | 5.19 | 500 | day | 5.24 | - | mix[eq] 3链共识; 目标2.66%nav(上限23%); 链: taoge6%、liuyiqing6%、chong5000w6%
2026-10-13 - 10:00 | A-mix-eq | BUY | 601595 | 27.6 | 100 | day | 27.21 | - | mix[eq] 4链共识; 目标2.90%nav(上限21%); 链: lubenyuan6%、liuyiqing6%、antoo6%、zhiyingjuexin6%
2026-10-13 - 10:00 | A-mix-eq | BUY | 601988 | 6.97 | 1100 | day | 6.97 | - | mix[eq] 9链共识; 目标7.97%nav(上限21%); 链: qushitiange6%、lubenyuan6%、liuyiqing6%、lianghuaxiaohao6%、xingjianye6%、daxingdaxingdadangxing6%、xuanqiucaijing6%、stzhilang6%、zhiyingjuexin6%
2026-10-13 - 11:00 | A-mix-eq | BUY | 601398 | 8.44 | 400 | day | 8.44 | - | mix[eq] 4链共识; 目标3.59%nav(上限25%); 链: qushitiange6%、lianghuaxiaohao6%、daxingdaxingdadangxing6%、stzhilang6%
2026-10-13 - 11:00 | A-mix-eq | BUY | 601595 | 27.25 | 100 | day | 27.21 | - | mix[eq] 4链共识; 目标2.89%nav(上限21%); 链: lubenyuan6%、liuyiqing6%、antoo6%、zhiyingjuexin6%
2026-10-13 - 14:00 | A-mix-eq | BUY | 002692 | 5.14 | 700 | day | 5.24 | - | mix[eq] 4链共识; 目标3.59%nav(上限24%); 链: taoge6%、liuyiqing6%、a6586%、chong5000w6%
2026-10-13 - 14:00 | A-mix-eq | BUY | 601595 | 27.75 | 100 | day | 27.21 | - | mix[eq] 5链共识; 目标3.76%nav(上限22%); 链: lubenyuan6%、liuyiqing6%、a6586%、antoo6%、zhiyingjuexin6%
2026-10-13 - 14:55 | A-mix-eq | BUY | 601398 | 8.48 | 500 | day | 8.44 | - | mix[eq] 5链共识; 目标4.49%nav(上限29%); 链: qushitiange6%、lianghuaxiaohao6%、daxingdaxingdadangxing6%、stzhilang6%、chong5000w6%
2026-10-13 - 09:15 | A-mix-lhb | BUY | 001330 | 7.68 | 300 | day | 7.67 | - | mix[lhb] 3链共识(高权重1); 目标2.78%nav(上限16%); 链: liuyiqing10%、qushitiange6%、a6583%
2026-10-13 - 09:15 | A-mix-lhb | BUY | 002343 | 6.7 | 200 | day | 6.69 | - | mix[lhb] 2链共识(高权重1); 目标1.94%nav(上限20%); 链: liuyiqing10%、a6583%
2026-10-13 - 09:15 | A-mix-lhb | BUY | 601988 | 6.97 | 800 | day | 6.97 | - | mix[lhb] 6链共识(高权重1); 目标5.83%nav(上限26%); 链: xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 09:15 | A-mix-lhb | SELL | 002805 | 20.75 | 100 | day | 18.86 | - | mix[lhb] 卖v1: 持有它的 1 条导师链全部已出卖单: liuyiqing
2026-10-13 - 09:15 | A-mix-lhb | SELL | 600400 | 3.93 | 200 | day | - | - | mix[lhb] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-13 - 09:27 | A-mix-lhb | BUY | 601398 | 8.48 | 400 | day | 8.44 | - | mix[lhb] 4链共识(高权重1); 目标4.07%nav(上限22%); 链: stzhilang11%、daxingdaxingdadangxing7%、qushitiange6%、lianghuaxiaohao5%
2026-10-13 - 09:27 | A-mix-lhb | BUY | 601988 | 6.97 | 1100 | day | 6.97 | - | mix[lhb] 8链共识(高权重2); 目标8.29%nav(上限21%); 链: stzhilang11%、xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、qushitiange6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 10:00 | A-mix-lhb | BUY | 002692 | 5.19 | 500 | day | 5.24 | - | mix[lhb] 3链共识(高权重1); 目标2.97%nav(上限25%); 链: liuyiqing10%、chong5000w7%、taoge4%
2026-10-13 - 10:00 | A-mix-lhb | BUY | 601595 | 27.6 | 100 | day | 27.21 | - | mix[lhb] 4链共识(高权重1); 目标3.43%nav(上限22%); 链: liuyiqing10%、lubenyuan8%、antoo7%、zhiyingjuexin6%
2026-10-13 - 10:00 | A-mix-lhb | BUY | 601988 | 7 | 1300 | day | 6.97 | - | mix[lhb] 9链共识(高权重3); 目标9.35%nav(上限20%); 链: stzhilang11%、liuyiqing10%、xingjianye8%、lubenyuan8%、daxingdaxingdadangxing7%、zhiyingjuexin6%、qushitiange6%、xuanqiucaijing5%、lianghuaxiaohao5%
2026-10-13 - 11:00 | A-mix-lhb | BUY | 601595 | 27.25 | 100 | day | 27.21 | - | mix[lhb] 4链共识(高权重1); 目标3.42%nav(上限22%); 链: liuyiqing10%、lubenyuan8%、antoo7%、zhiyingjuexin6%
2026-10-13 - 14:00 | A-mix-lhb | BUY | 002692 | 5.19 | 600 | day | 5.24 | - | mix[lhb] 4链共识(高权重1); 目标3.48%nav(上限25%); 链: liuyiqing10%、chong5000w7%、taoge4%、a6583%
2026-10-13 - 14:55 | A-mix-lhb | BUY | 601398 | 8.49 | 500 | day | 8.47 | - | mix[lhb] 5链共识(高权重1); 目标5.06%nav(上限27%); 链: stzhilang11%、daxingdaxingdadangxing7%、chong5000w7%、qushitiange6%、lianghuaxiaohao5%
2026-10-14 - 09:15 | A-mix | BUY | 000823 | 22.32 | 100 | day | 22.32 | - | mix[main] 4链共识(高权重1); 目标3.37%nav(上限24%); 链: qushitiange13%、zhiyingjuexin7%、daxingdaxingdadangxing6%、xuanqiucaijing4%
2026-10-14 - 09:15 | A-mix | BUY | 002436 | 36.55 | 300 | day | 36.19 | - | mix[main] 11链共识(高权重1); 目标13.49%nav(上限24%); 链: qushitiange13%、zhiyingjuexin7%、chong5000w7%、antoo7%、daxingdaxingdadangxing6%、taoge4%、xuanqiucaijing4%、lianghuaxiaohao3%、bianbenling3%、a6583%、gaogailvfuli3%
2026-10-14 - 09:15 | A-mix | SELL | 001330 | 7.4 | 300 | day | - | - | mix[main] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-14 - 09:15 | A-mix | SELL | 002692 | 4.93 | 600 | day | 4.93 | - | mix[main] 卖v1: 持有它的 3 条导师链全部已出卖单: taoge、liuyiqing、a658
2026-10-14 - 09:15 | A-mix | SELL | 002805 | 18.11 | 100 | day | - | - | mix[main] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-14 - 09:15 | A-mix | SELL | 601118 | 7.23 | 400 | day | 7.3 | - | mix[main] 卖v1: 持有它的 2 条导师链全部已出卖单: daxingdaxingdadangxing、gaogailvfuli
2026-10-14 - 09:15 | A-mix-eq | BUY | 000823 | 22.32 | 100 | day | 22.32 | - | mix[eq] 4链共识; 目标2.64%nav(上限23%); 链: qushitiange6%、daxingdaxingdadangxing6%、xuanqiucaijing6%、zhiyingjuexin6%
2026-10-14 - 09:15 | A-mix-eq | BUY | 002436 | 36.55 | 400 | day | 36.19 | - | mix[eq] 11链共识; 目标17.54%nav(上限22%); 链: taoge6%、qushitiange6%、lianghuaxiaohao6%、a6586%、bianbenling6%、daxingdaxingdadangxing6%、gaogailvfuli6%、xuanqiucaijing6%、chong5000w6%、antoo6%、zhiyingjuexin6%
2026-10-14 - 09:15 | A-mix-eq | BUY | 002639 | 14.61 | 100 | day | 14.59 | - | mix[eq] 3链共识; 目标1.57%nav(上限18%); 链: bianbenling6%、xuanqiucaijing6%、zhiyingjuexin6%
2026-10-14 - 09:15 | A-mix-eq | BUY | 603968 | 14.38 | 100 | day | 14.36 | - | mix[eq] 3链共识; 目标2.27%nav(上限16%); 链: liuyiqing6%、xuanqiucaijing6%、zhiyingjuexin6%
2026-10-14 - 09:15 | A-mix-eq | SELL | 000710 | 11.15 | 100 | day | 11.1 | - | mix[eq] 卖v1: 持有它的 1 条导师链全部已出卖单: gaogailvfuli
2026-10-14 - 09:15 | A-mix-eq | SELL | 001330 | 7.4 | 300 | day | - | - | mix[eq] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-14 - 09:15 | A-mix-eq | SELL | 002212 | 8.18 | 300 | day | 7.58 | - | mix[eq] 卖v1: 持有它的 2 条导师链全部已出卖单: bianbenling、xingjianye
2026-10-14 - 09:15 | A-mix-eq | SELL | 002692 | 4.93 | 700 | day | 4.93 | - | mix[eq] 卖v1: 持有它的 3 条导师链全部已出卖单: taoge、liuyiqing、a658
2026-10-14 - 09:15 | A-mix-eq | SELL | 601118 | 7.23 | 400 | day | 7.3 | - | mix[eq] 卖v1: 持有它的 2 条导师链全部已出卖单: daxingdaxingdadangxing、gaogailvfuli
2026-10-14 - 10:00 | A-mix-eq | BUY | 002639 | 14.88 | 100 | day | 14.59 | - | mix[eq] 3链共识; 目标2.07%nav(上限21%); 链: lianghuaxiaohao6%、bianbenling6%、zhiyingjuexin6%
2026-10-14 - 09:15 | A-mix-lhb | BUY | 000823 | 22.32 | 100 | day | 22.32 | - | mix[lhb] 4链共识(高权重1); 目标3.37%nav(上限24%); 链: qushitiange13%、zhiyingjuexin7%、daxingdaxingdadangxing6%、xuanqiucaijing4%
2026-10-14 - 09:15 | A-mix-lhb | BUY | 002436 | 36.55 | 300 | day | 36.19 | - | mix[lhb] 11链共识(高权重1); 目标13.49%nav(上限24%); 链: qushitiange13%、zhiyingjuexin7%、chong5000w7%、antoo7%、daxingdaxingdadangxing6%、taoge4%、xuanqiucaijing4%、lianghuaxiaohao3%、bianbenling3%、a6583%、gaogailvfuli3%
2026-10-14 - 09:15 | A-mix-lhb | SELL | 001330 | 7.4 | 300 | day | - | - | mix[lhb] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-14 - 09:15 | A-mix-lhb | SELL | 002692 | 4.93 | 600 | day | 4.93 | - | mix[lhb] 卖v1: 持有它的 3 条导师链全部已出卖单: taoge、liuyiqing、a658
2026-10-14 - 09:15 | A-mix-lhb | SELL | 002805 | 18.11 | 100 | day | - | - | mix[lhb] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-14 - 09:15 | A-mix-lhb | SELL | 601118 | 7.23 | 400 | day | 7.3 | - | mix[lhb] 卖v1: 持有它的 2 条导师链全部已出卖单: daxingdaxingdadangxing、gaogailvfuli
2026-10-15 - 09:15 | A-mix | SELL | 002692 | 4.44 | 600 | day | - | - | mix[main] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-15 - 09:15 | A-mix-eq | SELL | 000710 | 10.56 | 100 | day | - | - | mix[eq] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-15 - 09:15 | A-mix-eq | SELL | 002212 | 7.38 | 300 | day | - | - | mix[eq] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-15 - 09:15 | A-mix-eq | SELL | 002692 | 4.44 | 700 | day | - | - | mix[eq] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-15 - 09:15 | A-mix-lhb | SELL | 002692 | 4.44 | 600 | day | - | - | mix[lhb] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-16 - 09:15 | A-mix | SELL | 002692 | 4 | 600 | day | - | - | mix[main] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-16 - 09:15 | A-mix | SELL | 300364 | 26 | 100 | day | 25.26 | - | mix[main] 卖v1: 持有它的 2 条导师链全部已出卖单: lubenyuan、bianbenling
2026-10-16 - 09:15 | A-mix | SELL | 601595 | 29.2 | 100 | day | 28.6 | - | mix[main] 卖v1: 持有它的 3 条导师链全部已出卖单: lubenyuan、bianbenling、antoo
2026-10-16 - 09:15 | A-mix | SELL | 601988 | 7.05 | 1300 | day | 7.05 | - | mix[main] 卖v1: 持有它的 4 条导师链全部已出卖单: xingjianye、daxingdaxingdadangxing、xuanqiucaijing、stzhilang
2026-10-16 - 09:15 | A-mix | SELL | 603533 | 30.17 | 200 | day | 29.01 | - | mix[main] 卖v1: 持有它的 1 条导师链全部已出卖单: antoo
2026-10-16 - 09:15 | A-mix-eq | BUY | 600812 | 6.57 | 300 | day | 6.57 | - | mix[eq] 2链共识; 目标1.99%nav(上限18%); 链: liuyiqing6%、zhiyingjuexin6%
2026-10-16 - 09:15 | A-mix-eq | BUY | 601811 | 25.58 | 100 | day | 25.58 | - | mix[eq] 2链共识; 目标3.54%nav(上限34%); 链: daxingdaxingdadangxing6%、zhiyingjuexin6%
2026-10-16 - 09:15 | A-mix-eq | SELL | 002692 | 4 | 700 | day | - | - | mix[eq] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-16 - 09:15 | A-mix-eq | SELL | 300364 | 26 | 100 | day | 25.26 | - | mix[eq] 卖v1: 持有它的 2 条导师链全部已出卖单: lubenyuan、bianbenling
2026-10-16 - 09:15 | A-mix-eq | SELL | 601595 | 29.46 | 100 | day | 28.6 | - | mix[eq] 卖v1: 持有它的 3 条导师链全部已出卖单: lubenyuan、bianbenling、antoo
2026-10-16 - 09:15 | A-mix-eq | SELL | 601988 | 7.05 | 1100 | day | 7.05 | - | mix[eq] 卖v1: 持有它的 4 条导师链全部已出卖单: xingjianye、daxingdaxingdadangxing、xuanqiucaijing、stzhilang
2026-10-16 - 09:15 | A-mix-eq | SELL | 603533 | 30.17 | 200 | day | 29.01 | - | mix[eq] 卖v1: 持有它的 1 条导师链全部已出卖单: antoo
2026-10-16 - 10:00 | A-mix-eq | BUY | 601811 | 25.62 | 100 | day | 25.58 | - | mix[eq] 2链共识; 目标3.44%nav(上限34%); 链: daxingdaxingdadangxing6%、zhiyingjuexin6%
2026-10-16 - 09:15 | A-mix-lhb | SELL | 002692 | 4 | 600 | day | - | - | mix[lhb] 卖v1: 已无任何导师链持有(前几日已卖光), 按昨收挂卖
2026-10-16 - 09:15 | A-mix-lhb | SELL | 300364 | 26 | 100 | day | 25.26 | - | mix[lhb] 卖v1: 持有它的 2 条导师链全部已出卖单: lubenyuan、bianbenling
2026-10-16 - 09:15 | A-mix-lhb | SELL | 601595 | 29.2 | 100 | day | 28.6 | - | mix[lhb] 卖v1: 持有它的 3 条导师链全部已出卖单: lubenyuan、bianbenling、antoo
2026-10-16 - 09:15 | A-mix-lhb | SELL | 601988 | 7.05 | 1300 | day | 7.05 | - | mix[lhb] 卖v1: 持有它的 4 条导师链全部已出卖单: xingjianye、daxingdaxingdadangxing、xuanqiucaijing、stzhilang
2026-10-16 - 09:15 | A-mix-lhb | SELL | 603533 | 30.17 | 200 | day | 29.01 | - | mix[lhb] 卖v1: 持有它的 1 条导师链全部已出卖单: antoo
```

## 回演末日 Hedge 乘子(h_after, 归一)

| 链 | h |
|---|---|
| A-stzhilang | 13.79% |
| A-qushitiange | 11.61% |
| A-daxingdaxingdadangxing | 9.16% |
| A-lubenyuan | 8.81% |
| A-chong5000w | 8.41% |
| A-xingjianye | 7.96% |
| A-zhiyingjuexin | 7.43% |
| A-liuyiqing | 4.64% |
| A-taoge | 4.55% |
| A-gaogailvfuli | 4.08% |
| A-cb | 3.74% |
| A-bianbenling | 3.73% |
| A-antoo | 3.08% |
| A-lianghuaxiaohao | 3.00% |
| A-a658 | 3.00% |
| A-xuanqiucaijing | 3.00% |
