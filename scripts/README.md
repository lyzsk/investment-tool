# scripts/ 目录说明

本目录分五块：**plan-a**(学桃哥管线， 收益率最高)、**plan-b**(转债日内， 目前日内最强， 骨架待建)、**plan-c**(AI 自研策略， 原 k3-inv, 最弱缺参考系)、**东财快照**(dfcf/)、以及项目原有的根目录脚本。

> 三计划定位(2026-09-24 用户定): plan-a=学桃哥(有参考系=桃哥视频) / plan-b=转债(有参考系=用户自己实盘+高手语料) / plan-c=AI 自学(无参考系, 最弱——同花顺大赛/淘股吧高手语料采集就是为了给它补参考系)。
> 2026-09-24 改名: `bilibili-taoge/` → `plan-a/`, `k3-inv/` → `plan-c/`。策略 ID 不变(决策日志里仍叫 taoge/k3), 只动目录名。

---

## plan-a/（原 bilibili-taoge/）— 桃哥管线（audio → text → 纠错 → 注入 md → 学习 → 回测）

针对 B站 UP主「股市-目标1000万的股桃」(mid=625315686) 的完整流水线。

### 采集与转写
| 脚本 | 用途 |
|---|---|
| `fetch_bilibili_taoge.mjs`（在 scripts/ 根，9/27 起） | 桃哥视频发现+产物下载（由 fetch_taoge/fetch_video 合并）: `--list` 只发现（Java handler 消费）; `--bvid X --out 目录` 一次拿 mp4+m4a+json(playurl 一次请求取 dash 双轨，产物已存在则跳过） |
| `process_video.py`（在 scripts/ 根，9/27 起） | 视频处理全管线（transcribe+correct_names+vision_extract+aggregate_pages 四合一体）: ASR→纠错→7B视觉→pages聚合 → `<out>/<bvid>.txt+raw.txt+tsv+vision.json`。`--bvid --mp4 --m4a --out`, `--stage asr,correct,vision,aggregate`, 幂等跳已完成阶段 |
| `crawl_index.mjs` | BFS 爬全部历史视频索引 → `downloads/index.json`(archive/related API) |
| `backfill_prepare.mjs` | 用 index.json ∩ stocks/*.md 日期，生成追溯下载工作清单 |
| `coverage_report.mjs` | 覆盖率报告： index.json 日期 vs stocks 已有 md，看缺哪些天 |
| `transcribe.py` | （9/27 已并入 scripts/process_video.py, 文件已删） |
| `vision_extract.py` | （9/27 已并入 scripts/process_video.py, 文件已删） |
| `setup_vision.sh` | 视觉/OCR 环境一键安装固化（9/24 晚）: venv依赖+torch cu124本地wheel+Qwen2.5-VL-7B模型，幂等。`bash setup_vision.sh` |
| `inject_vision.py` | vision JSON → md `### 桃哥` 下插 `#### 画面`（口述未提增量/互证/板块指数）; 名≥2帧投票或OCR确认， 代码只采信OCR同屏共现投票（号段过滤+严格多数） |
| `batch_vision_q3.sh` | ⚠️历史归档（Q3 视觉管线批量已完成；引用的 fetch_video/vision_extract 已删，勿直接重跑） |
| `aggregate_pages.py` | （9/27 已并入 scripts/process_video.py, 文件已删） |
| `batch_vision2_q3.sh` | ⚠️历史归档（Q3 58 视频 Vision2.0 重跑已完成；引用的 vision_extract/aggregate_pages 已并入 scripts/process_video.py, 勿直接重跑） |
| `synthesize_prompt.md` + `batch_synthesize_q3.sh` | 合并综合陈述批量合成（headless claude -p, 倒叙近两周优先， 断点=无####解读/画面）: 转写+vision pages+analysis → 五要点合并， 删 #### 画面/解读 |
| `batch_transcribe.py` | 批量转写 downloads/audio/*.m4a → downloads/txt/，可断点续跑 |
| `watch_and_inject.mjs` | 等 small 批跑完 → 自动纠错+注入 md（一次性看护） |
| `watch_and_medium.mjs` | 等 small 批完 → 自动启动 medium 模型重跑 |
| `watch_and_finalize.mjs` | 等 medium 批完 → 自动纠错+注入（已完成于 2026-09-19 06:20) |

### 纠错与注入
| 脚本 | 用途 |
|---|---|
| `correct_names.py` | （9/27 已并入 scripts/process_video.py, 文件已删；字典仍在 downloads/stock_dict.json+entity_dict.json) |
| `inject_md.mjs` | 把转写+解读注入 stocks/*/YYYY-MM-DD.md 的 `## 复盘 → ### 桃哥 → #### 解读`。`--dir <txt目录> --replace` 替换已有小节 |
| `extract_prompt.md` | 从转写文本提取"解读"JSON 的 LLM prompt（大盘判断/提及个股/操作/风格规则） |

### 行情数据与回测
| 脚本 | 用途 |
|---|---|
| `fetch_m5.mjs` | 抓腾讯 5 分钟 K线（约 2 周深度）→ `downloads/kline/<code>_m5.json`。`node fetch_m5.mjs sh600127 ...` |
| `day_card.mjs` | 日内回放卡片： 打印某日 前收/开/收/高低点时刻+关键 bar，回测 replay 用 |
| `backtest/` | 回测结果：`runs/pilot-20260915/`(单日试跑）、`runs/pilot-2week/`(9/02→9/18 两周走查， 含 report.md/trades.csv/equity.csv/settlement.json) |
| `rules_spec.md` | 桃哥操盘规则的规格草稿（入场/出场/仓位/成交口径） |

### 数据目录（downloads/，不进 git 也不用手动看）
`audio/`(m4a)、`txt/ txt_fixed/ txt_medium/ txt_medium_fixed/`(各级转写）、`analysis/`(每日解读 JSON)、`kline/`(m5 缓存）、`index.json`、`entity_dict.json`、`*.log`。venv/ 是 Anaconda 建的 python 环境（faster-whisper)。

---

## dfcf/ — 东财客户端快照（只读！）

读取本机已登录的东方财富终端（进程 mainfree，交易窗口标题"东方财富证券")。**原则： 只截屏读取， 绝不点击买入/卖出区， 不输入密码； 用户在场时禁止运行（窗口会闪现)。**

统一入口只有一个脚本 `em.ps1`(8 个旧 em_*.ps1 已合并删除）:

```powershell
# hermes / Claude 调用方式(在 scripts/dfcf/ 下, 输出单行 JSON, file 字段是截图路径, 用 Read 工具看图)
powershell -ExecutionPolicy Bypass -File em.ps1 -Action probe                  # 找进程+交易窗口, 不截图
powershell -ExecutionPolicy Bypass -File em.ps1 -Action read                   # 截【资金持仓】页(默认页, 最常用)
powershell -ExecutionPolicy Bypass -File em.ps1 -Action read -Page 当日成交 -RealClick  # 翻页再截(真实鼠标, 仅无人时用)
powershell -ExecutionPolicy Bypass -File em.ps1 -Action hide                   # 重新隐藏窗口
```

核心手法： EnumWindows 按 PID+标题+子窗口 `_DC` 类名后缀识别交易主窗口 → ShowWindow(SW_SHOWNA) → MoveWindow 1600x950 → PrintWindow(PW_RENDERFULLCONTENT) 截 PNG → 原本隐藏则还原。已验证的关键坑： 隐藏窗口截图全黑； 合成消息点击(PostMessage/SendMessage)被东财 DirectUI 全部忽略， 翻页只能 -RealClick 注入真实鼠标（光标物理移动约1秒+窗口短暂前台， 仅限无人值守）; 账号掉线（页面值 "--"）时翻页无响应， 需用户手动重登。
截图输出 `snapshots/` 已 gitignore（资产隐私）。已验证可拿到： 总资产/可用资金/证券市值/持仓盈亏/个股持仓， 与手算交叉验证一致。

---

## plan-c/（原 k3-inv/）— AI 自研操盘策略（非桃哥）

k3-inv = k3(我) + 用户引导， 纯 AI 策略： **加红电报(催化) × 威科夫(结构) × 李大霄(选股与心性) × AI 综合仲裁**, 与桃哥管线并列对照（plan A = 学桃哥情绪周期， k3-inv = 质量过滤的催化跟随, 标的池几乎不重叠）。

| 内容 | 用途 |
|---|---|
| `STRATEGY.md` | 策略规格 v0.1（信息可用性/李大霄筛/威科夫入场/电报催化/卖出与仓位/成交口径）, 回测前冻结 |
| `telegraph/*.txt` | 从 stocks/2026S3/*.md `## 加红电报` 提取的电报流（13 个交易日, 738 条, 回测数据源) |
| `backtest/runs/` | 回测结果（首个: k3-v0.1-20260901_0918) |
| `README.md` | 定位与规则（每策略一子目录/walk-forward/成交口径与桃哥一致/复用 kline 缓存） |

SQL 表设计在 `sql/k3inv.sql`(6 表： signal/watch/strategy/run/decision/trade)。

---

## plan-b/ — 转债日内策略（骨架， 2026-09-24 新增）

用户实盘转债日内线（目前三计划中日内最强, 但无代码无沉淀）。只有 README: 定位/待回答的第一性问题/数据需求(交割单导出、集思录溢价率、强赎下修日历)。建设顺序见 `docs/TODO.md`。

---

## 根目录（项目原有， 非本次新增）
| 脚本 | 用途 |
|---|---|
| `format-markdown.mjs` | md 格式化， **被 Java 后端 MarkdownFormatServiceImpl 通过 ProcessBuilder 调用**，勿动接口 |
| `cls_image_ocr.py` | 财联社图自动填 md(9/24 晚， 全本地 OCR 0 token): `python cls_image_ocr.py <图> --type wp|sp|wjzt|zt` → stdout(UTF-8）出 md 小节内容（wp→午评/wjzt→午间涨停分析/sp→收评/zt→涨停分析）; 校验不过非0退出 PARSE_FAIL。依赖见 requirements-cls.txt(`pip install -r scripts/requirements-cls.txt`, 任意 python 环境均可; 本机用 scripts/venv 隔离)； 9月 wp/sp 30/30 + wjzt/zt 7图全 PASS |
| `fill_cls_md.py` | cls 图批量填 md(9/24 晚, Q3 一次性回填已完成): `--from/--to/--overwrite/--backup`; PARSE_FAIL 只告警不写。**保留原因**: wjzt 23 天 PARSE_FAIL 待 Java 侧修解析器后, 历史回填仍走它(Java 只有日常增量入口), 回填完成可删。同 requirements-cls.txt |
| `requirements-cls.txt` | 根目录脚本 python 依赖(9/25, 从 plan-a/venv 剥离): 只装 rapidocr/onnxruntime/opencv/numpy/pillow ~300MB, 版本与 plan-a 实测一致 |
| `fetch_holidays_cn.py` | 抓中国节假日数据（inv-common resources/holiday/*.json 的来源, 每年需重跑） |
| ~~`ocr_zdfb.py`~~ | 已删(9/27): 早期实验脚本, OCR 已由 Java Tess4j 承担, 零引用 |
