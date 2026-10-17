# 导师登记表 = 全体链名单唯一真源（TODO 二B-4，2026-10-17）

> 10/17 13:20 用户派发；短期 agent 执行。原定 18:30 时间闸，13:3x 主会话通知 A4 沙盒提前开跑，闸**立即生效**：决策链读取的文件只保留 1 个已验证的改动（run_taoge_chain.py），其余全部做成"待上线"版本放在 `scripts/temp/registry_bak/pending/`，等 A4 跑完由主会话安排上线。

## 1. 设计

- **登记表 = 两个 json**：
  - `scripts/tzzb/tzzb_ledgers.json`：tzzb 账本条目（id 就是 ledger 字段）。**只新增字段，不改不删**，脚本核过 21 条的原字段逐值不变。16 个正例新增 `type/display/book/short/cluster/circle/online`；5 个负样本只加 `type`，没有 book，所以不算链。
  - `scripts/tzzb/mentor_registry_extra.json`（新建，附表）：放 B站 UP 3 条和对照组 1 条。
- **UP 和对照组为什么没塞进 tzzb_ledgers.json**：Java `TzzbFetchHandler.loadLedgers()` 会把数组**每一条**都拿去跑 `fetch_tzzb.mjs --ledger <id>` 加 `syncFromRawJson`。taoge 这类条目没有 key、也没有 downloads 目录，必然失败，每轮还要多等 30~60 秒；整轮任务会被标成失败。而 Java 按规矩不能改。所以"在读者那边按 kind 过滤"这条路在 Java 上走不通，只能拆成附表。→ 列入「待用户裁」第 1 条。
- **字段**：id、type（UP / tzzb / 对照）、name（md 小节名，沿用 tzzb 原有语义；UP 填 md 标题去掉 `#### `）、display（显示名，等于 accounts.mjs 的第 2 列）、book（paper 账本名，土豆是 `A-cb`）、short（短描述，等于 facts「导师信号速览」的节标题；括号前那段 = run_taoge_chain MENTOR_HEAD 的关键词）、cluster（风格簇，从 mix_plans.CLUSTERS 搬过来，没有簇填 null）、circle（能力圈一句话，从 apply_plan_a.py 的 scope 和 ledgers 的 style 字段缩写而来）、online（上线日）。
- **顺序** = UP（按附表顺序）→ tzzb（按账本文件顺序，只取有 book 的）→ 对照组，正好等于 accounts.mjs 的颜色槽顺序。新导师加在文件末尾，自然排在对照组前面，和 10/17 onboard 的做法一致。
- **读取口**：`scripts/lib/mentors.py` 与 `scripts/lib/mentors.mjs`，两边口径相同：`all()` / `ids(*types)` / `get(id)` / `book(id)` / `by_book(book)`（mjs 里叫 `byBook`）/ `head(id)`。两边都有 `--selftest`：检查 id 和 book 不重复、必填字段齐全、py 与 mjs 读出逐项一致，并且 **accounts.mjs 字面名单与登记表逐项一致**（过渡期的一致性守卫）。

## 2. 写死名单位置表

### 2.1 已上线（改完且已验证）

| 文件 | 位置 | 改成 | 验证 |
|---|---|---|---|
| scripts/taoge-chain/run_taoge_chain.py | SKILL_CFG 里 18 行 `_up_cfg` | `SKILL_CFG.update({m: _up_cfg(m) for m in MENTORS.ids() if m not in SKILL_CFG})` | 改前改后 5 项全部 EQUAL（SKILL_CFG 20 个键的顺序和每链配置、TZZB_LEDGERS、LEDGER_NO、MENTOR_HEAD）；`--skill taoge/liuyiqing/control --selftest` 三条全 PASS |
| 同上 | TZZB_LEDGERS / LEDGER_NO / MENTOR_HEAD / UP 判断（拟人审统计） | `ids("tzzb")-{土豆}` / `ids("UP","对照")` / `head()` / `ids("UP")` | 同上 |
| scripts/tzzb/distill_daily.py | ALL_LEDGERS | `mentors.ids("tzzb")` | EQUAL；`--ledgers bogus` 列出 16 人 |
| scripts/tzzb/distill_history.py | DEFAULT | `_PRIO` 只管排序偏好，名单来自登记表，新导师自动排到末尾 | EQUAL |
| scripts/tzzb/screen_candidates.py | POS | `ids("tzzb")` 去掉土豆和冲5000w（原名单本来就没这两个） | EQUAL；`--dry` 正常 |
| scripts/backfill_bilibili/backfill_inference.py | `--ups` / `--tzzb-ledgers` 两个默认值 | DEFAULT_UPS（桃哥排最后）/ DEFAULT_TZZB | EQUAL |
| scripts/backfill_bilibili/backfill_loop.py | UPS | `ids("UP")` | EQUAL |
| scripts/md/build_distill_pack.py | UP_HEAD | `"#### " + name` | EQUAL；`--selftest` ok |
| scripts/skills_ver/persona_versions.py | chains()（原来解析 accounts.mjs 文本） | `[(book, id) for 登记表]` | 20 条 EQUAL；`selftest` 全部通过 |

### 2.2 待上线：pending/（决策链会读，A4 期间不落真文件；已验证）

`scripts/temp/registry_bak/pending/scripts/...` 下 15 个文件，合并 diff 在 `pending/registry_pending.patch`：

| 文件 | 位置 | 改前改后 |
|---|---|---|
| dfcf/paper/matcher.mjs | SOURCES 的 A 线 20 本 | EQUAL（25 本，顺序也一致） |
| dfcf/paper/facts.mjs | 导师信号速览 mentors 表 | 每一节内容逐字相同，**节顺序变了**：土豆从第 6 节挪到第 1 节，天哥和卢本圆对调 |
| dfcf/paper/replay_daily.mjs | BOOKS | 集合相等，**A-cb 从第 2 位挪到第 4 位** |
| dfcf/paper/ledger_limits.py | NO_LEDGER / TZZB_SKILLS | EQUAL |
| dfcf/paper/mimicry_score.py | TZZB_LEDGERS（PAIRS 跟着它生成） | EQUAL；selftest 40/40 |
| dfcf/paper/rule_tags.py | TZZB | EQUAL；selftest PASS |
| dfcf/paper/reflect_trigger.py | CHAINS | EQUAL；selftest PASS |
| dfcf/paper/mix_plans.py | CLUSTERS（改读登记表 cluster 字段）/ mentor_chains()（原来解析 accounts 文本） | 每簇成员集合相等（簇内顺序、簇的先后不同，只做成员判断，不影响结果）；mentor_chains EQUAL；selftest 全 ✓ |
| dfcf/paper/skill_weights.py | chains() / ledger_of() | EQUAL；selftest PASS |
| dfcf/paper/similar_days.py | UP 判断 | 集合相等；selftest PASS |
| md/gen_profile_index.py | STOCK_SKILLS | EQUAL（原以为链不读它，实际 run_taoge_chain 会 import，所以放进 pending） |
| taoge-chain/gen_horizon.py | NO_STAT / LEDGERS | EQUAL；整份输出 json 逐项 EQUAL |
| taoge-chain/collect_lessons.py | NAMES | 键值对集合相等；整份输出 md EQUAL |
| bilibili/up_ops_stats.py | UPS | EQUAL（run_taoge_chain 和 paper/* 都会 import 它） |
| tzzb/mentor_scope.py | NO_LEDGER | EQUAL（mimicry_score 和 run_taoge_chain 会间接 import） |

**上线步骤（A4 跑完后由主会话执行）**：
```bash
cd C:/Users/admin/dev/investment-tool
# ① 确认这段时间没人改过真文件(有输出的那几个改用 registry_pending.patch 手工合)
for f in $(cd scripts/temp/registry_bak/pending && find scripts -type f); do cmp -s $f scripts/temp/registry_bak/$f || echo "真文件已变: $f"; done
# ② 一致就整体覆盖
cp -r scripts/temp/registry_bak/pending/scripts/. scripts/
# ③ 验证
scripts/venv/Scripts/python.exe -X utf8 scripts/lib/mentors.py --selftest
PY=scripts/venv/Scripts/python.exe node scripts/lib/mentors.mjs --selftest
scripts/venv/Scripts/python.exe -X utf8 scripts/temp/registry_bak/_cmp_pending.py      # 16+1 项 EQUAL
node scripts/temp/registry_bak/_cmp_pending.mjs                                         # 3 项
for s in skill_weights mimicry_score rule_tags mix_plans reflect_trigger similar_days; do scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/$s.py --selftest | tail -1; done
for s in taoge liuyiqing control; do scripts/venv/Scripts/python.exe -X utf8 scripts/taoge-chain/run_taoge_chain.py --skill $s --selftest | tail -1; done
```

### 2.3 二期：accounts.mjs（前提是主会话先把 check_md_daily 切过来）

- `pending_after_checkmd/scripts/dfcf/paper/accounts.mjs` 已做好：导师 20 行改成 `MENTORS.all().map(...)`，混合账本 3 行保留。生成的 ACCOUNTS 和现在**逐项 EQUAL**（23 行）。
- **不能先上**：`check_md_daily.py _review_chains()`（L425）、`mix_plans.mentor_chains`、`skill_weights.chains`、`persona_versions.chains`、`top_chains_report`（L53）都是用正则读 accounts.mjs 的**文本**。accounts 改成函数生成后，这些正则只能读到混合账本，07 复盘名单会直接变空。目前前三处已处理（persona_versions 已上线，mix_plans/skill_weights 在 pending 里）；还剩 check_md_daily（主会话的文件）和 top_chains_report（只用来取显示名，二期顺手改成 mentors display 加混合名即可）。
- 二期上线时还要同步改 `scripts/lib/mentors.py` 的 selftest：它会文本比对 accounts.mjs，生成式写法下要跳过这一步。

### 2.4 主会话文件里的写死名单（我没动，替换式已验证等价）

| 文件 | 位置 | 建议替换（已验证与原值相等） |
|---|---|---|
| scripts/md/check_md_daily.py | L41 `UPS` | `[(m, "#### " + mentors.get(m)["name"]) for m in mentors.ids("UP")]` ✓ |
| 同上 | L425 `_review_chains()`（文本解析 accounts.mjs） | `return mentors.ids()` ✓（这一步是 accounts 二期的前提） |
| 同上 | L419 `REVIEW_NO_LABEL={"control"}` | 属于语义特例（当天没有答案标签），不算名单，建议保留 |
| scripts/dfcf/paper/slot_weekly.py | L51 `UP_SKILLS`（md 标题） / L52 `NO_REAL={"control"}` | `{m: "#### "+name for UP}` ✓ / `set(ids("对照"))` |
| scripts/dfcf/paper/slot_profile.py | L45 `UP_SKILLS` / L269 `("qushitiange","control","taoge","lubenyuan")` | `set(ids("UP"))` ✓ / `ids("UP","对照")`（只做成员判断，顺序无关）；L46 `PRIOR_ONLY` 是语义特例，保留 |
| scripts/tzzb/order_inference.py / scripts/holders/ / skills/*/persona/ | — | 没有名单（order_inference 只在 L1122 注释里提到两个 id） |

### 2.5 没改的（及原因）

- **语义特例，不是名单**：run_taoge_chain 里 `SKILL_CFG` 的 taoge/buchitudou0 专属配置；L3823 `("taoge","control","buchitudou0")`（审计#8 盲审口径）；`t_profile.FIRST`（示例优先级）；`mentor_model.PERSONA_CHECK`（规则出处）；quality_hooks、settle_decisions、price_rules 里的 control 判断。
- **A-cb↔buchitudou0 别名映射**（以后可以统一改成 `by_book()`，不影响加导师）：baselines.mjs L121、report.mjs L123/L202、real_vs_chain.mjs L24、similarity.mjs L32、settle_decisions.py L329、top_chains_report.py L12、pre_market.py L214。
- **B站基建（UP 专用的 mid/目录口径）**：llm_drain.py `MID`、backfill_bilibili.py 的 ups.json、manual_backfill.py `--ups` 默认值（paper/rerun_day 和 slot_weekly 会引用它，所以 A4 期间没碰；以后改成 `",".join(ids("UP"))` 即可）。
- **历史一次性脚本**（只是存档，不再跑）：apply_plan_a.py、rerun_tzzb_{batch1,batch2,batch3,b1v2,b3v2}.sh、expand8_follower.sh、coldstart_chain.sh、resume_1007_night.sh、reset_books.mjs、scripts/temp/onboard_1017.py、add_onboard_jobs_1017.py。
- **Java（只统计，不改）**：没有写死的名单。真正的依赖只有一处：`TzzbFetchHandler` 遍历 tzzb_ledgers.json 全部条目（这决定了附表设计）。其余是默认值或注释：PaperChainHandler L48 默认 taoge、PaperReviewHandler L62、TzzbRecordController L32 默认 buchitudou0、ChainRun L22 / BilibiliBackfillHandler L28,L42 / IBilibiliReconcileService L29 的注释。另外 md 模板 `inv-stock/src/main/resources/templates/stock-template.md` 每位导师有一个小节（属于 Java 资源）。
- **文档**：skills/tzzb-skill/SKILL.md、workflows/distill.md 里列举账本的句子是描述性历史记录，不是程序读的名单。

## 3. 新增导师标准步骤（tzzb 型；UP 型把第 1 步换成在附表加一条）

1. **登记**：tzzb_ledgers.json 末尾加一行，含凭证字段（ledger/name/user_key/key/kind=pos/match/entered，可选 pc_*）和登记字段（type="tzzb"、display、book="A-<id>"、short="名(一句风格)"、cluster 或 null、circle、online）。加完跑 `python scripts/lib/mentors.py --selftest`。
2. **skill 目录**：`skills/<id>-skill/`，内含 SKILL.md、`workflows/{sum,distill,chain}.md`、`persona/{rules,cases}.md`；chain.md 要写上本导师的能力圈、推导链、取数口径（参照 apply_plan_a.py 的 M 表格式）。
3. **数据**：`node scripts/tzzb/fetch_tzzb.mjs --ledger <id>` → Java 同步入库（TzzbRecordController sync?ledger=<id>）。
4. **md**：Java 模板 stock-template.md（src 和 target 两份）加 `#### <name>`，再用 `migrate_md_template.mjs` 迁移历史 md；`node scripts/tzzb/gen_tzzb_md.mjs --ledger <id> --all --write` 回填硬数据层。
5. **paper**：建 10 万初始账本 `books/A-<id>.json`；经应用接口 `/api/quartz/add` 挂 sys_job 定时，参数 `<id>:HHMM`，时段按真人成交分布定（参考 scripts/temp/add_onboard_jobs_1017.py 和 slot_activity.json）。
6. **零 token 生成**：mentor_fingerprint.py、mentor_scope.py、gen_horizon.py（→horizon_days.json）、gen_tzzb_profile / gen_tzzb_cases、slot_profile / t_profile（有新数据会自动纳入）；画像：distill_history.py --ledger <id>（要花 token），然后 gen_rules_index.mjs、gen_profile_index.py、sync_skills.mjs。具体参数以各脚本 `--help` 为准（本条依据 onboard_1017.py 和 TODO 10/17 记录整理，没有逐个演练）。
7. **过渡期还要手改**（pending 和二期都上线后这一步就没了）：accounts.mjs 加一行（不加的话 mentors selftest 会报不一致）、matcher SOURCES、facts.mjs mentors、replay_daily BOOKS、ledger_limits TZZB_SKILLS、mimicry_score TZZB_LEDGERS、rule_tags TZZB、gen_profile_index STOCK_SKILLS、gen_horizon LEDGERS、collect_lessons NAMES；如果归入风格簇，还要改 mix_plans CLUSTERS。UP 型另外还有：up_ops_stats、mentor_scope、check_md_daily UPS、slot_weekly / slot_profile UP_SKILLS。
   全部上线后：第 1 步加一行加第 2 步建目录，再跑第 3~6 步的生成脚本即可，代码一行都不用改。

## 4. 验证记录（10/17 13:2x~13:5x）

- 登记表：21 条原字段逐值不变（脚本断言），只新增字段。mentors.py / mentors.mjs 的 selftest 都 OK：20 条链（UP 3 / tzzb 16 / 对照 1），py 与 mjs 逐项一致，accounts.mjs 也一致。
- 已上线 9 个文件：py_compile 全过；`_cmp_lists.py` 7 项 EQUAL；run_taoge_chain 改前改后 5 项 EQUAL，三条链 `--selftest` PASS（日志在 registry_bak/selftest_chain_*.log）；persona_versions chains 20 条 EQUAL、selftest 全过；build_distill_pack selftest ok；check_md_daily `--date 2026-10-16 --only review07 --dry` 正常（用的是没改过的 accounts）。
- pending 15 个文件：py_compile 和 node --check 全过；`_cmp_pending.py` 17 项 EQUAL，`_cmp_pending.mjs` 3 项通过（差异仅在 2.2 表里列出的顺序）；用 `_run_pending_selftest.py`（以真实路径执行 pending 源码，不落真文件）跑了 6 个 selftest，全 PASS（日志在 registry_bak/selftest_pending_*.log）；gen_horizon 和 collect_lessons 的整份输出 EQUAL。
- 备份：改动前的原文件都在 `scripts/temp/registry_bak/<相对路径>`。facts.mjs 曾在 live 改过，因节顺序有变已按备份还原，cmp 一致。

## 5. 待用户裁

1. **附表方案**：UP 和对照组放在 `mentor_registry_extra.json`，不进 tzzb_ledgers.json（原因见 §1，Java 会逐条抓取）。另一个选项是改 Java TzzbFetchHandler 跳过 type≠tzzb 的条目，然后合成一个文件。
2. **facts 节顺序**：pending 版 facts.mjs 会让导师速览的节顺序跟登记表走（内容不变）。如果要求逐字节不变，就得在登记表里另加一个排序字段。
3. **上线日 online 的口径**：我按 paper 正式起算日填写：原 15 链填 10-08（A 线 10/8 统一重置）、对照组填 10-12（首个 live 日）、antoo / 芷影填 10-16、新 3 位填 10-19（计划首日）。也可以改成"登记日"。
4. **短描述和能力圈的文字**：short 原样沿用 facts.mjs 的节标题；circle 是我从 apply_plan_a.py 的 scope 和 ledgers.style 缩写的一句话；桃哥和对照组的 short 是新写的（只保证括号前关键词不变）。请过目。
5. **run_taoge_chain.py 留在 live 的风险**：它现在 import 时就读这两个 json。如果 fetch_tzzb.mjs 用旧的内存副本整表写回（切视图时会 saveLedgers），新字段会丢，tzzb 链的 `--skill` 就选不到。概率很低（这个副本得是在 10/17 13:2x 加字段之前就载入的）；如果要零风险，可以用 `cp scripts/temp/registry_bak/scripts/taoge-chain/run_taoge_chain.py scripts/taoge-chain/` 还原。
