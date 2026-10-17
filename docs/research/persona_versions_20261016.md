# 导师画像当"模型权重"管：版本化 + 每版评估 + 可回滚（TODO 二B-11，2026-10-16 晚建）

> 脚本：`scripts/skills_ver/persona_versions.py`（零 token、不写数据库、不做 git、子进程 CREATE_NO_WINDOW）
> 存储：`skills_versions/`（项目根）
> 对应 TODO E16 的类比：画像文本=权重，蒸馏=梯度更新，分层拟人度=损失，前向交易日=验证集。本件补的是"改写没有验证"这一环。

## 一、要解决的问题（第一性原理）

每天蒸馏都会改写 `skills/<skill>-skill/persona/`，但没人量"这次改完，链是更像导师了还是更不像了"。要回答这个问题，需要三样东西：

1. **知道每一天链用的是哪一版画像**（版本化 + 归属）；
2. **按版本把结果分开算**（分段评估）；
3. **发现变差时能退回去**（回滚），且回滚本身可追溯、可撤销。

git 由用户手工提交，频率和蒸馏对不上，所以脚本自己存快照，不依赖 git。

## 二、存储格式

```
skills_versions/
  .lock                                  snapshot/rollback 互斥锁（运行时才有）
  _metrics/metrics_<止日>.json/.md       分段评估结果
  _metrics/check_<止日>.json/.md         变差判定结果
  <skill>/index.json                     版本表 + 回滚事件
  <skill>/objects/<sha256>.gz            内容寻址存储：文件内容 gzip，同样的内容只存一份
  <skill>/v<NNN>_<YYYYMMDD-HHMM>/manifest.json   该版每个文件的 sha256/字节/行数/mtime/类别 + 代码指纹明细
  <skill>/v<NNN>_<YYYYMMDD-HHMM>/diff.patch      相对上一版的 unified diff（v001 没有）
```

index.json 每个版本条目的字段：`v / id / ts（快照时刻）/ effective_from（生效时刻）/ persona_hash / data_hash / parent / changed{added,modified,removed} / data_changed / lines{added,removed} / bytes_weight / why / code{chain,distill}`，回滚生成的版本另带 `rollback_of`，被 prune 剪掉内容的版本带 `pruned`。

### 文件分两类

| 类别 | 哪些文件 | 会不会触发新版本 | 回滚时还原吗 |
|---|---|---|---|
| 权重 | `*.md`（profile/rules/rules_index/profile_index/cases/fingerprint/language）、`*.json`（ic/pools/score/rules_index.vec.json） | 会，版本哈希只看这一类 | 会 |
| 数据 | `*.jsonl`（cases_auto/fills_rt） | 不会（每晚由 mentor_fingerprint / backfill_fill_minutes 从账本机械重算，单独变化不算"改画像"） | 默认不还原，加 `--include-data` 才还原 |

数据文件不升版本，但只要出了新版本，就会连同当时的数据文件一起存档（同内容去重），所以需要的时候还是能看到当时的数据长什么样。

### 体积（实测）

- 23 个 skill 的 persona/ 原始共 15.7 MB（权重 5.6 MB + 数据 10.1 MB），gzip 后约 3.6 MB；**基线 v001 全量存档实测 4.1 MB**。
- 之后每出一个新版本，只新增改动过的文件（gzip 后的大小）：
  - tzzb 导师：权重约 20~30 KB，加上数据文件（如有变化）约 30~200 KB；
  - 桃哥最重：rules.md gz 后 450 KB，rules_index.vec.json gz 后 680 KB，一次全面蒸馏大约 1.2 MB；
  - 估算全体每天 2~3 MB，一年约 1 GB，量级不小，所以加了 **`prune --keep 30`**：只保留基线 v001 + 最近 30 版 + 回滚事件涉及的版本的文件内容，其余版本只留 manifest（哈希/行数）和 diff.patch。被剪的版本不能再回滚，会明确报错拒绝。按这个上限，桃哥约 36 MB，其他每位不到 6 MB。
- 选"gzip 全量 + 内容寻址"，没选"只存 diff 链"，理由：还原时不用把 diff 一路叠回去，任何一版都能一步取出；坏一个对象也只影响用到它的那几版。diff.patch 只是给人看的，还原不靠它。超过 1.6 MB 的文件和 vec.json 不出 diff，只记 +/- 行数。

## 三、版本归属：D 日的结果算哪一版

画像在当天 0915 前生效（0915 链 08:15 开跑），按下面的优先级定归属：

1. **run_meta 哈希（最准）**：`results/<skill>_chain/live-D/run_meta.jsonl` 里当天第一次真实运行（非 dry、非 as-of）记下的 rules/profile/cases/language 四个文件的 sha12，和哪一版完全一致就归哪一版。同一天几次运行画像不一样时，归属方式标"同日画像有变"。
2. **伪版本 `~<哈希8位>`**：有 run_meta 但对不上任何快照，说明这个画像确实存在过，只是没存快照。照样分段统计，但**不能回滚**。10/16 之前的历史全是这种情况。
3. **按时刻**：没有 run_meta 时，取 `effective_from < D 日 08:00` 的最新一版。`effective_from` = 这一版改动文件里最晚的 mtime（即内容最后成形的时刻），夹在"上一版快照时刻"和"本次快照时刻"之间。比如 00:12 蒸馏、00:30 快照，生效时刻记 00:12，归到当天。
4. 都没有：`v000`（基线前，未版本化）。

## 四、评估口径（metrics）

- 拟人度：读 `scripts/dfcf/paper/mimicry/*.json` 里每对（链, 日）的逐日 scores。同一天有多份结果（单日、累计、重算）时取 generated_at 最新的。四层主指标与 mimicry_score.py 的 MAIN 一致：L1_交易 / L2_方向 / L3_持仓Jaccard / L4_总仓误差。lift = 链 − 基线，误差类反过来取 基线 − 链。**综合 lift = 四层 lift 的均值**。
- 两条基线都算：
  - **对照（ctrl，主口径）**：A-control，同模板、同 facts、persona 为空。驱动器、模板、开关改了，对照链和导师链一起受影响，做差后基本抵掉，剩下的差异更能归到画像上。
  - **延续（persist）**：导师真人昨天的原样。不受代码影响，但也就分不出到底是画像改了还是代码改了。
- 收益：`books/<链>.json` 的 nav 逐日收益，段内复利；同时给 A-control 同期收益、导师真人同期收益（tzzb nav_daily）。超额 = 链 − 对照。
- 每段输出：版本、归属方式、起止日期、天数、各层 lift（对照/延续）、综合 lift、收益三列、该段里出现过几种代码指纹。

### 现在能算到什么程度（10/16 实跑）

- 有拟人度的只有 12 条 tzzb 导师链（B站三位 UP 没有真人账本，只算收益）。10/08 起最多 7 个交易日；对照链 10/12 才开始有数，所以对照口径最多 4~5 天。
- 画像几乎每天都在变（蒸馏每天跑），所以**每段基本只有 1 天**。10/08~10/09 是 v000（那时 run_meta 还没上线）；10/12~10/15 全是伪版本；10/16 有一部分能对上 v001（四个记录文件和 v001 一样）。
- 结论：**分段的表格框架已经通了，但现在任何一段的数都不能当结论**。check 实跑结果：5 正常 / 4 观察 / 1 告警（宣秋财经，退用延续基线、样本不够、没有可回滚的目标）/ 7 不判，没有任何动作。

## 五、check / rollback 规则

### check（判断"连续变差"）

- 只用有拟人度数据的版本段。**最近两段**各自和**参照段**比较：从最近两段之前往回，合并 1~3 个版本，凑够 `min_ref_days`（5 天）为止。
- 判定等级：
  - **不判**：有数据的版本段 < 3，或参照段 < `min_eval_days`（2）天。
  - **正常 / 观察**：最近两段都没比参照低 `delta`（0.10），或只有一段低了。
  - **告警**：最近两段的综合 lift 都比参照低 ≥ 0.10，但样本不够（参照 < 5 天，或最近两段合计 < 4 天）、bootstrap 不显著、在延续口径下代码同期也改过、或参照段里没有能回滚的版本。告警只写报告，不做任何动作。
  - **建议回滚**：以上条件都满足，并且两组之差（最近 − 参照）的 bootstrap 95% 上界 < 0。回滚目标 = 参照段里最近一个有快照的版本。
- 对照口径的样本不够时退用延续口径，这种情况下最多只到"告警"。

### rollback

`rollback --skill X --to vNNN [--dry] [--include-data] [--keep-extra] [--no-sync]`

1. 先检查目标版本的所有对象是否完整（被 prune 过或损坏就直接拒绝，persona 一个字都不动）；
2. **给当前状态存一份快照**（why=`rollback 前自动保存`），所以回滚本身随时可以撤销：再回滚到这份快照就行；
3. 把目标版本的权重文件写回 persona/（原子写，mtime=现在，生效时刻自然正确）。目标版本里没有的权重文件默认删除（回滚前的快照里已经存着），`--keep-extra` 保留；
4. 再存一份快照，标 `rollback_of`，index.json 记一条回滚事件；
5. 调 `node scripts/sync_skills.mjs`（CREATE_NO_WINDOW）同步到 .claude/skills/。

### 开关设计（默认只告警，不自动回滚）

脚本读 `scripts/dfcf/paper/params.yaml` 顶层的 `persona_rollback:` 节（**今晚没有写进去**，没有这一节就用默认值，auto=false 是安全的一侧）：

```yaml
persona_rollback:
  auto: false          # true 且 check --apply 才真回滚; 默认 false=只告警
  baseline: ctrl       # ctrl=对照差分(能抵掉代码改动) / persist=延续
  delta: 0.10
  min_eval_days: 2
  min_ref_days: 5
  min_recent_days: 4
  max_ref_segments: 3
  cooldown_days: 7     # 同一 skill 两次自动回滚至少隔 7 天
```

为什么默认不自动回滚：

1. 现在每段只有 1 天，噪声远大于信号。拟人度单日 lift 在 ±1 之间来回跳（L1/L2 是 0/1 指标），自动回滚就等于每天随机撤销蒸馏；
2. 蒸馏是"加知识"，回滚会把这几天新学到的规则也一起扔掉。代价不对称：误回滚丢的是真信息，晚几天回滚只是多跑几天差一点的画像；
3. 画像变差和代码改动经常同一天发生（见第六节），没有对照差分的话，"画像变差"本身可能就是误判；
4. 必须**同时满足** auto=true 和命令行带 `--apply` 才会真回滚。只改其中一个都不会动手，防止误触。

建议的放开条件：同一条链连续 ≥ 3 个版本段每段 ≥ 3 天，并且对照链覆盖完整，再考虑把 auto 设为 true。

## 六、局限与归因

1. **样本太少**：现在每段 1 天，check 基本只能给"不判/观察/告警"。要等蒸馏节奏和评估节奏对上，比如以后蒸馏改成每周合并一次，或者按周统计，每段才会有足够天数。
2. **蒸馏和代码改动混在一起**：run_taoge_chain.py、chain.md、params.yaml、开关（flags）几乎每天都在改。处理办法：
   - 每个版本的 manifest 里记两组**代码指纹**：`chain`（run_taoge_chain.py / 本 skill 的 chain.md / SKILL.md / params.yaml）和 `distill`（distill.md / distill_daily.py / llm_batch_tzzb.py / mentor_fingerprint.py / backfill_bilibili.py / gen_profile_index.py / gen_rules_index.mjs / check_md_daily.py），每个文件各存 sha12；
   - metrics 每段另外统计 run_meta 里 `chain_md_sha12 + flags` 的哈希有几种，check 里参照段和最近段的指纹不一样就注明"代码同期改过"；
   - 主口径用对照差分。对照链和导师链用同一个驱动器、同一套模板，代码改动两边一起吃，差掉之后剩下的才归到画像上。注意：这个差分只能抵掉"对所有链影响一样"的那部分代码改动，只对导师链生效的开关（比如 profile_index 的 F 注入只对有画像的链起作用）抵不掉。
3. **run_meta 只记了 4 个文件**（rules/profile/cases/language），fingerprint.md、profile_index.md、rules_index.md 改了，它看不出来。所以 run_meta 归属"一致"其实是"这四个文件一致"。要补上需要改 record_rules_version 让它记全部文件（改的是现有文件，今晚没动，作为建议）。
4. **快照必须跑在蒸馏之后、08:15 之前**，否则当天的画像就只能落成伪版本，不能回滚。建议两道：check md 的蒸馏步骤后跑一次，08:00 再跑一次兜底（没变化就什么都不做，0.6 秒跑完）。
5. **伪版本不能回滚**：10/16 之前的历史画像没有快照，只能看分段统计，不能退回去。
6. **拟人度依赖 mimicry 结果的新鲜度**：books 重跑以后 mimicry 需要重算，metrics 才会跟着变。metrics 永远读最新生成的那份。
7. **回滚不等于撤销已发生的交易**：只影响下一次链运行，books 不动。

## 七、要接进 check md 的命令（主会话来接，本件没有改 check_md_daily.py）

```bash
# ③三 UP distill 之后、⑤tzzb distill 之后、⑥发哥核销之后(任何改 persona 的步骤后) —— 只在有变化时出新版
scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py snapshot --all --why "check-md <日期> <步骤名>"
# 每晚收尾(mimicry_score + skill_weights 之后)
scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py check --until <日期>     # 同时写 metrics_<日>.md 和 check_<日>.md; 不带 --apply = 绝不回滚
# 每周一次(或体积 > 200MB 时)
scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py prune --all --keep 30
# 08:00 兜底(盘前, 0915 链之前)
scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py snapshot --all --why "08:00 盘前兜底"
```

手工用法：`log --skill X` 列版本；`export --skill X --v v003 --out <目录>` 把某一版还原到别的目录看；`rollback --skill X --to v003 --dry` 先看会动哪些文件；`selftest` 在临时目录里测全部功能（包括 rollback）。
