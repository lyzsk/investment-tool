# qushitiange-skill · distill 工作流（核销+沉淀）

> 路由来源: SKILL.md。触发: 每晚 check md 链(taoge 两棒之后); 或用户喊"核销趋势天哥"。

## 定位

读当日 md `#### 趋势天哥` 小节, 把可复用的东西沉淀进 `skills/qushitiange-skill/persona/`。
**信息截止铁律**同 taoge distill: 只允许 ≤ 目标日期的素材, 禁止马后炮。

## 流程(两步, 同 taoge distill, 差异=目标小节与 persona 目录)

0. **读素材包(10/17 A14②, 零 token)**: 会话开头一次 Bash `scripts/venv/Scripts/python.exe -X utf8 scripts/md/build_distill_pack.py --skill qushitiange --date <日1>,<日2>,...`, 每天先 Read `downloads/distill_pack/<目标日>/qushitiange.md`(当天小节/收评+同票行/近 5 天同票记录/同票规则全文+待验证索引/画像目录); 包里有的不再自己 grep/cat, 标"未展开/截断"的按行号补读; 脚本失败=照旧读原件。
   - 10/17 晚起: 每个目标日的收评等公共部分不再放进本人包, 在同目录 `downloads/distill_pack/<目标日>/_common.md`(需要大盘背景时读一次)
1. **核销**: `skills/qushitiange-skill/persona/rules.md` 中 `[待验证]` 规则 vs 目标日期 md(收评/涨停分析/电报区)——兑现改 `[md 验证 YYYY-MM-DD]`+样本+1+验证记录; 打脸改 `[已证伪]` 不删+cases.md 立案; 未触发不动。
2. **提取**: 小节 bullets 分流——大盘/操作→profile.md(行为统计); 提及个股(带态度)→rules.md 对应区(A市场/B买/C卖/D仓); 画面增量只沉淀看盘习惯; 规则沉淀→rules.md 主战场(初始 `[待验证]`); 误判/踏空/检讨→cases.md 立案(格式同 taoge-skill: 背景/判断/结果/自我归因/人格增量)。

## 纪律(同 taoge distill 六条)

1. 新增/修改必带证据锚点(日期+原话短句), 引不出原文不入库
2. 冲突不删, 标 `[已失效-市况变迁 YYYY-MM-DD]`
3. 改任一 persona 文件必须在其修订记录追加一行
4. 单样本也可进 rules.md(标 [单样本], 时间状态=待复核; 之后兑现升级、打脸降级; 10/18 用户定 R27: 我们是来赚钱的); 同时在 cases.md 记一条案例卡
5. 无可沉淀内容(空小节/未发稿日)是正常结果, 不硬凑
6. 结束时 stdout 末行哨兵: `DISTILL_OK {日期}`
7. 输出纪律(10/17 A14③): persona 只写变更/新增条目, 不整段重写、不复述 md 原文(锚点=日期+≤30 字原话); 用 Edit 局部改, 不用 Write 整文件重写; 最终回复每天只列改动清单 + 哨兵
8. 规则时间状态(10/17 晚用户批): 每条规则头下第一行是 `- **时间状态**: 建立 YYYY-MM-DD · 最后验证 YYYY-MM-DD · 状态 活跃|待复核|已否定(...)`(列表式规则写成下一行缩进子项 `  - 时间状态: ...`)。新增规则→写这一行(建立=目标日, 最后验证=最近证据日); 本次核销兑现或打脸了某条→把它的「最后验证」改成目标日; 导师的新做法否定了旧规则→旧规则**不删不改正文**, 只把状态改成 `已否定(YYYY-MM-DD, 由 Rxx 取代)`, 新做法另起一条; 活跃/待复核两态由 scripts/md/rule_time_state.py 每晚按最近证据日机械刷新, 不用手改。
