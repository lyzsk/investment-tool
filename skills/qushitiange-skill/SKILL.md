---
name: qushitiange-skill
description: "趋势天哥(B站 mid=1372241958, 投稿524条): ①persona(冷启动) ②sum: 合成视频产物→md #### 趋势天哥 小节+markSummarized ③distill: md 小节→persona 沉淀(哨兵 DISTILL_OK)。2026-10-05 建线; 10/7 拼音全名立法更名(原 qstg-skill)+目录结构化。按任务读 workflows/ 对应文件。"
---

# qushitiange-skill · 趋势天哥

> 定位: B 站导师线之一(桃哥=情绪周期/卢本圆=盘中实战/趋势天哥=**趋势视角**——名字即方法论)。
> 与 taoge-skill 同构但**冷启动**: 0 个已处理视频, 0 条规则。所有管线 = 最小可用版, 样本攒起来后再对齐桃哥线的完整度(技术快照管线/统计画像/IC 记分都未建, 见 TODO)。
> 2026-10-07: 拼音全名立法更名(原 qstg-skill) + 目录结构化(sum/distill 下沉 workflows/)。

## persona 目录(由 distill 工作流维护)

- `persona/rules.md` — 决策规则(初始=空骨架, 样本≥2 才准入, 同 taoge 纪律)
- `persona/profile.md` — 行为统计画像
- `persona/cases.md` — 误判/神操作立案(一等公民)
- `persona/language.md` — 语言指纹

## 路由表（按任务读对应文件）

| 任务 | 读 |
|---|---|
| 合成视频产物进 md | `workflows/sum.md` |
| 核销+沉淀 persona | `workflows/distill.md` |

## 上下游

> **架构方向(10/6 用户立法)**: 本 skill 未来接**独立决策链**(workflows/chain.md, 与 taoge-skill 同构; 七步暂定); persona 攒厚后启动。成长触发器: rules.md>15KB 建索引+references/ 放溯源全文。

- 上游: `bilibiliVideoHandler`(quartz, cron `0 30 16-23 * * ?`——10/7 定稿: 发布习惯平均比桃哥晚 1-2 小时, 桃哥窗 15:30 起故本线 16:30 起步留缓冲, 尾同桃哥 23:30; 观察 2 周实发后收窄), param `--mid 1372241958 --name 趋势天哥` → 下载→ASR→视觉 → `results/bilibili/1372241958/<yyyy.MM.dd>/`
- 每晚 check md 链把本 skill 两棒排在 taoge 两棒之后(同一批产物目录, 顺手)
- 双副本: 编辑后 `node scripts/sync_skills.mjs`
