# scripts/ 目录说明

本目录分四块：**桃哥管线**(bilibili-taoge/)、**东财快照**(dfcf/)、**AI 自研策略 k3-inv**(k3-inv/)、以及项目原有的根目录脚本。

---

## bilibili-taoge/ — 桃哥管线（audio → text → 纠错 → 注入 md → 学习 → 回测）

针对 B站 UP主「股市-目标1000万的股桃」(mid=625315686) 的完整流水线。

### 采集与转写
| 脚本 | 用途 |
|---|---|
| `fetch_taoge.mjs` | 抓桃哥最新视频列表（B站 API，无 cookie)，对比本地判断有无更新 |
| `crawl_index.mjs` | BFS 爬全部历史视频索引 → `downloads/index.json`(archive/related API) |
| `backfill_prepare.mjs` | 用 index.json ∩ stocks/*.md 日期，生成追溯下载工作清单 |
| `coverage_report.mjs` | 覆盖率报告： index.json 日期 vs stocks 已有 md，看缺哪些天 |
| `transcribe.py` | faster-whisper 单文件转写 m4a → txt（用本目录 venv) |
| `batch_transcribe.py` | 批量转写 downloads/audio/*.m4a → downloads/txt/，可断点续跑 |
| `watch_and_inject.mjs` | 等 small 批跑完 → 自动纠错+注入 md（一次性看护） |
| `watch_and_medium.mjs` | 等 small 批完 → 自动启动 medium 模型重跑 |
| `watch_and_finalize.mjs` | 等 medium 批完 → 自动纠错+注入（已完成于 2026-09-19 06:20) |

### 纠错与注入
| 脚本 | 用途 |
|---|---|
| `correct_names.py` | 股名纠错 v4: jieba + 拼音反查 + 首字母校验 + 实体锚定（SK海力士类）。`python correct_names.py <输入目录> <输出目录>`，字典 `downloads/entity_dict.json` |
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

## k3-inv/ — AI 自研操盘策略（非桃哥）

k3-inv = k3(我) + 用户引导， 纯 AI 策略： **加红电报(催化) × 威科夫(结构) × 李大霄(选股与心性) × AI 综合仲裁**, 与桃哥管线并列对照（plan A = 学桃哥情绪周期， k3-inv = 质量过滤的催化跟随, 标的池几乎不重叠）。

| 内容 | 用途 |
|---|---|
| `STRATEGY.md` | 策略规格 v0.1（信息可用性/李大霄筛/威科夫入场/电报催化/卖出与仓位/成交口径）, 回测前冻结 |
| `telegraph/*.txt` | 从 stocks/2026S3/*.md `## 加红电报` 提取的电报流（13 个交易日, 738 条, 回测数据源) |
| `backtest/runs/` | 回测结果（首个: k3-v0.1-20260901_0918) |
| `README.md` | 定位与规则（每策略一子目录/walk-forward/成交口径与桃哥一致/复用 kline 缓存） |

SQL 表设计在 `sql/k3inv.sql`(6 表： signal/watch/strategy/run/decision/trade)。

---

## 根目录（项目原有， 非本次新增）
| 脚本 | 用途 |
|---|---|
| `format-markdown.mjs` | md 格式化， **被 Java 后端 MarkdownFormatServiceImpl 通过 ProcessBuilder 调用**，勿动接口 |
| `fetch_holidays_cn.py` | 抓中国节假日数据（inv-common resources/holiday/*.json 的来源） |
| `ocr_zdfb.py` | 早期 OCR 涨停分析图片的实验脚本（现 OCR 已由 Java Tess4j 承担） |
