# scripts/ 目录说明 + 全链路使用手册(2026-10-02 重组 v2: 域目录化)

> 在用路线: **taoge-skill(学桃哥) + cb-skill(转债高手不吃土豆0)** 两条线。
> 目录按域分文件夹; 根目录只放全局工具+环境; Java 调用的脚本路径已同步改 Java(10/2)。
> 运行前提: mjs 一律 `node scripts/<域>/<脚本>`(cwd=项目根); py 一律 `scripts/venv/Scripts/python.exe scripts/<域>/<脚本>`。

## 根目录(全局)

| 文件/目录 | 用途 | 用法 |
|---|---|---|
| `scan.mjs` | 大盘六榜扫描(涨跌幅/连板梯队/跌停/次新/板块), taoge-skill 事实包用 | `node scripts/scan.mjs --out <run_dir> [--date YYYYMMDD] [--top 30]` → scan.md+scan.json |
| `fetch_holidays_cn.py` | 中国节假日抓取(年度) | `python scripts/fetch_holidays_cn.py` → inv-common/resources/holiday/{year}.json |
| `venv/` | python 环境(ASR+7B+OCR; 已 gitignore) | 重建: `requirements-taoge.txt` / `requirements-cls.txt` |
| `models/` | Qwen2.5-VL-7B(16G)+纠错字典+wheel(已 gitignore) | `process_video.py --download-model` 一次性下载 |
| `dfcf/` | 实盘语料存档(snapshots/ 已 gitignore=隐私唯一落点) | 见文末「dfcf 线」 |

---

## bilibili/ — 桃哥视频管线(发现→下载→ASR→纠错→VLM→产物)

**全链路**: B站视频 → `fetch_bilibili_taoge.mjs`(发现+下载原料) → `process_video.py`(转知识) → `results/bilibili/<mid>/<yyyy.MM.dd>/` 四件套 → taoge-sum 合成进 md。

| 脚本 | 用法 | 产物/出口 |
|---|---|---|
| `fetch_bilibili_taoge.mjs` | `node scripts/bilibili/fetch_bilibili_taoge.mjs --list`(只发现, stdout 末行 `JSON:[...]`)<br>`node scripts/bilibili/fetch_bilibili_taoge.mjs [--bvid BVxxxx] [--out <目录>] [--video-only\|--audio-only]` | `<out>/<bvid>.mp4`+`.m4a`+`.json`; 幂等补缺; 0=就位 1=失败 |
| `process_video.py` | `scripts/venv/Scripts/python.exe scripts/bilibili/process_video.py --bvid <bvid> --mp4 <路径> --m4a <路径> --out <结果目录>`<br>调试口: `--stage asr,correct,vision,aggregate` / `--keep-frames` / `--download-model` | `<bvid>.raw.txt`+`.tsv`+`.txt`(合成读的)+`.vision.json`; 幂等; GPU 串行(ASR 卸载再上 7B) |

**Java 驱动(生产唯一入口, 勿手工并行跑)**: `bilibiliVideoHandler` 单 job 三段(发现→下载→process_video), 状态机走 `bilibili_video` 表(VISION_DONE 后等 taoge-sum 合成→SUMMARIZED→30 天原料物理删除)。
**依赖**: scripts/models/(字典+7B); 无 cookie 方案(search HTML+view/playurl API 不吃风控, 空间列表已风控勿用)。

---

## tzzb/ — 转债高手(不吃土豆0)线

**全链路**: 同花顺投资账本 API → `fetch_tzzb.mjs`(Java cron 小时级) → `downloads/tzzb/<ledger>/`(raw 证据层) → Java sync 入 `tzzb_record` 表 → `gen_tzzb_md.mjs`(硬数据层) + tzzb-sum skill(【推测】层) → md `#### 不吃土豆 0` → tzzb-distill(机械核销进 cb-skill)。

### 每日链(15:10 抓取后, check md 例程内)

```bash
node scripts/quotes/fetch_cb_quotes.mjs --trends-all      # ①当日有腿标的分钟级分时归档(东财只留~5天, 必做!)
node scripts/tzzb/gen_tzzb_md.mjs --ledger bchitudou0 --date <yyyy-MM-dd> --write   # ②硬数据层进 md
# ③tzzb-sum skill: LLM 补【推测】层(逐条标【推测】, 不复述硬数据)
# ④tzzb-distill 机械层(零 token, 每日必跑):
scripts/venv/Scripts/python.exe scripts/tzzb/profile_bchitudou0.py
scripts/venv/Scripts/python.exe scripts/tzzb/review_cb_daily.py --json scripts/backfill_taoge/review_cb_daily.json
scripts/venv/Scripts/python.exe scripts/tzzb/gen_cb_cases.py    # 依赖 ② 的 json, 重生成 cases.md 双尾区
```

### 脚本明细

| 脚本 | 用法 | 说明 |
|---|---|---|
| `fetch_tzzb.mjs` | `node scripts/tzzb/fetch_tzzb.mjs [--ledger <id>]` | 默认跑 `tzzb_ledgers.json` 全部账本; 产物=downloads/tzzb/<ledger>/(position_change/nav_daily/month/position/change_bs_*/state.json); 出口 0=正常 2=凭证失效 1=失败 |
| `gen_tzzb_md.mjs` | `--ledger <id> --date <d> [--write]` / `--ledger <id> --all --write` | 硬数据层(零 token): 净值行+FIFO round-trip 明细+汇总; --write 整小节覆盖**保留【推测】行**; --all 全历史回填 |
| `review_cb_daily.py` | `[--json out.json]` | 执行质量复盘: 卖分位/卖飞上限/持收增量/买滑点/日度对照 |
| `profile_bchitudou0.py` | `[--json out.json]` | 机械画像: 900腿统计+市况反向联动(T-1 口径) |
| `gen_cb_cases.py` | (先跑 review --json) | cases.md 双尾样本库区机械重生成(curated 区保留); 阈值 \|持收增量\|≥5% 全量不截断 |
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

## quotes/ — 行情获取域(转债+个股, 东财公开接口)

| 脚本 | 用法 | 说明 |
|---|---|---|
| `fetch_stock_trends.mjs` | `node scripts/quotes/fetch_stock_trends.mjs --from-md <yyyy-MM-dd> [--force]`<br>`--codes 600127,002264 [--date <d>]` | 桃哥=分时盘口选手, 日内断言("冲高2点没走"/"尾盘硬拉")需分钟级核销; 东财分时只留~5天=当天必归; --from-md 抠 md 全文（6位代码）去重归档 → downloads/quotes/stock/trends/<code>_<date>.json; 市场位自动翻转(北交所) |
| `fetch_cb_quotes.mjs` | `node scripts/quotes/fetch_cb_quotes.mjs --trends-all`<br>`--kline-all` / `--kline --code <c>` / `--trends --code <c>` / `--snap --code <c>` | 转债行情(10/2 自 tzzb/ 迁入): 日线回填(双源东财+腾讯)/分时归档/实时快照; --trends-all 单向依赖 downloads/tzzb 账本腿; 产物 downloads/quotes/cb/{kline,trends}/ |

---

## md/ — md 工具

| 脚本 | 用法 | 说明 |
|---|---|---|
| `format-markdown.mjs` | Java MarkdownFormatServiceImpl 调用 | prettier 格式化(需项目根 npm install prettier) |
| `migrate_md_template.mjs` | `node scripts/md/migrate_md_template.mjs [--dry] [dir...]` | **模板迁移常备**: stock-template.md 变更后跑它批量同步历史 md(模板驱动/标题归一/缺节补骨架; 幂等) |

---

## backfill_taoge/ — 桃哥历史追溯(整目录已 gitignore, 只在本机跑)

**全链路**: `backfill_taoge_index.mjs`(BFS 建待办索引 index.json) → `backfill_taoge.py` 守护(待办=索引-results 扫描; 时间窗/GPU/PAUSE 三守卫; 下载(先查 reuse/ 硬链复用)→process_video→state 记账) → results 四件套 → md-sweep(taoge-sum 批量合成) → distill(taoge-distill 核销沉淀, distill_state.json 账本)。

| 脚本 | 用法 |
|---|---|
| `backfill_taoge.py` | 守护模式(无参, 常驻); `--bvid <bvid>` 一次性插跑单视频; `--md-sweep --md-force --md-months <yyyy-MM,...> --md-max-minutes 110 --ignore-pause` =md 批量重合成(枚举 results 四件套齐备日倒序, 最新一期样板自动跳过) |
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

---

## 每日 check md 链条(用户回家一句"check md"触发)

check-cls-md(Java 侧已灌) → **taoge-sum**(results→md 桃哥小节; 同日必跑 fetch_stock_trends --from-md=分时归档, 东财只留5天) → **taoge-distill**(md→taoge-skill 核销沉淀, 日内断言用 stock_trends 核销)
→ **tzzb-sum**(腿→md 土豆小节, 前置必跑 fetch_cb_quotes --trends-all) → **tzzb-distill**(腿→cb-skill 核销, 机械层零 token 必跑)
→ **fage-skill 入口②**(发哥推演 T+1 核销; 盘前蒸馏=入口①归 hermes 早上)

各 skill 的过程性事件(跑批/格式/立法/事故)追加到对应 `skills/<skill>/PROCESS.md`。
