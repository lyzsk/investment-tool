---
name: taoge-sum
description: "Use when 合成桃哥B站视频产物进 stocks md: 读 results/bilibili/<mid>/<日期>/ 的 txt+vision.json 写 ### 桃哥 小节, 并推进状态机 VISION_DONE→SUMMARIZED(每晚跑批后/用户喊合成桃哥视频时)"
---

# 桃哥视频产物合成(状态机最后一棒)

上游 `bilibiliVideoHandler`(quartz, cron 0 30 15-23 * * ?)已完成:
发现(INSERT step=NEW) → 下载(mp4+m4a+json → source_files, step=DOWNLOADED)
→ 直链 process_video.py(ASR→纠错→视觉→聚合 → results/, step=VISION_DONE)。

本 skill = 把 VISION_DONE 的产物消化进 stocks md, 然后推进 SUMMARIZED。
**这是状态机最后一棒: 不推进, 30 天物理删除永不触发, downloads/ 会膨胀。**

## 纪律(不可违反)

1. **AI 写库必须走 controller**: 推进只准 curl `POST /api/bilibili/video/markSummarized`,
   禁止手写 SQL 改 DB; curl 不通(spring 没跑)就报告用户, 不许绕过
2. **幻觉防控**: 只写产物文件里有的信息; 产物缺就标注缺失, 绝不脑补内容
3. **股票代码以 OCR/多帧投票为准**(VLM 会编代码: 金健米业→600193, 真 600127),
   对不上的代码标 `[?]`, 不猜
4. 不改 downloads/ 任何文件, 不删任何文件; results/ 是永久档案只读
5. `### 桃哥` 小节内容只可能是本 skill 的产出, 合成即整小节覆盖(幂等), 无需任何标记

## 步骤

### 1. 发现待合成列表

```bash
curl -s localhost:8888/api/bilibili/video/pendingSummary
# Result.data = VISION_DONE 且 retry_count<3 的行: bvid/title/authorMid/publishTime
```

空列表 = 没活, 直接结束(先确认上游 job 跑过: sys_job_log 看 bilibiliVideoHandler 回执)。

### 2. 逐视频定位产物 + 三态判定

产物目录: `results/bilibili/<authorMid>/<发布日 yyyy.MM.dd>/`(发布日=publishTime 的日期部分)

| 文件 | 角色 |
|---|---|
| `<bvid>.txt` | 纠错后口述全文, **主原料** |
| `<bvid>.vision.json` | 画面产物, 含 pages 段(页面时间轴/注意力榜/BS买卖点/持仓快照/自选股清单/紫色持仓) |
| `<bvid>.raw.txt` / `.tsv` | 原始转写/时间戳, 仅参考不直接引用 |

三态(幻觉防控核心):
- **态1 全齐**(txt + vision.json 含 pages): 正常合成, 口述+画面两段都写
- **态2 仅 txt**(仅 CPU 机器跑过 asr,correct, 视觉留待): 只整合口述, md 小节开头标注
  `> ⚠️ 画面产物缺失(仅CPU管线), 本节无视觉信息` — 可以合成, 信息缺口显式化
- **态3 连 txt 都没有**: **不合成不脑补**, 把缺失清单报给用户(查 sys_job_log 失败原因), 结束

### 3. 合成写 md

挂载点: `stocks/<year>S<quarter>/<发布日 yyyy-MM-dd>.md` 的 `## 复盘` → `### 桃哥` 小节
(桃哥只在交易日盘后发稿, 挂发布日当天; quarter=(月-1)/3+1, 9月=S3)

小节结构:
```markdown
### 桃哥

[视频标题](https://www.bilibili.com/video/<bvid>) (<publishTime>)

#### 解读
- 大盘判断: ...(txt 里的原意, 引用不转述失真)
- 提及个股: 名称(代码) — 他的态度/操作
- 操作: 今天买/卖/埋伏了什么
- 明日策略: ...

#### 画面   ← 仅态1
- BS买卖点: ...(vision.json pages.bs_points, 价位需多帧一致或命中口述才采信)
- 注意力榜: ...(驻留秒排序, =他视线重心, 可与口述对照出"沉默持仓")
- 持仓/自选股: ...(紫色高亮=持仓∪当日成交; 口述未提但画面出现的票=重要增量)
```

- `### 桃哥` 小节只可能是 AI 产出 → 已存在就直接整小节覆盖(幂等重合成)
- md 文件不存在(非交易日/没预建) → 报告, 不新建(挂载归口是 cls 域的职责)

### 4. 推进状态机(只推合成成功的)

```bash
curl -X POST localhost:8888/api/bilibili/video/markSummarized \
  -H "Content-Type: application/json" -d '["<bvid1>","<bvid2>"]'
# 回执: "推进SUMMARIZED x/跳过 y(非VISION_DONE)/未找到 z"
# 跳过=已推进过(幂等), 不是错误; 推进时刻的 update_time = 30 天物理删除倒计时起点
```

## 后续(plan-a 拟人化方向, 2026-09-27 用户定, 本 skill 暂未实现)

每日合成是人格原料入口。拟人化=人格画像(认知偏差/情绪周期/语言指纹/决策节奏/
交易哲学/行为特征, 从长期沉淀的 md/results 提取, prompt 层面持续更新)
+ 组织流程(分析→辩论→交易→风控→终裁→复盘, 计数器终止+recursion_limit+结构化输出)
+ 事实走确定性代码/拟人只做判断评分 + 学习闭环(延迟结算+反思注入+历史决策向量索引)
+ 可解释性(采集→辩论→决策全链路日志)。沉淀格式待 2-3 周数据后定, 先不建表。
