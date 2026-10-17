# taoge 对账 orphan_distill 两天排查（2026-10-17，agent③，只报告+建议）

> 对账口径（`inv-stock/.../BilibiliReconcileServiceImpl.java`）：`orphan_distill` = 蒸馏账本 `scripts/backfill_bilibili/distill_state.json` 的 `done` 里有、但没有任何"产物齐的视频"对应到的日子。两天的原因不同：**2026-09-13 是对账规则的误报；2024-07-15 是一条归档错位视频留下的假账，还顺带让 md 补跑每轮白跑一次 claude -p。**

## 1. 2026-09-13：误报（对账规则漏了一种合法情况）

- 事实：BV1sqYi68ESj《A股最高板，是三板组 明天不要接盘》2026-09-13（周日）21:52 发布，产物在 `results/bilibili/625315686/2026.09.13/`（齐）；周末稿按 10/7 立法并入下一交易日 md `md/2026S3/2026-09-14.md`（小节首，见该 md 第 1157 行注释）。
- 账本里 09-13 和 09-14 都有：09-14 在 10/7 就蒸馏过；10/11~10/12 md 补跑把 09-13 顺延块并进 09-14 时，因为挂载日已蒸馏，脚本把 09-13 记进 `rolled_pending`，随后**单独蒸馏了 09-13 这一块、账本按发布日记 09-13**——这是 `backfill_bilibili.py` 设计好的流程（`_pending_distill_days` 的顺延分支）。
- 对账为什么报：Java 里"顺延稿按发布日记账"的兜底条件是 `doneDates.isEmpty() && !mdDates.isEmpty() && distilled.contains(f.day)`——只在挂载日**没**蒸馏时才把发布日算进已蒸馏。09-14 先蒸馏了，`doneDates` 非空，09-13 就落不进 `distillDays`，成了孤儿。
- 建议（Java 补丁已出，未合入）：`scripts/temp/agent3_patch/J1_BilibiliReconcile_orphan_distill.patch`。条件改成 `!mdDates.isEmpty() && distilled.contains(f.day)`，即账本里记了发布日也算数。javac 离线编译通过（`scripts/temp/agent3_test/javac/`），需要重启 application 才生效。

## 2. 2024-07-15：归档错位视频的残留账（建议清账+挪隔离区）

- 事实：BV11w4m1a7D4 是 2024-07-15 的旧视频（产物 pubdate=1721062168），早期被老 md 里的脏链接错挂成 9/21 的"第二视频"；**10/01 发现后剔除**，产物移到 `results/bilibili/625315686/2024.07.15/` 隔离（见 `md/2026S3/2026-09-21.md` 第 953 行注释）。
- 账本里的 "2024-07-15"：最早的备份（`distill_state.json.bak-20261011-pre-redo`）里就已经有，并且是第一项。代码路径里没有能产生它的正常分支（2024 年没有 md，`maybe_distill`/`_pending_distill_days` 都要求 md 存在），**推断是错位期间或 10/01 清理时手工/会话写进去的**（证据不足以确定是哪一次，日志里查不到 "distill 完成 2024-07-15"）。2024 年的内容其实从没按 2024-07-15 蒸馏过。
- 连带问题（实测）：隔离目录在 `results/bilibili/625315686/` 下，`_pending_md_days` 把它当"有产物没 md"的欠账，**每轮 llm-batch 都给它开一次 md-batch**——10/15 20:03 起已经 7 次"md-batch 未成 2024-07-15: 哨兵缺失"，其中 10/16 19:52 那次是单独一个会话（$0.15）；其余混在 5 天批次里，占用批次名额。
- 对账为什么报：这只视频的 md 日期集合 = {2026-09-21}（因为 9/21 的 md 里那条剔除说明还带着它的链接），所以 `distillDays` 里只有 09-21；账本里的 2024-07-15 对不上，成了孤儿。上面的 J1 补丁合入后，这条会因为"md 有链接 + 账本有发布日"而**不再报**——但那是被掩盖了，不是真的对上了，所以仍建议清账。
- 建议（需主会话/用户批，**本 agent 没动账本**）：
  1. 从 `scripts/backfill_bilibili/distill_state.json` 的 `done` 删掉 `"2024-07-15"`（先备份）。
  2. 合入 Python 补丁 `scripts/temp/agent3_patch/P1_backfill_bilibili_md_cutoff.patch`：`_pending_md_days` 跳过早于 2025-01-07 的结果目录（md 从这天开始，更早的永远不会有 md）。已离线验证：原版 `_pending_md_days({"BV11w4m1a7D4"})` 含 2024-07-15，补丁版不含。
  3. （可选，更彻底）把隔离目录挪出 UP 结果根目录，如 `results/bilibili/_quarantine/625315686/2024.07.15/`，这样 Java 对账和 Python 扫描都看不到它。

## 3. 不自信点

- "2024-07-15 是手工/会话写进账本"是推断，没有日志直接证明。
- J1 改动会让"md 里只是提到链接（不是真的挂载）"的视频也算已蒸馏；目前只有 BV11w4m1a7D4 这一个例子。要更严，可以让 Java 的 md 索引只认小节里的视频标题行（`**[标题](…/video/BV…)**`），不认注释里的链接——这一步改动更大，没做。
