---
name: tzzb-skill
description: "Use when 处理同花顺投资账本高手数据(六 ledger): ①sum=合成每日操作进 md(gen_tzzb_md 硬数据层零token + LLM 补【推测】层) ②distill=反向沉淀 persona(土豆=机械统计+五闸门→buchitudou0-skill; 五人=LLM 提取→各自 <ledger>-skill)(每日15:10抓取后/每晚 check md 链/用户喊合成或核销时; 按任务读 workflows/ 对应文件, 不全文载)"
---

# tzzb-skill · 投资账本高手数据处理（sum+distill 统一入口）

> 2026-10-07 合并: tzzb-sum + tzzb-distill → 本 skill。目录结构立法: **SKILL.md 只做路由, 工作流全文在 workflows/ 按需载入**(防上下文爆炸)。

## 路由表（按任务读对应文件）

| 任务 | 读 | 一句话 |
|---|---|---|
| 合成某高手当日 md 小节 | `workflows/sum.md` | 硬数据层(脚本, 零token) + 【推测】层(LLM, 逐条锚点) → `#### <高手名>` |
| 核销 + 沉淀 persona | `workflows/distill.md` | 土豆=机械统计+五闸门→buchitudou0-skill; 五人=LLM 提取→`<ledger>-skill` |

## 上下游与标识

- 上游 `tzzbFetchHandler`(quartz, cron `0 10 15-23 ? * *`, hasNavDay 幂等): fetch_tzzb.mjs → `downloads/tzzb/<ledger>/` → sync 入 `tzzb_record` 表
- 高手清单 `scripts/tzzb/tzzb_ledgers.json`; **skill 名 == ledger id**（10/7 命名立法: liuyiqing/lianghuaxiaohao/a658/bianbenling/xingjianye 各自 `<ledger>-skill`; buchitudou0 同律(10/7 用户纠正: K3 原拼 bchitudou0 丢 u, 全链已正名; 转债特化形态保留=persona/buchitudou0/ 子层+references/api.md)）; lianghuaxiaohao 产出一律标"(程序化嫌疑)"
- 过程账: 本目录 `PROCESS.md`（跑批/格式变更/立法/事故各追加一行）

## 纪律（两条工作流共用）

1. **双副本防漂移**: 本目录是 canonical; headless claude 加载 `.claude/skills/tzzb-skill/`, **编辑本目录任何文件后跑 `node scripts/sync_skills.mjs`**（2026-10-07 起替代逐文件手工 cp）
2. 硬数据层数字禁止手改（要改就改脚本重跑）; 不改 downloads/ 任何文件; 不直接写 DB; 实盘隐私立法（用户自己的成交/账户明细永远不进 md）
