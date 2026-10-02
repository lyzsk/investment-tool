# taoge-sum 过程记录(2026-10-02 用户立法: 过程可追溯, skill 更新/格式更新/意外都可回查)

> 追加约定: 每次跑批、格式变更、立法、事故, 在最上方加一行 `YYYY-MM-DD 事件: 经过 → 结果/产物`。
> 本文件只记"过程", 人格结论去 `skills/taoge-skill/persona/`, 管线知识去 Claude 记忆。

- 2026-10-02 **scripts 大重组(用户终裁)**: plan-a/plan-b/plan-c/taoge-paper 废除(曾压缩 1851 文件 33MB,
  **用户当日手工删除归档不可恢复**)。**v2 域目录化(同日)**: scripts/{bilibili,tzzb,cls,md} 分域,
  Java 6 处调用路径已同步改(BilibiliVideoServiceImpl/ClsTelegraphServiceImpl/MarkdownFormatServiceImpl/
  TzzbFetchHandler); backfill 守护迁入 `scripts/backfill_taoge/backfill_taoge.py`(**PAUSE=本目录 PAUSE**);
  老原料 20G 拆解: models+字典+wheel 16G → `scripts/models/`(已 gitignore), frames 870M 删(运行期可再生,
  不进 downloads 三件套), reuse 434M → `backfill_taoge/reuse/`(与 downloads 重叠=nlink=2 硬链接零占盘,
  45 待办跑完可删); scan.mjs 抢救回根目录(全局六榜); .gitignore 补 venv/models/__pycache__。
- 2026-10-02 cudnn 劫持根因修复: ctranslate2 抢注 torch 的 cudnn64_9.dll → VLM 崩溃;
  守护重启回填 07-08→05-06。scan_done 判据修复: 旧判据认 ocr 段=完成, 201 个 VLM 半成品被误判
  → 改认 vlm/pages 键; 另加日期区间倒挂守卫(lo>hi 显式报死, 10/2 我曾用倒挂区间重启导致 0-todo 空转)。
- 2026-10-02 模板迁移: 小节层级+1(### bilibili 下), 常备脚本 `scripts/migrate_md_template.mjs`,
  177 天历史 md 机械整编。
- 2026-10-01 格式机械可验立法: `#### 股市 - 桃哥复盘` 小节内禁止 `#####` 子标题(awk 可校验);
  10/1 夜跑 47 天+早期 3 天违规产物用 `scripts/temp/reformat_taoge_md.py` 零 token 整编。
- 2026-09-29 双副本漂移事故: `.claude/skills/taoge-sum/SKILL.md` 停留在 9/27 版(缺 §3.5/§5/§6),
  backfill md-sweep 按旧格式合成 → 立法: 每次编辑 canonical 后必 cp 覆盖 .claude 副本。
- 2026-09-29 用户修订: 旧 md 全部统一为**最新日期格式**(锚点跟随最新日期而非历史定稿日);
  批量改写走脚本不走手工会话。
- 2026-09-28 §3.5 立法: 个股技术快照与持仓逆向分层; 紫色高亮=持仓(用户确认非"疑似");
  MA120/144 与指标参数=用户指定观察字段, 不进推断链; "跌透了"语料实锤(05-07/08 逐字稿)。
- 2026-09-24 小节格式定稿: 五大 bullet 全收在 `#### 股市 - 桃哥复盘` 下, 不用 ##### 子小节。
- 定位: 状态机最后一棒(VISION_DONE→SUMMARIZED), 不推进则 30 天物理删除不触发。
  下游: `taoge-distill` 读本 skill 产出的 md 小节沉淀进 taoge-skill/persona(串行链第三棒)。
