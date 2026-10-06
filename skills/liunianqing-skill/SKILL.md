---
name: liunianqing-skill
description: "刘念青(同花顺投资账本 ledger=liunianqing)人格画像与决策规则——10/5 建线, 原料 297 条流水/340 腿。md 硬数据层已全历史回填(见 md 各日 #### 刘念青 小节); persona 由 tzzb-distill --ledger liunianqing 逐日沉淀; 混合型选手(非纯转债), buchitudou0-skill 不适用。"
---

# liunianqing-skill · 刘念青(2026-10-05 建线)

> 拆自原 早期聚合库(已拆) 聚合库(10/6 用户裁决: 样本量充足, 每人独立 skill)。
> 防串扰纪律: 只读本人小节+本人 persona; 画像未建=留白, 严禁借用土豆 cb 画像/其他高手风格。

## persona(persona/)

- rules.md: 规则三态(待验证/md 验证/已证伪), 通用四区(市场/入场/出场/仓位), 证据锚点+样本≥2 准入
- profile.md: 行为统计(开仓节奏/持仓时长/时段偏好/仓位口径)
- cases.md: 反常操作立案(反例优先)
- language.md: 语言指纹(如账本备注/昵称黑话)

## 上下游

> **架构方向(10/6 用户立法)**: 本 skill 未来接**独立决策链**(workflows/chain.md, 与 taoge-skill 同构; 七步暂定); persona 攒厚后启动。成长触发器: rules.md>15KB 建索引+references/ 放溯源全文。

上游 tzzbFetchHandler(cron 0 10 15-23)→fetch_tzzb(全账本)→tzzb-sum(硬数据+【推测】层写 md)；
沉淀=tzzb-distill --ledger liunianqing；输出供 chain 01 facts 加权(先例 fage C12)。
