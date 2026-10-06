# qushitiange-skill · distill 工作流（核销+沉淀）

> 路由来源: SKILL.md。触发: 每晚 check md 链(taoge 两棒之后); 或用户喊"核销趋势天哥"。

## 定位

读当日 md `#### 趋势天哥` 小节, 把可复用的东西沉淀进 `skills/qushitiange-skill/persona/`。
**信息截止铁律**同 taoge distill: 只允许 ≤ 目标日期的素材, 禁止马后炮。

## 流程(两步, 同 taoge distill, 差异=目标小节与 persona 目录)

1. **核销**: `skills/qushitiange-skill/persona/rules.md` 中 `[待验证]` 规则 vs 目标日期 md(收评/涨停分析/电报区)——兑现改 `[md 验证 YYYY-MM-DD]`+样本+1+验证记录; 打脸改 `[已证伪]` 不删+cases.md 立案; 未触发不动。
2. **提取**: 小节 bullets 分流——大盘/操作→profile.md(行为统计); 提及个股(带态度)→rules.md 对应区(A市场/B买/C卖/D仓); 画面增量只沉淀看盘习惯; 规则沉淀→rules.md 主战场(初始 `[待验证]`); 误判/踏空/检讨→cases.md 立案(格式同 taoge-skill: 背景/判断/结果/自我归因/人格增量)。

## 纪律(同 taoge distill 六条)

1. 新增/修改必带证据锚点(日期+原话短句), 引不出原文不入库
2. 冲突不删, 标 `[已失效-市况变迁 YYYY-MM-DD]`
3. 改任一 persona 文件必须在其修订记录追加一行
4. 单次怪操作只进 cases.md, 样本≥2 才进 rules.md
5. 无可沉淀内容(空小节/未发稿日)是正常结果, 不硬凑
6. 结束时 stdout 末行哨兵: `DISTILL_OK {日期}`
