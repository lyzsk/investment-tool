# scripts/ 目录说明 + 全链路使用手册(2026-10-02 重组 v2: 域目录化)

> 在用路线: **taoge-skill(学桃哥) + buchitudou0-skill(转债高手不吃土豆0)** 两条线。
> 目录按域分文件夹; 根目录只放全局工具+环境; Java 调用的脚本路径已同步改 Java(10/2)。
> 运行前提: mjs 一律 `node scripts/<域>/<脚本>`(cwd=项目根); py 一律 `scripts/venv/Scripts/python.exe scripts/<域>/<脚本>`。

## 根目录(全局)

| 文件/目录 | 用途 | 用法 |
|---|---|---|
| `scan.mjs` | 大盘六榜扫描(涨跌幅/连板梯队/跌停/次新/板块), taoge-skill 事实包用 | `node scripts/scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30]` → scan.md+scan.json |
| `fetch_holidays_cn.py` | 中国节假日抓取(年度) | `python scripts/fetch_holidays_cn.py` → inv-common/resources/holiday/{year}.json |
| `venv/` | python 环境(ASR+7B+OCR; 已 gitignore) | 重建: `requirements-taoge.txt` / `requirements-cls.txt` |
| `models/` | Qwen2.5-VL-7B(16G)+纠错字典+wheel(已 gitignore) | `process_video.py --download-model` 一次性下载 |
| `models/local_llm.py` / `.mjs` | **本地 ollama 统一客户端**(10/7 第一梯队本地化) | 分工: qwen3:14b=ASR 谐音纠错 / qwen3:32b=推测层初稿(错峰, 与 VLM-7B 互斥) / bge-m3=rules_index 检索层; 模型实体在 `%USERPROFILE%\.ollama\models`; 冒烟 `python scripts/models/local_llm.py --smoke` |
| `models/`（本地模型台账） | **全模型分工与显存预算见文件头注释** | whisper small=faster-whisper **CPU int8 零显存**(ollama 无 ASR 生态, 不迁); RapidOCR=onnx CPU(不迁); Qwen2.5-VL-7B **bf16 15.4G transformers**(行为真值层禁量化, 不迁 ollama; 除非未来要 VLM 与 32B 真并行才评估 Q4 省 9G) |
| `dfcf/` | 实盘语料存档(snapshots/ 已 gitignore=隐私唯一落点) | 见文末「dfcf 线」 |
| `taoge-chain/` | 决策链驱动器(按 skills/taoge-skill/workflows/chain.md 契约) | `scripts/venv/Scripts/python.exe scripts/taoge-chain/run_chain.py --slot 0915 [--date yyyymmdd] [--dry]` / `--review` / `--selftest`(不烧 token); 出口 0=完成 1=中止 3=ESCALATE_FULL_CHAIN |

---

## bilibili/ — 桃哥视频管线(发现→下载→ASR→纠错→VLM→产物)

**全链路**: B站视频 → `fetch_bilibili_taoge.mjs`(发现+下载原料) → `process_video.py`(转知识) → `results/bilibili/<mid>/<yyyy.MM.dd>/` 四件套 → taoge-skill sum 合成进 md。

| 脚本 | 用法 | 产物/出口 |
|---|---|---|
| `fetch_bilibili_taoge.mjs` | `node scripts/bilibili/fetch_bilibili_taoge.mjs --list`(只发现, stdout 末行 `JSON:[...]`)<br>`node scripts/bilibili/fetch_bilibili_taoge.mjs [--bvid BVxxxx] [--out <目录>] [--video-only\|--audio-only]` | `<out>/<bvid>.mp4`+`.m4a`+`.json`; 幂等补缺; 0=就位 1=失败 |
| `process_video.py` | `scripts/venv/Scripts/python.exe scripts/bilibili/process_video.py --bvid <bvid> --mp4 <路径> --m4a <路径> --out <结果目录>`<br>调试口: `--stage asr,correct,vision,aggregate` / `--keep-frames` / `--download-model` / `--local-correct`(10/7: correct 后追加本地 qwen3:14b 修词典漏网谐音, 等长替换护栏, ollama 不在=跳过不阻塞) | `<bvid>.raw.txt`+`.tsv`+`.txt`(合成读的)+`.vision.json`; 幂等; GPU 串行(ASR 卸载再上 7B) |

**Java 驱动(生产唯一入口, 勿手工并行跑)**: `bilibiliVideoHandler` 单 job 三段(发现→下载→process_video), 状态机走 `bilibili_video` 表(VISION_DONE 后等 taoge-skill sum 合成→SUMMARIZED→DISTILLED→30 天原料物理删除)。10/12 起: 表加 `origin`(DAILY=每日 48h 发现 / BACKFILL=补跑登记), 每日任务只处理 DAILY; 历史补跑由 `bilibiliBackfillHandler`(`--up X [--enqueue N --from --to] [--process N]`)限量处理, 替代 backfill_bilibili.py 的逐视频下载/处理(其 `--llm-batch` 清账段照用); `bilibiliReconcileHandler`(23:50)逐视频核 results→md→distill 账本并把表同步到文件事实。
**依赖**: scripts/models/(字典+7B); 无 cookie 方案(search HTML+view/playurl API 不吃风控, 空间列表已风控勿用)。

---

## tzzb/ — 转债高手(不吃土豆0)线

**全链路**: 同花顺投资账本 API → `fetch_tzzb.mjs`(Java cron 小时级) → `downloads/tzzb/<ledger>/`(raw 证据层) → Java sync 入 `tzzb_record` 表 → `gen_tzzb_md.mjs`(硬数据层) + tzzb-skill(sum 工作流,【推测】层) → md `#### 不吃土豆 0` → tzzb-skill(distill 工作流,机械核销进 buchitudou0-skill)。

### 每日链(15:10 抓取后, check md 例程内)

```bash
node scripts/quotes/fetch_quotes.mjs --market cb --trends-all      # ①当日有腿标的分钟级分时归档(东财只留~5天, 必做!)
node scripts/tzzb/gen_tzzb_md.mjs --ledger buchitudou0 --date <yyyy-MM-dd> --write   # ②硬数据层进 md
# ③tzzb-skill(sum 工作流): LLM 补【推测】层(逐条标【推测】, 不复述硬数据)
# ④tzzb-skill(distill 工作流) 机械层(零 token, 每日必跑):
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_profile.py --ledger buchitudou0
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_review.py --ledger buchitudou0 --json scripts/backfill_bilibili/review_cb_daily.json
scripts/venv/Scripts/python.exe scripts/tzzb/gen_tzzb_cases.py --all    # 六人 cases.md 双尾区(直连 review 引擎, 无需 json 前置)
```

### 脚本明细

| 脚本 | 用法 | 说明 |
|---|---|---|
| `fetch_tzzb.mjs` | `node scripts/tzzb/fetch_tzzb.mjs [--ledger <id>]` | 默认跑 `tzzb_ledgers.json` 全部账本; 产物=downloads/tzzb/<ledger>/(position_change/nav_daily/month/position/change_bs_*/state.json); 出口 0=正常 2=凭证失效 1=失败 |
| `fetch_tzzb.mjs --rank` | `node scripts/tzzb/fetch_tzzb.mjs --rank <比赛key>[,<比赛key>...]` | **比赛榜单发现层**(10/7 建): match_ranking_by_share 拉全量榜单→downloads/tzzb/_ranks/<key>.json; (比赛key,user_key) 直通账本全链端点=同人换更早比赛视图可扩时间深度; 归档永远 by ledger(人), 比赛只做发现 |
| `llm_batch_tzzb.py` | `scripts/venv/Scripts/python.exe scripts/tzzb/llm_batch_tzzb.py [--ledger <id\|all>] [--from-date/--to-date] [--dry]` | **推测层本地批量初稿**(10/7 建, 替代退役 sweep_tzzb_spec 的云端批量): qwen3:32b 错峰跑缺【推测】的小节, 每条带锚点+尾标 (32B初稿), 复核定稿归日常链 Claude; 显存闸>6G 外部占用让路; 幂等=有【推测】即跳过 |
| `gen_tzzb_md.mjs` | `--ledger <id> --date <d> [--write]` / `--ledger <id> --all --write` | 硬数据层(零 token): 净值行+FIFO round-trip 明细+汇总; --write 整小节覆盖**保留【推测】行**; --all 全历史回填 |
| `review_cb_daily.py` | `[--json out.json]` | K3 原作(全日内单土豆口径, 10/7 退役存档); 日常链用 gen_tzzb_review |
| `gen_tzzb_profile.py --ledger buchitudou0` | `[--json out.json]` | 机械画像: 900腿统计+市况反向联动(T-1 口径) |
| `gen_tzzb_cases.py` | `--ledger <id> \| --all` | 六人 cases.md 双尾样本库区机械重生成(直连 gen_tzzb_review 含跨日); 阈值 \|持收增量\|≥5% 全量不截断; 土豆 curated 区与五人 LLM 叙事区保留 |
| `sweep_tzzb_spec.py` | `[--limit N]` | 历史日【推测】层批量补写(headless, 5日/批); **10/2 已全量收官 144/144**, 留作新高手账本接入时的模板 |
| `tzzb_ledgers.json` | — | 账本凭证清单(分享链接 key+user_key), 加高手=加一行 |

---

## cls/ — 财联社电报线

**全链路**: cls_telegraph 表(Java 已有) + 电报图下载(downloads/cls/<yyyy.MM.dd>/) → `cls_image_ocr.py`(本地 OCR 零 token) → md 四小节(午评/午间涨停分析/收评/涨停分析, **OCR 单一数据源覆盖**) → /check-cls-md 晚间人工看图复核。

| 脚本 | 用法 | 说明 |
|---|---|---|
| `cls_image_ocr.py` | `python scripts/cls/cls_image_ocr.py <图片路径> --type wp\|sp\|wjzt\|zt` | stdout=md 小节内容(不含标题); PARSE_FAIL 非0退出=不写 md 只告警; **Java ClsTelegraphServiceImpl 定时调用(生产入口)** |
| `fill_cls_md.py` | `python scripts/cls/fill_cls_md.py --from <d> --to <d> [--overwrite --backup <dir>]` | 历史回填通道(非 Java); 默认只填空小节, --overwrite 才覆盖 |
| `fetch_cls_zaobao.mjs` | `node scripts/cls/fetch_cls_zaobao.mjs --url <api3.cls.cn/share/article/...> [--date <d>] [--write] [--force]`<br>`--remount --date <d> [--write]` | **早报线(10/2 建)**: 早报=文章通道不在电报端点(Java 爬不到=端点问题); 发现层=人工贴链接(hermes 语法 "早报+链接"); 产物 downloads/cls_zaobao/<date>/{raw.html,text.md,meta.json,spec.md}; 挂载 md `## 盘前`→`### 财联社早报`(原文不进 md, spec.md=【早报要点】五栏唯一真源, hermes 蒸馏) |

---

## lhb/ — 每日龙虎榜(2026-10-14 建, 东财 datacenter-web 公开接口, 零 token)

| 脚本 | 用法 | 说明 |
|---|---|---|
| `fetch_lhb.mjs` | `node scripts/lhb/fetch_lhb.mjs --date <d> [--write] [--force]` | 一天 3 次请求(总表+买五整批+卖五整批; 某记录两边全缺才按个股补); 产物 downloads/lhb/yyyy.MM.dd/{list.json,detail_<code>.json}(18:00 后抓且齐=完整, 再跑走缓存零请求); --write 整节覆盖 md `## 复盘`→`### 龙虎榜`(总表表头从 stock-template.md 现读; 缺骨架先调 migrate_md_template 补; 无 `## 复盘` 的早期 md 只存 json); 出口 0/1 抓取失败/3 当日未出/4 无md/5 反爬 |
| `backfill_lhb.mjs` | `node scripts/lhb/backfill_lhb.mjs --from 2025-01-07 --to <d> [--max-days N] [--write] [--until HH:MM] [--gap 秒]`<br>`--remount`(零请求按当前格式重写已有 json 的天) | 倒序回填; 反爬即停/连续 2 天失败即停; 开始结束各探一次东财 push2 金丝雀; 日志 scripts/lhb/logs/; check md 00:00 轮末尾自动调(--max-days 150 --until 06:40) |
| `youzi.json` | 手工维护 | 席位简称→游资名(只收确定的), 命中在 md 席位后标"(游资名)" |

---

## market/ — 行情库 investment_market 采集域(2026-10-11 建, 10/12 凌晨补齐 2b/4/5/6 段)

**链路**: Quartz `marketDailyHandler`(15:35) → Java `MarketPipelineService`: `collect_daily.mjs` → `refresh_factors.py` → `collect_minute.py` → `downloads/market/<交易日>/*.jsonl`+`manifest.json`+`DONE_<stage>` → Java `MarketImportService` 入库(表结构 `sql/investment_market/`); 对账 `marketReconcileHandler`(16:40 + 应用启动 3 分钟后)缺哪天补哪天, 共用同一流水线和锁。脚本都不直接写库。

| 脚本 | 用法 | 说明 |
|---|---|---|
| `collect_daily.mjs` | `node scripts/market/collect_daily.mjs [--expect yyyy-MM-dd] [--stages security,kline_day] [--force] [--src sina\|em]` | 第 1 段: 证券主数据+全市场日线快照(A股/转债/ETF/指数); 新浪主/东财 clist 备, 整节点单源; 单位归一(沪市指数手→股); 涨跌停按板块算; 盘中拒跑; DONE 断点; 出口 0/1 失败或交易日不符/2 盘中 |
| `backfill_history.py` | `scripts/venv/Scripts/python.exe -X utf8 scripts/market/backfill_history.py [--until 06:30] [--max-pages 1] [--gap 2.0,3.0] [--codes/--codes-file] [--force]`<br>`--day yyyy-MM-dd`(补采单日全市场) / `--source baostock`(备选) | 第 2 段: 腾讯不复权日线(按日期翻页, 单页 ≤2000 根)+新浪 hfq 复权因子+推导昨收 → `downloads/market/history/`(Java `marketHistoryHandler` 入库, 只导上线日 2026-10-09 之前); **腾讯 ifzq ~1.6 次/秒 6 分钟即封 IP(10/12 实测), 默认 0.4 次/秒**; `--max-pages 1` 截断的记 `truncated.txt` 以后补全; 出口 0/1 有失败/2 熔断或到点 |
| `refresh_factors.py` | `scripts/venv/Scripts/python.exe -X utf8 scripts/market/refresh_factors.py --date yyyy-MM-dd` | 第 2b 段: 快照昨收≠上一日收盘 → 拉新浪因子, 因子比与收盘/昨收比对 <0.2% 才落 `adjustment_factor.jsonl`, 不过记 `factor_pending.json` 重试 5 天; ETF 只留痕 |
| `collect_minute.py` | `scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_minute.py --date yyyy-MM-dd` | 第 3 段: 关注集(持仓/计划/池/导师/涨跌停/md/固定/粘滞 10 日) + 通达信逐笔聚合 1 分钟线; 往日可补 |
| `collect_auction.py` | `scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_auction.py --phase OPEN\|CLOSE [--now]` | 第 5 段: 新浪批量报文轮询集合竞价过程(OPEN 09:15~09:25:40 每 15s / CLOSE 14:57~15:00:40 每 10s), 原始报文全留档; 竞价不可事后补 |
| `collect_global.py` | `scripts/venv/Scripts/python.exe -X utf8 scripts/market/collect_global.py [--force]` | 第 4 段: 外围 16 品种收盘(美股指数/中概/港股/日英/A50·美股期货/金油/离岸人民币), 按当地交易日, symbol 如 `us.NDX` |

## 新增导师标准步骤(10/18 起一条命令 `onboard_mentor.py`, 默认"最厚做法"; tzzb 型。UP 型仍手工: 登记换成在 `scripts/tzzb/mentor_registry_extra.json` 加一条)

登记表 = 全体链名单唯一真源(`scripts/lib/mentors.py` / `mentors.mjs` 读), 各脚本都从这里取名单, **加导师不用改代码**。人工只做前两步:
1. **登记**: `scripts/tzzb/tzzb_ledgers.json` 末尾加一行: 凭证字段(ledger/name/user_key/key/kind=pos/match/entered/style, 可选 pc_*) + 登记字段(type="tzzb"、display、book="A-<id>"、short、cluster 或 null、circle、online)。
2. **抓取**: `node scripts/tzzb/fetch_tzzb.mjs --ledger <id> --full`(同花顺请求只走它, 避开每小时 :05~:30)。
3. **一条命令**(其余全自动, 每步幂等、断点续跑 = 再跑同一命令; 状态 `results/onboard/<id>/state.json`, 日志与备份 `scripts/temp/night_bak/onboard_<id>/`):
```bash
scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/onboard_mentor.py --ledger <id> --apply-jobs [--focus "专题" --focus-match "正则"] [--skip-token] [--dry] [--date D] [--redo 步名] [--budget 25]
```
   步骤顺序: preflight → db_sync(应用接口 sync + 只读核对行数) → skill_skel(SKILL.md/sum/distill/rules/cases 骨架) → md(order_tzzb_sections 补 `#### <name>` + gen_tzzb_md 全历史硬数据层; **不用改 Java 模板**) → kline(补日线归档) → mech(gen_tzzb_profile→profile.md v1 / mentor_fingerprint / mentor_scope / gen_horizon / gen_tzzb_cases / backfill_fill_minutes / order_inference / case_log / hold_mining / fee_profile) → paper(matcher --init 建 10 万账本 + 时段按真人决策事件分布算 → slot_activity.json; `--apply-jobs` 才经 `/api/quartz/add` 加 sys_job `<id>:HHMM`) → daily(链日 D 的 pools 合并 / mentor_model --predict / mentor_cards / quality_daily) → chain_md(由模板导师 chain.md 改名 + 能力圈/推导链/取数按机械统计重写) → focus(给了 --focus 才做: 专题逐笔明细) → **[token]** distill(distill_history 并入 rules.md) → thicken1 → thicken2(并入) → profile_deep(profile.md 深度六节 + 专题节) → finalize(规则索引 / 画像索引 / rule_tags / persona_versions snapshot / sync_skills) → verify(mentors 自测 / run_chain --selftest / 驱动器模板载入 / matcher --once --dry / 共享文件核对)。
   共享文件(mentor_scope / horizon_days / fee_profile / model_out / pools / slot_activity)一律合并写, 不丢别人的条目; 核对: `onboard_mentor.py --check-shared a,b [--date D]`。实测单人花费约 $12(上限 --budget 默认 25)。
- 10/18 规矩: 脚本生成的报告一律写本域 `reports/`(tzzb → `scripts/tzzb/model_out/reports/`, paper → `scripts/dfcf/paper/reports/`, 决策链 → `scripts/taoge-chain/reports/`, 龙虎榜 → `scripts/lhb/reports/`, 健康 → `scripts/health/reports/`); `docs/research/` 只放人写的调研, 看完即删。

## lib/ — 公共模块

| 模块 | 用法 | 说明 |
|---|---|---|
| `claude_call.py` | `sys.path.insert(0, "scripts/lib"); from claude_call import call` → `call(prompt, tag=..., permission="skip", sentinels=[...], json_schema=..., expect_files=[...])`<br>自测: `python -X utf8 scripts/lib/claude_call.py --selftest` | 无头 `claude -p` 统一调用(10/12): prompt 按字节走 stdin / json 信封判 is_error+subtype / 限流只在错误文本匹配+rotation 切 key / 哨兵整行匹配 / ```json 块+迷你 schema 校验 / 应写文件 mtime 核验 / 成本账本 `scripts/lib/claude_cost.csv`(gitignore) |
| `req_guard.mjs` / `req_guard.py` + `req_guard_sources.json` | `import { gfetch, gcall, guard } from "../lib/req_guard.mjs"` / `from req_guard import gfetch, gcall, guard`; 状态: `node scripts/lib/req_guard.mjs --status`, 人工解熔断 `--clear <源id>`, 冷却中探测 `REQ_GUARD_PROBE=<源id>` | 统一请求层(10/15): 按域名路由到源, 跨进程限速+抖动/滑动窗口/熔断(连败 N 或封禁特征→`downloads/_guard/<id>.ban.json` 冷却内不发请求)/日预算/失败分类 BLOCKED·AUTH·RATE_LIMIT·NO_DATA·UNAVAILABLE·PARSE/每日计数 `<id>_requests_<日>.json`; daily_health 巡检红黄。已接: bilibili/lhb/cls 早报+涨停池/kline/snapshot/scan(tzzb 用自带 `downloads/tzzb/_guard`) |

## quotes/ — 行情获取域(转债+个股)

| 脚本 | 用法 | 说明 |
|---|---|---|
| `kline.mjs` | `node scripts/quotes/kline.mjs --codes 002428,1.000001 [--src east\|tencent\|sina] [--dir <d>] [--full]` | **日线多源注册表**(10/5 用户立法: 数据源 switch-case): 东财(前复权,增量beg)→腾讯ifzq(前复权,900根)→新浪(不复权,仅兜底禁混前复权档); `--src`=强制单源排障; 归档幂等按日期合并 → downloads/quotes/daily/; gen_taoge_ic(A1) 与 A2 通用归档共用; 淘汰记录见文件头(163死/雪球要登录/东财镜像空) |
| `fetch_quotes.mjs --market stock` | `node scripts/quotes/fetch_quotes.mjs --market stock --from-md <yyyy-MM-dd> [--force]`<br>`--codes 600127,002264 [--date <d>]` | 桃哥=分时盘口选手, 日内断言("冲高2点没走"/"尾盘硬拉")需分钟级核销; 东财分时只留~5天=当天必归; --from-md 抠 md 全文（6位代码）去重归档 → downloads/quotes/stock/trends/<code>_<date>.json; 市场位自动翻转(北交所)。**无替代源**(腾讯分时仅当日且格式异, 5天窗口是本脚本存在原因) |
| `fetch_quotes.mjs --market cb` | `node scripts/quotes/fetch_quotes.mjs --market cb --trends-all`<br>`--kline-all` / `--kline --code <c>` / `--trends --code <c>` / `--snap --code <c>` | 转债行情(10/2 自 tzzb/ 迁入): 日线回填(双源东财+腾讯)/分时归档/实时快照; --trends-all 单向依赖 downloads/tzzb 账本腿; 产物 downloads/quotes/cb/{kline,trends}/; 日线可后续迁移至 kline.mjs 注册表(TODO) |

> **数据源立法(10/5)**: 行情快照统一走 `dfcf/paper/snapshot.mjs`(5 源: 腾讯qt/东财/腾讯分时qt/新浪/东财延迟, `--src` 强制单源; matcher/facts/驱动器验价共用), 日线统一走本目录 `kline.mjs`(3 源)。东财限频实证(10/5)后立的: **任何行情拉取禁单源直连**, 注册表+fallback 是标配。

---

## md/ — md 工具

| 脚本 | 用法 | 说明 |
|---|---|---|
| `format-markdown.mjs` | Java MarkdownFormatServiceImpl 调用 | prettier 格式化(需项目根 npm install prettier) |
| `migrate_md_template.mjs` | `node scripts/md/migrate_md_template.mjs [--dry] [dir...]` | **模板迁移常备**: stock-template.md 变更后跑它批量同步历史 md(模板驱动/标题归一/缺节补骨架; 幂等) |
| `gen_rules_index.mjs` | `node scripts/md/gen_rules_index.mjs [--skill taoge] [--embed]` / `--query "文本" [--top N]` | B3 分级加载: rules.md ### Xnn 头→rules_index.md(✅⏳❌ 状态标+前 2 条要点备注); `--embed` 追加 bge-m3 向量层→rules_index.vec.json(本地零 token); `--query` 语义检索 top-N(标题捞不准时的兜底); 幂等; chain 驱动器每轮自动重建 |

---

## backfill_bilibili/ — B站 UP 历史追溯(桃哥/天哥/卢本圆, 引擎 backfill_bilibili.py; 整目录已 gitignore, 只在本机跑)

**全链路**: `backfill_taoge_index.mjs`(BFS 建待办索引 index.json) → `backfill_bilibili.py` 守护(多 UP 引擎, --up 选 taoge/qushitiange/lubenyuan, 旧名 backfill_bilibili.py=兼容垫片链落地后删; 待办=索引-results 扫描; 时间窗/GPU/PAUSE 三守卫; 下载(先查 reuse/ 硬链复用)→process_video→state 记账) → results 四件套 → **两段式清账**: ①`--stage download` 视频段(纯 GPU, 零 LLM) ②`--llm-batch` 清账段(5 天/会话批量 taoge-skill sum 合成 md + taoge-skill distill 核销沉淀, distill_state.json 账本)。

**启动命令(两段式, 2026-10 起为默认路径)**:
```bash
# ① 视频段(纯 GPU, 零 LLM): 下载+process_video, 产出 results 四件套
scripts/venv/Scripts/python.exe scripts/backfill_bilibili/backfill_bilibili.py --stage download
# ② 清账段(5 天/会话, 批量 sum+distill): results→md→skill 沉淀一次清 5 天
scripts/venv/Scripts/python.exe scripts/backfill_bilibili/backfill_bilibili.py --llm-batch
```

| 脚本 | 用法 |
|---|---|
| `backfill_bilibili.py` | 守护模式(无参, 常驻); `--stage download` =视频段(纯 GPU); `--llm-batch` =清账段(5 天/会话批量 sum+distill, **默认走这个**); `--bvid <bvid>` 一次性插跑单视频; 旧路径 `--md-sweep --md-force --md-months <yyyy-MM,...> --md-max-minutes 110 --ignore-pause` =md 批量重合成(仅重合成 md 时用, 枚举 results 四件套齐备日倒序, 最新一期样板自动跳过) |
| `backfill_taoge_index.mjs` | 索引多跳 BFS 重建(产物 index.json) |
| `reset_for_new_skill.py` | 归零器: skill 大改时归档 distill_state+重置, 配合"凡新加 skill 内容全量重跑"铁律 |
| `gen_md_checklist.py` | md 覆盖核对清单生成 |

**开关**: `PAUSE` 文件=总刹车(backfill 守护与 sweep_tzzb_spec 共用; 存在即停); 实例锁(wait_pause 待命期间释放, 一次性 --bvid 可插跑)。
**铁律**: 跑批必须用户发令"开始/继续"; 有 token 才跑; results 产物是唯一事实, state.json 只是加速账本。

---

## wechat/ — 微信公众号盘前语料线(红旗大街发哥)

**全链路**: 用户微信贴链接(发现层=纯人工, 无可靠自动发现) → hermes 跑 `fetch_wechat.mjs --url <url> --write`(抓+挂)
→ hermes 蒸馏写 `spec.md`(【推演要点】五维度) → `--remount --write` 重挂 → Claude 晚间 T+1 核销(【核销】行+沉淀 fage-skill/persona)。

| 脚本/文件 | 用法 | 说明 |
|---|---|---|
| `fetch_wechat.mjs` | `node scripts/wechat/fetch_wechat.mjs --url <url> [--date <d>] [--write] [--force]`<br>`--remount --account <id> --date <d> [--write]` | 产物 downloads/wechat/<account>/<yyyy-MM-dd>/{raw.html,text.md,meta.json,spec.md}; 挂载 md `## 盘前`→`### 微信公众号`→`#### <name>`(整小节覆盖保【核销】/【推演要点】行, 骨架缺失自动补); 出口 0/1抓失败/2被删/3解析/4无md/5反爬/6未知公众号 |
| `wechat_accounts.json` | — | 账号清单(id↔名称), 加公众号=加一行 |

**规约与蒸馏/核销口径= `skills/fage-skill/SKILL.md`**(入口①hermes 盘前蒸馏 / 入口②Claude T+1 核销); 作者会删文=贴链接即抓不攒批。

---

## dfcf/ — 实盘语料存档(隐私唯一落点, 已 gitignore)

只有 `snapshots/`: 用户做 T 后手动贴的成交 txt(牧原做T系列)+live_account.md 账户快照。
em.ps1(东财自动截图) 10/2 已删——手动贴文本流保真度远高于 OCR, 自动化性价比不成立; DirectUI 实测结论存 Claude 记忆, 重建账户感知层先读。

**paper/ 做 T 账本(10/18 建)**: 中行 601988 / 纳指ETF 159941 各三本——`t_decide.py`(决策T A-dbank/A-dndq, 花 token, 0915/0933/1033/1303/1433 + 14:45 收口) / `t_bot.py`(机械T A-tbank/A-tndq + 不T A-hbank/A-hndq, 零 token); 都由 check md `--only mix` 每 5 分钟 `--tick`。
**波段T 四本(10/20 建)**: `t_swing.py` —— 跨日先卖后接; 机械 A-sbank/A-sndq(三态表: 下跌趋势卖 1/2、箱体上沿卖 1/3, 按 ATR / 箱体下沿分档接回, 零 token) / 决策 A-wbank/A-wndq(09:35、14:35 各调一次模型); 14:45 机械收口(三态转上涨 / 现价 ≥ 卖出均价+1ATR / 满 20 交易日); 对照=不T A-hbank/A-hndq; 状态 t_swing_state.json; 同样由 check md 每 5 分钟 `--tick`。
收盘后 `t_review.py`(事后最优 T → t_log/ + 品种 skill 日卡) / `t_skill.py`(skills/bank-skill、nasdaq-skill 的 AUTO 数据画像) / `t_knowledge.py`(全体导师做 T 正反面 → t_knowledge.md), 每晚 check md 跑。
`report_skills.mjs`(10/18 晚): report.html 的「skill 多维对比」(paper 表现 / 对比真人·对照组·拟人度 / 真人近 60 日 / 行为 / 真人做 T / skill 厚度 / 成本, 可排序、按维度开关列) + 「做 T 品种 skill」三本对照卡。
`rand_baseline.py`(10/18 晚 P0): RAND 抛硬币基准——各链买卖日期 / 金额照抄, 只把"买哪只"随机换成当天候选池里的票, 几百次随机里链排第几分位。`signal_lab.py`(P2): 分钟级信号实验室(MOM / REV / VWAP / TFI / RAND, 横截面 IC + 多空价差 + 滚动命中)。牧原私有: `t_private_report.py` → snapshots/report_private.html。
行情: `market/collect_minute.py` 10/18 起多写 `tick_flow.jsonl`(逐笔主动买 / 卖量每分钟, 独立文件, Java 不读; `--flow-only --date D` 补历史)。 `market/collect_book.py`(10/18 晚 P3): 盘口五档快照(新浪, 每 3 秒, 约 40 只) → `book_snap.jsonl.gz`, 给 QI / DI / OFI 攒数据; check md --only mix 调 --ensure 拉起。
**均线 / 三态 / 风险仓位(10/18 晚 A+B+C)**: `quotes/indicators_db.py` 每晚全市场 → `downloads/market/<日>/indicators.jsonl`(EMA 5~388 / MA 5~250 / ATR / ER20 / 三态 上涨趋势·下跌趋势·交易区间·无规则 / 收盘箱体 / 止损候选 / 1% 风险建议股数; `--validate` 三态自检); `tzzb/regime_trades.py` 导师 × 三态 胜率·盈亏比·期望·¼凯利 → 各导师 fingerprint.md `AUTO:三态` 块。
消费方: ✅ 做 T 品种 skill(t_skill.py ⑤ 块 → 决策T 提示词 / 牧原私有报告) ✅ 盯盘 live_watch(三态 / 箱体 / EMA144·169 / 止损候选一行) ✅ 导师指纹(蒸馏 / 加厚读) · ⏳ 周三起(改链, 等前两天开关效果): 决策链事实包每只候选附状态 + 箱体 + 均线、06 按风险算仓位影子记录、mix 按状态分导师权重、RAND 改为同状态随机、拟人度加"买入时状态分布"; 以后 inv-crypto 同一套。
`bilibili/up_case_log.py`: B站 UP 日卡(md 今日操作 + 画面 BS 点 / 持仓页 / 紫色高亮 + 转写原话 + 行情, BS 价位对不上日线标存疑)。

---

## 每日 check md 链条(用户回家一句"check md"触发)

check-cls-md(Java 侧已灌) → **taoge-skill sum**(results→md 桃哥小节; 同日必跑 fetch_quotes --market stock --from-md=分时归档, 东财只留5天) → **taoge-skill distill**(md→taoge-skill 核销沉淀, 日内断言用 stock_trends 核销)
→ **tzzb-skill(sum)**(腿→md 小节, 前置必跑 fetch_quotes --market cb --trends-all) → **tzzb-skill(distill)**(腿→buchitudou0-skill 核销, 机械层零 token 必跑)
→ **fage-skill 入口②**(发哥推演 T+1 核销; 盘前蒸馏=入口①归 hermes 早上)

各 skill 的过程性事件(跑批/格式/立法/事故)追加到对应 `skills/<skill>/PROCESS.md`。

## 盘中资料索引

| 脚本 | 用法 | 说明 |
|---|---|---|
| `scripts/lib/ctx_index.py` | `python scripts/lib/ctx_index.py --code 601988 [--before 1033] [--l1] [--section 新到电报]`；代码里 `ctx_index.pack(code, D, before)` | **盘中资料索引(10/19, 零 token)**：资料覆盖表 + ①3 秒盘口 L0 一句话(L1 5 分钟 K 按需) ②最新时段 facts 目录(带行号) + 按品种关键词预取 ③结构 / 三态 ④外围期货；决策T(t_decide，开关 T_DECIDE_READ=1 时模型可按行号 Read 原文)与实盘挂单共用；--before 回放不偷看；book_snap 收盘后 .gz 也认 |
| `scripts/dfcf/paper/paper_idle_check.py` | `python ... [--date D] [--push]` | **paper 午间体检(10/19)**：在跑账本里 空转(没持仓没挂单没成交) / 做T 底仓没建 / 当天单全被拒，有问题推微信；check md `--only mix` 每天 12:00~13:00 自动跑一次 |
| `scripts/dfcf/paper/paper_vs_real.py` | `python ... [--date D]`(check md 每晚自动) | **paper vs 导师真人 偏离归因(10/19)**：按 日期+代码+导师 串真人持仓 / paper 持仓 / 真人买入 / 当天事实包；逐日算重合、仓位差、候选召回(真人买的票链看不看得见)、收益差和归因；写进各 skill `fingerprint.md` 的 AUTO:paper偏离 块，蒸馏素材包 ⑥ 节读它 |
| `scripts/dfcf/paper/restate_fills.py` | `python ... --date D [--dry]` | **按 10/19 新成交价口径重算某天成交(零 token)**：盘前单越价→开盘价、排板单没触板→撤销；先校验流水能复现账本，整目录备份，最后 matcher --eod --restate |
| `scripts/market/collect_cb_facts.py` | `python ... [--date D] [--no-fetch]`(check md 每晚自动) | **可转债事实表(10/19, 用户口述转债逻辑)**：东财 datacenter 条款表 1~2 个请求 + 行情库算 转股价值 / 溢价率 / 强赎计数(30 日内 ≥130% 天数) / 正股涨停 / 近 5 日涨停次数 / 临期；产物 `downloads/market/<日>/cb_facts.jsonl` + `.md`(成交额前 10、正股涨停的债、负溢价、临赎回临期、热点妖债同族最强)；土豆链次日 04/06 注入精选 |
| `scripts/market/topology.py` | `python ... [--date D] [--show 代码]`(check md 每晚自动) | **市场拓扑(10/19 深夜)**：每只 A 股的邻居 = 扣大盘后近 60/20 日收益相关 + 东财行业 + 申万三级 + F10 精准概念, 可信度 = 相关强度 × 来源数; 期货按行业关键词 + 指数成分。产物 `downloads/market/<日>/topology.jsonl`。消费: `ctx_index` ⑥ 节(邻居此刻涨跌 + 同向/背离思考提示, 预取关键词/期货兜底)、`collect_book` 录实盘/做T 标的前 3 邻居盘口、paper 链 04/06(`CHAIN_TOPOLOGY`)、`paper_vs_real` 同板块半重合。只作参考, 不进任何买卖规则 |

## hermes/ 微信桥接

| 脚本 | 用法 | 说明 |
|---|---|---|
| `cli_relay.py` / `cli_inject.py` | 见 CLAUDE.md「跨机转接」 | `pcN cli: xxx` 转给别的电脑上的 Claude Code 窗口 |
| `fmt_cli_reply.py` | `python fmt_cli_reply.py "原文"` / stdin / `--from-jsonl [--at HH:MM] [--grep 词]`；`--kind` 强制类型、`--debug` 看每行归类、`--send` 排好直接推微信 | **CLI 回复 → 微信格式(10/19, 零 token)**：自动认挂单 / 日报 / 预判 / 兜底；挂单 = 📊状态 → 🔴B档(买) → 🟢S档(卖) → 🔗配对 → ⚡改单条件(触发价加粗)，改单行旧档"撤→新价"、新档"改(原价)"都进表，依据压到约 20 字；日报 = 异常前置、正常压一句 |
