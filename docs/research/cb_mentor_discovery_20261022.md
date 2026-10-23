# 转债导师发现（不吃土豆0 线 第 2、3 名）· 2026-10-22

> 状态：**第一段（离线初筛）已完成；第二段（联网看流水）没跑**。原因：副线请求守护 `scripts/tzzb/tzzb_guard.py` 规定 09:00~15:10 不发同花顺请求（用户令），15~23 点每小时 :05~:30 还要让给正式轮次，所以最早 **15:30** 才能发请求；本 agent 13:15 开工，90 分钟时限到 14:45，赶不上。
> 本次没有入库，没改代码，没写业务库或行情库，**同花顺请求一次都没发**（只做了 `--dry`，不联网）。

## 1. 方法

1. **榜单去重**：10 场比赛的缓存榜单 `downloads/tzzb/_ranks/*.json` 共 9651 行。按昵称（去掉空格）去重，得到 4827 人。
   - 没用 win_rate/trans_time/max_hc 指纹去重：这几个字段在 nav 端点里，离线拿不到。
   - 打码昵称（如 `liu****ng002`）可能把两个人并成一个，第二段用 nav 指纹复核。
2. **活跃**：只有 10/17 拉的 4 场（KCk2q2o / QmyNC3q / XfDymq2 / wqNOWPc）能看到 10/15 之后的 update_time；10/7 拉的 6 场最多只到 9/30。
   → 离线只能做到"10/15~10/16 还在更新"。**"10/19 之后还在更新"必须第二段联网核实。**
3. **样本够长**：入场日 ≤ 2026-08-31（≥ 约 35 个交易日）。
4. **转债先验（第一性原理）**：榜单行里没有任何品种字段，看不出谁做转债。但转债是 T+0，可以当天买当天卖、收盘空仓；股票是 T+1，当天买的票收盘前卖不掉。
   → 所以**活跃 + 每个快照收盘仓位都 = 0** 的人，大概率在做 T+0 品种（转债、T+0 ETF），或者纯粹空仓。可用快照两个：9/30 收盘（10/7 拉的）、10/16 收盘（10/17 拉的）。
   - 土豆两个快照都是 0。
5. **先验校验**（拿本地已有流水的 60 人对一下，见 `scripts/temp/cb_disc_1022/validate_prior.py`）：
   - 仓位一直为 0 的 5 人里：
     - 1 人纯转债 T：土豆；
     - 1 人只有转债卖腿：若曦deep，是打新债上市卖出，不是 T；
     - 3 人转债为 0：ST之狼 等。
   - 其余 55 个仓位不为 0 的人里，转债占比 ≥30% 的只有高概率（46%）一个。
   - → 这个先验能把命中率从约 2% 提到约 20%（样本极小），**但会漏掉高概率这种股债混做、隔夜持仓的人**。

## 2. 漏斗

| 步骤 | 人数 |
|---|---|
| 10 场榜单行 | 9651 |
| 按昵称去重 | 4827（其中已在库 25） |
| update_time ≥ 10/15（只在 10/17 那 4 场里能判断） | 1700 |
| 入场 ≤ 08-31 | 1358 |
| 每个快照收盘仓位都 = 0 | 153（两个快照都有的 68） |
| 去掉已在库（土豆、ST之狼） | 151 → `downloads/tzzb/_discovery_20261022/flat_active_pool.json` |
| 总收益 > 0 | 66；> 20% 的有 20 |
| **第二段待查（按总收益取前 15）** | 15 → `stageA_cands.json` |
| 有转债 / 近 3 日更新 / 样本够 | **未知（第二段没跑）** |

## 3. 本地已有数据里的转债人（不用新请求）

逐笔腿 FIFO 配对，不含费用，脚本 `scripts/temp/cb_disc_1022/analyze_cb.py`，结果 `downloads/tzzb/_discovery_20261022/baseline_local.jsonl`：

| 人 | 转债占比 | 转债出手日 | 逐笔腿 | 回转数 | 回转胜率 | 每笔均值 | 日内占比 | 9 月以来 | 买点 | 卖点 |
|---|---|---|---|---|---|---|---|---|---|---|
| 不吃土豆0（基准） | 100% | 157 | 940 | 457 | 56.2% | +0.35% | 100% | 37 笔 / 胜 70% / +0.78% | 竞价 09:25 106 笔，09:30 179 笔 | 09:30~09:45 443/457 |
| 高概率复利（已在库，对照） | 46% | 55 | 484 | 163 | 68.7% | +0.84% | 44% | 77 笔 / 胜 70% / +1.54% | 10:00 后 241/300 | 分散，下午最多 |
| 东橙西柚13（cand1018_01） | 8.5% | 9 | — | — | — | — | — | 最后一次转债 08-28 | | |
| 若曦deep（cand1018_20） | 33% | 4 | — | — | — | — | — | 4 条全是打新卖出 | | |

本地 60 人里，除了已在库的两位，**没有第三个合格的转债人**。

## 4. 第二段待查名单（15 人，每人都还没确认做不做转债）

- 链接格式取自 `scripts/tzzb/fetch_tzzb.mjs:366` 的 homeUrl，手机可直接打开（api.md 里的入口页同款）。
- "总收益"取该人各场里的最大值，"入场"取最早一场；"视图"选 10/17 那 4 场里最新、入场最早的一场。

| # | 昵称 | 视图 key / user_key | 链接 | 入场 | 总收益 | 两个快照仓位 | 出现场数 |
|---|---|---|---|---|---|---|---|
| 00 | 毫无规律可言 | wqNOWPc / 203813 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=203813 | 02-09 | +111.9% | 0 / 0 | 7 |
| 01 | 小帅1113 | XfDymq2 / 201893 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=201893 | 02-03 | +91.4% | — / 0 | 1 |
| 02 | 渡尽朝安 | wqNOWPc / 268527 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=268527 | 08-04 | +76.0% | 0 / 0 | 3 |
| 03 | 可莉重度依赖KFc | wqNOWPc / 168725 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=168725 | 12-23 | +58.5% | 0 / 0 | 2 |
| 04 | liu****ng002 | wqNOWPc / 171815 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=171815 | 12-30 | +57.8% | 0 / 0 | 6 |
| 05 | patience99 | wqNOWPc / 215831 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=215831 | 03-23 | +54.7% | 0 / 0 | 2 |
| 06 | 左右天下无敌 | wqNOWPc / 168908 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=168908 | 12-23 | +50.2% | 0 / 0 | 3 |
| 07 | me_486251149315 | wqNOWPc / 204438 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=204438 | 02-12 | +47.1% | — / 0 | 1 |
| 08 | 做以待币0012 | XfDymq2 / 265415 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=265415 | 07-06 | +46.5% | 0 / 0 | 3 |
| 09 | A股小小小泥鳅 | XfDymq2 / 177677 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=177677 | 01-05 | +44.3% | 0 / 0 | 5 |
| 10 | Cycle0212 | XfDymq2 / 174780 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=174780 | 01-03 | +42.7% | — / 0 | 2 |
| 11 | 夏火i | QmyNC3q / 184152 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=QmyNC3q&user_key=184152 | 01-07 | +41.8% | 0 / 0 | 2 |
| 12 | 圣馒头 | XfDymq2 / 137859 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=137859 | 2025-09-25 | +40.0% | 0 / 0 | 2 |
| 13 | 芙奥斯 | wqNOWPc / 177882 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=wqNOWPc&user_key=177882 | 01-05 | +35.4% | 0 / 0 | 10 |
| 14 | A牛气冲天kungr | XfDymq2 / 182274 | https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=XfDymq2&user_key=182274 | 01-06 | +35.2% | — / 0 | 2 |

各人所有场次的视图都在 `flat_active_pool.json` 的 `views` 字段里。另外，`套利皇 / 兰板套利 / 套利格子间` 这类名字带"套利"的人收益都 ≤ +6% 或为负，没放进名单。

## 5. 第二段怎么跑（15:30 后，不用改代码）

```
scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/rank_screen.py fetch-light --cands downloads/tzzb/_discovery_20261022/stageA_cands.json --wait
scripts/venv/Scripts/python.exe -X utf8 -I scripts/temp/cb_disc_1022/analyze_cb.py downloads/tzzb_cand/disc1022_00 ... downloads/tzzb_cand/disc1022_14
```

**请求怎么限：**
- 走 rank_screen.py → rank_monthly.mjs 浏览器代发，请求间隔约 2 秒 ±25%。
- 共用正式额度和熔断（tzzb_guard）；遇到 403 自动写 ban 并停到次日。
- 每人 1 次净值 + 最多 4 页流水，**一共不超过 78 次**（已 `--dry` 验证 15 人 / 估算 ≤75 + 开页 3）。

**产物位置：**
- 现成封装没有 `--root` 透传，产物会落在 `downloads/tzzb_cand/disc1022_XX/`。都是新目录，不覆盖任何导师目录。
- 跑完复制到 `_discovery_20261022/`。

**判定门槛**（看最近 200 行流水 + nav）：
- 转债占比 ≥ 50%；
- 转债出手日 ≥ 20（200 行盖不全的，按 max_count 外推后再标注）；
- 最后一次转债成交日 ≥ 10-19，nav 最后日期 ≥ 20261019；
- 剔除只有清仓腿的打新债户；
- 转债行里 buy_sell=9（做T）占比高的，标"日内 T / 像土豆"。

**收益的代理指标**：账户日胜率、近 30 日日均、max_hc、nav 的 win_rate。纯转债户（占比 ≥80%）的账户日胜率约等于转债胜率。

**逐笔腿回转胜率**要拉 change_bs（每只转债 1~2 次请求）。现成的 fetch_tzzb.mjs 账本模式会顺带全量 day_positions、全部非转债标的，单人可达几百次，并且走它自己 root 的额度（绕开正式守护）。所以**留到用户拍板后 onboard 时再拉**，不在发现阶段做。

**第一批命中不到 2 人时**：取 `flat_active_pool.json` 第 16~30 名再跑一批（≤78 次），两批合计 ≤160，在 300 以内。

## 6. 不自信点

1. **"收盘仓位 = 0 ⇒ 做 T+0 品种"这个先验只校验了 5 个样本**，命中 1 个。另外有 3 个仓位为 0 的人其实是空仓或短线股票户（如 ST之狼）。第一批 15 人里可能 0~4 人真做转债，置信 40%。
2. 这个先验**结构性漏掉股债混做、隔夜持债的人**（高概率就是）。如果用户想要的是"高概率型"的第 3 名，这条路径找不到，需要另想先验，比如对 10/17 那 4 场高收益非空仓的人抽样。
3. 9/30 是国庆节前最后一个交易日，很多人节前清仓，所以 9/30 快照为 0 的说服力弱；只有 10/16 一个快照为 0 的人（01/07/10/14）可信度更低。
4. 按昵称去重：打码昵称可能误并；同名的不同人会被当成一个。
5. "近 3 日更新"离线最多只能证明到 10/16。缓存是 5 天前的，期间有人退赛或停更都看不到。
6. 榜单的 total_profit_rate 是"各比赛窗口内收益"，不同场窗口不同，取最大值会偏向入场早的视图。
