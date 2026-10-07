---
name: lubenyuan-skill
description: "卢本圆复盘(B站 mid=550494308, 投稿273条/22.7万粉): ①persona(冷启动) ②sum: 视频产物按发布时刻五锚点路由挂载 md(盘前/早盘/午间/下午盘/复盘区, append 不固定模板槽)+markSummarized ③distill: md ####卢本圆 小节→persona 核销+沉淀(哨兵 DISTILL_OK, 5 天/会话批量降序)。签名「持仓透明充电是交割单」=晨报型实盘选手。按任务读 workflows/ 对应文件。2026-10-07 拼音全名立法更名(原 lby-skill)+目录结构化。"
---

# lubenyuan-skill · 卢本圆复盘

> 2026-10-05 建线; 10/7 拼音全名立法更名(原 lby-skill) + 目录结构化(sum/distill 下沉 workflows/)。
> 定位: B 站导师线之一(桃哥=情绪周期/趋势天哥=趋势视角/卢本圆=**盘中实战+持仓透明**)。

## persona（persona/, 冷启动）

- rules.md: 样本≥2 准入, 同 taoge 纪律
- profile.md: 近两月 10/10 条全为北京 8 点档晨报（时区坑: pubdate+8h 才是北京时间, toISOString 是 UTC）
- 未来接独立决策链（多决策者架构立法）+ 成长触发器同全局

## 路由表（按任务读对应文件）

| 任务 | 读 |
|---|---|
| 合成视频产物进 md | `workflows/sum.md`（五锚点挂载路由是本 skill 核心差异） |
| 核销+沉淀 persona | `workflows/distill.md`（已建: 克隆 qushitiange 骨架落地, L 系规则锚点积累制, 主料=持仓披露+交割单） |

## 上下游

- 上游 `bilibiliVideoHandler`(quartz, cron `0 0/30 7-22 * * ?`——10/7 定稿: 晨报型主峰北京 8 点档, 7:00 起留 1h 缓冲, 尾 22:30 覆盖更早样本的晚间习惯; 恢复发稿后按 sys_job_log 实发再收窄), param `--mid 550494308 --name 卢本圆复盘`
- 盘中时段稿的价值 = 当日 slot 链的 12:30/14:00 确认点可引用（晚于 09:45 的稿只对下午 slot 有增量）
- 双副本: 编辑后 `node scripts/sync_skills.mjs`
