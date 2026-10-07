# tzzb 账本来源与选拔规则（references/ledgers.md, 2026-10-07 建档/晚二改审阅版）

> 机器可读版=`scripts/tzzb/tzzb_ledgers.json`。⚠**本表为待用户复核的终稿候选**——json 已按此改（可回滚：信阳谷神一条命令加回；鳄狼King 若否决则出列仅留档案）。
> 直查链接点开=该账本当日流水 JSON（`position_change_by_share` 端点，浏览器直接看）。

## 六个比赛（key → 名称）

| key | 中文名 | 备注 |
|---|---|---|
| joonDP3 | 板块必读&桃粉杯第二届 | 805 人主力场（土豆 rank3/刘忆青 rank1/A658 rank2） |
| yNkQm2X | 待补 | 负例主源场（窗口最长 2025-09 起） |
| 73xX2pt | 待补 | 大兴/宣秋/信阳谷神场（窗口 2026 起） |
| 7CK72My | 待补 | 高概率复利场 |
| yDYm2oX | 待补 | 量化小号实验场 |
| wXNp67m | 待补 | 边学本领边实践场 |
| CM3ntt2 / Yp6WWwx | （发现未采用） | _ranks 有榜未选人 |

> 名称待补原因: article 端点名未破译（article_ex/article_by_share 均不返回 title）; H5 页面有名字，下次会话补。

## 窗口审计结论（10/7 晚实测）

每 ledger 当前 key **均为最大样本窗口** ✓（lianghuaxiaohao 187=187 天、bianbenling 182=182 天跨场完全一致；其余 14 条 enter_date 即最早场）。**无需换 key**，10/7 换早视图已做对。

## 负例终稿候选（分层制, 待用户点链接复核）

| 档 | 选手 | 实证 | 战绩 | 直查 |
|---|---|---|---|---|
| 大亏(挖掘主力) | 买入太急 mairutaiji | 750 笔/768 腿/237 日 ✓已入库 | rank971, **-98%**, 满仓 | [链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=yNkQm2X&user_key=147086) |
| 大亏 | 护卫港 huweigang | 2000 笔/2245 腿（最活跃） | rank962, -90% | [链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=yNkQm2X&user_key=142875) |
| 大亏 | 洋大人 yangdaren | 723 笔/260 日 | rank968, -95% | [链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=yNkQm2X&user_key=140544) |
| 中亏 | 猎人IH liurenih | 596 笔/681 腿 | rank873, -57% | [链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=yNkQm2X&user_key=232343) |
| **小亏对照组** | 鳄狼King elangking | fetch 进行中（-10% 档典型: 满仓活跃） | rank498, **-10.3%**, 持仓 100% | [链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=73xX2pt&user_key=237800) |

**分层逻辑**: 大亏=禁手规则挖掘主力（错误惩罚大→信号清晰）; 中亏=补充; **小亏=对照组**——验证挖出的禁手规则不会误伤正常回撤（小亏行为常与正例重叠，规则若把小亏行为也否决=假阳性）。持续性偏好: 跨场一致亏损（f1l1y2 双场尾部 -98%/-82%）>单场深亏; f1l1y2 列备选第一顺位（[链接](https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/position_change_by_share?key=yNkQm2X&user_key=145263)）。

**出列（已彻底删除, 10/7 用户裁决不留档）**: 信阳谷神——四场收益恒 -73.16%（半死账户）+198 笔最不活跃; json/downloads/DB(476 行)已全删, 防未来看到一头雾水。回滚=按 _ranks 榜单重新选入+fetch。

## 正例 11 人（kind=pos, 已带注源字段 rank/rate_pct/entered）

有榜数据的 8 人 rank = 1,1,1,2,3,4,13,17 **全部 ≤20** ✓（前三闸之排名闸全过）; 量化小号/边学本领/宣秋/冲5000w 四人榜行未匹配 user_key 待补验。

## 选正例三闸（10/7 定稿）

1. **排名闸**: 每场比赛各自总榜（官方综合排名≈总收益, 不分合并）前 20 → 全进观察池（速览 ⏳ 低权档）
2. **证据量闸**: 出手日 ≥30 且 legs ≥100（转正条件）
3. **持续性闸**: 期间收益/参赛交易日 ≥0.15%/日 **或** 参赛 ≥120 日且总收益 ≥25%（0.75%/日 阈值已否决——土豆 0.26%/日会被自己毙掉）

宽进严出: 加权消费的是转正正例; 观察池人数不限。
