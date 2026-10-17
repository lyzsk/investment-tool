# 周末零 token 杂项(TODO「三、接下来」第 4 条)交付报告 · 2026-10-17

> 执行: agent34(短期 agent),周六 12:12~12:55。备份全部在 `scripts/temp/agent34_bak/`(按原相对路径存放)。没有动 DB 写、没有动 ~/.claude、没有做 git 操作。
> 真实网络请求: 新浪龙虎榜 5 次(页 2 次 + 席位 jsonp 3 次)、财联社网页版 4 次(专题页 2 次 + 文章页 2 次)、东财 push2ex 3 次(涨停/炸板/跌停池演练)、东财 push2his 1 次(分时主源回归)。没有请求同花顺。
> claude -p: 沙盒里跑了 1 次,花费 $0.66。

---

## 1. A9 时段周检(零 token)

**改动**
- 新建 `scripts/dfcf/paper/slot_weekly.py`: 链时段从 DB `sys_job` 只读(paperChainHandler,status 0=启用 / 1=暂停);真人出手 = tzzb 逐笔腿(`gen_tzzb_profile.load_legs` 只读,去逆回购,同一天同一票同方向同一细档只算 1 次)+ B站 UP md「今日操作」时段词(`up_ops_stats.parse_day` 只读)。
- 判定按五个阶段: 竞价[09:15,09:30)←0915 / 开盘[09:30,10:00)←0927·0935·0945 / 上午[10:00,11:30]←1000·1030·1100·1127 / 午后[13:00,14:30)←1230·1300·1400 / 尾盘[14:30,15:00]←1430·1455。错配规则: ①**无档**: 落在本链没有 slot 的阶段的出手合计 ≥20% ②**空档**: 启用 slot 所在阶段 0 样本(0915 不算)。统计窗口: 近 90 天有时段的样本 ≥20 就用近期,否则用全历史。报告里另附"宽松口径(0915 兼管开盘)"一列,和一张细网格(按 slot 名切分)出手次数表供参考。
- 产物: `docs/research/slot_weekly_<yyyyMMdd>.md`。没有写 slot_activity.json,也不写库。
- `scripts/md/check_md_daily.py` 加了 `--only slot_weekly`: 在交易日判定之前处理(周末是非交易日,原逻辑会直接退出),不占单实例锁;周一到周五跑会输出"跳过(只在周六/周日跑)"。

**验证**
- `slot_weekly.py --selftest` → selftest ok
- `check_md_daily.py --only slot_weekly --dry` → rc=0;真跑 → rc=0,产出 `docs/research/slot_weekly_20261017.md`
- 本周结果: 10 条链有错配,摘录:
  ```
  a658(0915,1030,1400,1455; 79): 无档 32% 开盘(25)(若算 0915 兼管开盘: 0%)
  gaogailvfuli(0915,1300,1400,1455; 355): 无档 56% 开盘(104), 上午(96)(宽松 27%)
  lianghuaxiaohao(0915,1000,1100,1455; 444): 无档 55% 开盘(176), 午后(66)(宽松 15%)
  liuyiqing: 无档 63% 开盘(51)(宽松 5%)   bianbenling: 无档 56% 午后(10), 开盘(9)(宽松 29%)
  xingjianye: 无档 42% 上午(10), 开盘(4)(宽松 30%)   antoo: 无档 39% 开盘(261), 尾盘(196)(宽松 17%)
  taoge: 空档 1230(近 90 天 24 条有时段的出手, 午后 0 条)   qushitiange: md「今日操作」解析出 0 条
  buchitudou0 0% / stzhilang 13% / lubenyuan 18%(样本 17, 仅供参考) 不报
  zjwzlclf / ynw01 / wudaokongfang: 未排程(sys_job 里没有启用的任务)
  ```

**待用户裁 / 需要主会话做的**
- 要每周自动跑,需要在 sys_job 加一条: handler=`checkMarkdownHandler`,param=`--only slot_weekly`(CheckMarkdownHandler 会把 param 原样拼到命令行),cron 例如 `0 0 10 ? * SAT`。我不能写库,所以没加。
- 开盘 30 分钟内的出手算不算 0915 的计划单"负责",是口径问题: 严格口径下 6 条链会报错配,宽松口径下大多不报。报告两列都给了,由用户裁。

**我不确定的点**
- 阶段怎么切(开盘 30 分钟 / 尾盘 30 分钟)是我定的口径;1455 档的 cron 实际是 14:35 触发,我把它归进尾盘阶段。
- UP 只有口述时段词,而且多半没说时段(桃哥 59 条出手里只有 24 条说了时段),结论很粗。天哥 0 条可能是 up_ops_stats 的正则不认他的写法,我没去查。

---

## 2. A12 数据源降级备份(东财 + 财联社)

### 2.1 逐源盘点

| 源 | 用在哪 | 改之前的主→备 | 失效模式 | 本次做了什么 |
|---|---|---|---|---|
| 东财 push2 实时 | dfcf/paper/snapshot.mjs | 腾讯 qt → 东财 → 腾讯分时 → 新浪 → 东财延迟(已接 req_guard) | ~25 次/5min 封 IP(ECONNRESET 静默) | 已经是 5 源 + 请求层,**没改** |
| 东财 clist 榜单 · 涨跌榜 / 板块榜 | scan.mjs | 东财 → 新浪(已有) | 10/11~13 连续失败 140 次 | 没改 |
| 东财 clist 榜单 · 次新榜 | scan.mjs `board次新` | **只有东财**(失败就整榜缺) | 同上 | **加备源**: 本地行情库(`investment_market.security_master.list_date` 近一年 + `kline_day`)自己算 60 日涨跌,零网络请求 → 新脚本 `scripts/quotes/cixin_local.py` |
| 东财 clist 榜单 · 收盘入库 | market/collect_daily.mjs | 新浪 → 东财 clist(没接 req_guard) | 见下方"发现" | **没改**(放进待用户裁) |
| 东财 push2his K 线 | quotes/kline.mjs | 东财 → 腾讯 → 新浪(已有) | — | 没改 |
| 东财 push2his 分时 trends2 | quotes/fetch_quotes.mjs `--market stock` | **只有东财**,也没接 req_guard | 东财只留约 5 天,失败就永久丢 | **接 req_guard + 加备源**: 本地通达信分钟线 `downloads/market/<日>/kline_minute.jsonl`(collect_minute 15:35 采,关注集含 md 提到的票,零请求);备源写的档带 `src` 标记,东财恢复后再跑会自动覆盖成主源数据 |
| 东财 datacenter 龙虎榜 | lhb/fetch_lhb.mjs | 只有东财(原有的备源位是同花顺,未实现,而且禁止用) | 403/429 / 非 JSON 页 → exit 5 | **加备源: 新浪龙虎榜**(总表页 + 席位 jsonp,映射成东财字段,render/build 不用改);只对近 7 天的日子自动切(避免 backfill 历史日大批量打新浪),`--source sina` 可强制,`--no-fallback` 可关 |
| 财联社早报 · 专题页 | cls/fetch_cls_zaobao.mjs `--discover` | api3 App 专题页 → 人工贴链接 | 改版 / 封 | **加备源**: 网页版专题页 `www.cls.cn/subject/1151`(SSR,列表带日期;不是目标日的话连文章都不抓) |
| 财联社早报 · 文章页 | 同上 | 只有 api3 | — | **加备源**: 网页版 `www.cls.cn/detail/<id>`(从 `__NEXT_DATA__.articleDetail` 取正文,转换口径同 parse) |
| 财联社涨停池 / x-quote | cls/fetch_cls_pool.mjs(scan 梯队另有自己的三级转移) | **只有财联社**(失败就 exit 1) | 免签接口,财联社可能随时补签名 | **加备源**: 东财 push2ex 涨停/炸板/跌停池(另一家供应商),映射成财联社字段;梯队头标"(本次=东财备源)"。炸板/跌停单项失败也会单独切东财 |
| 财联社 x-quote 快照/五档/分时 | 生产里没用 | — | — | 没有使用方,不需要备源 |
| 财联社电报 | Java nodeapi | Java 单源 | — | **没做**: 在 Java 里,不在本次脚本范围,放进待用户裁 |

### 2.2 统一请求层 `scripts/lib/req_guard_sources.json`(本次由我独占修改)
新增 3 个源,按最长匹配路由,单独熔断,一个源挂了不连累别的:
- `cls_xquote`(x-quote.cls.cn): 从 `cls` 拆出来,涨停池连败时不会把早报也一起熔断。
- `cls_web`(www.cls.cn/subject、/detail): 只给早报当备源,每天 ≤2 次;阈值没摸过,所以设得从严(连败 3 次熔断 30 分钟,日预算 100)。
- `sina_lhb`(新浪龙虎榜页 + jsonp): 龙虎榜备源一次大约 60~90 个请求,单独熔断,不连累 snapshot/collect_daily 用的新浪行情。

两种语言路由一致(node `--route` 和 py `source_of` 逐条对照,10 个 URL 结果相同);`daily_health` 会遍历全部源,新源自动纳入巡检。

### 2.3 验证(关键输出)
- **涨停池东财备源**(`CLS_POOL_DRILL=1`,3 次 push2ex):
  `> 财联社涨停池 2026-10-16(本次=东财备源): 涨停 61 只 / 炸板 49 / 跌停 10 / 封板率 55% · 最高 11 天 11 板(新华传媒)`;61 只和当日收评"涨停 61"对得上(同一天财联社池是 59 只)。没加 `--write`,产物在 `scripts/temp/agent34_sandbox/cls_pool_drill/`。
- **分时本地备源**(`QUOTES_DRILL=em`,0 次请求): `归档 002696 241 根1min(备源 tdx-local)`;再跑主源(1 次 push2his)→ `归档 002696 241 根1min`,自动覆盖成东财档。两源成交量逐分钟一致(36752 / 70740…),高低价有 0.01~0.03 的聚合差。演练写进真实目录的两个备源档已经删掉;最终留下的 002696_2026-10-16.json 是东财正式档。
- **龙虎榜新浪备源**(`LHB_DRILL=em LHB_SINA_MAX=1 LHB_OUT_DIR=沙盒`,2 次请求): 新浪 66 条 / 59 只,和东财 66 条 / 59 只完全一致(两边代码集合差集为空);000530 三日榜买入 214383553 / 卖出 231379000,东财是 214383656.54 / 231378883.08(差额是新浪"万元保留 4 位"的取整);涨跌幅取本地日线得 9.9567,和东财一致。产物在沙盒,没碰真实 downloads/lhb。
- **早报网页版备源**(`ZAOBAO_DRILL=api3,article ZAOBAO_OUT=沙盒`,2 次请求): `发现(网页版): 【早报】美股纳指大跌超500点… → 切网页版 www.cls.cn/detail/2507382 → 已抓 2274字, ctime 2026-10-17 07:00:00`。
- **次新本地备源**(`SCAN_DRILL=cixin`,用临时副本只跑 board次新,跑完已删): `local-db(东财失败兜底) | 近一年上市 88 只, 数据日 2026-10-16 …`,用时 3.8s。
- 改过的 mjs 全部通过 `node --check`;正常(不演练)路径的代码没有变。

### 2.4 发现(没改,写下来)
1. **collect_daily 的东财备源可能本身就跑不完**: 东财 clist 每页 100 条,A股+转债+ETF+指数一共约 80 页,远超 push2 约 25 次/5min 的封禁阈值。新浪真挂了切到东财,大概率跑到一半被封。要不要改(比如拆批、接 req_guard 排队、换别的备源)由用户裁。我没动这个 15:35 的生产链路。
2. **转债分时归档字段错位**: `fetch_quotes.mjs` 的 `archiveTrends()` 写 `[dt, price, vol] = line.split(",")`,而 trends2 的字段顺序是 时间, 开, 收, 高, 低, 量,所以 `vol` 实际存的是收盘价,`p` 存的是开盘价。这是旧代码,我没改(要改得先确认下游有没有在用这两个字段)。
3. **个股分时归档 10/13 以后没再产出**(downloads/quotes/stock/trends 最新一份是 10/13),疑似写 md 的流程改走 llm-batch 后,不再调用 `fetch_quotes --from-md`。本地 kline_minute 每天都在采,实际已经有替代。
4. rotation.mjs(emweb F10 + push2ex)还没接 req_guard;tzzb/mentor_scope.py 也没接,但 scripts/tzzb 归主会话,我没碰。

### 2.5 我不确定的点
- 东财涨停池很可能不收 ST(10/16 当天正好 0 只 ST,没法验证);用东财备源时 `### ST 股` 可能漏票。题材列放的是东财行业,不是财联社的"题材|归因",输出里已标注。
- 新浪龙虎榜: 只验证了 1 只票的席位;"对应值"会随上榜原因变化,所以我没拿它当涨跌幅,涨跌/换手改从本地日线取(当天日线还没入库时这两列显示 "-")。新浪的反爬阈值没摸过(一次兜底约 60~90 个请求,间隔 2~3s)。
- 早报网页版正文 2274 字,api3 版同一篇有多长没对比(10/16 那篇 api3 版是 3038 字),网页版可能少了图片表格之类的段落。
- 次新本地口径: 上市不足 60 个交易日的票是对首日收盘算,东财 f24 是不是这样算没核;行情库 list_date 最新只到 9/30,10 月新上市的票可能漏;security_master 里还有 353 只没有 list_date。
- 本地分钟线: 10/14 出现过"串号"(TODO 里有记录,collect_minute 未修),备源档里已经标了 src,下游需要的话可以据此过滤。

---

## 3. A14 省 token 三项

### ① check md「盘后合成」会话
**改动**(`scripts/md/check_md_daily.py`)
- cls 核对 / tzzb 推测层 / 发哥核销三步的 LLM 活改成"先登记"(`llm_task`),由新步 `postclose` 合成 **1 个** claude 会话。每个任务保留自己的完成标记,按标记各自记账(cls 照旧写 state,tzzb/fage 照旧靠 md 里的痕迹判断),一个任务失败不影响其他任务。
- 本轮只登记了 1 项时,用**原单步提示词和原 tag**跑,和改造前逐字相同。
- 什么时候合成: 全量轮;`--only postclose`;或 `--only` 里同时点了 ≥2 个这三步之一。单点一步(`--only cls` / `tzzb_sum` / `fage`)照旧单独开会话。
- 步骤顺序: fage 挪到 tzzb_distill 前面(两者没有依赖),postclose 插在 fage 之后、tzzb_distill 之前,所以蒸馏仍在推测层写完之后。合成会话里任务顺序是 cls → tzzb → fage,fage 读到的是 cls 修过的收评。

**验证**
- 离线桩测 `scripts/temp/agent34_sandbox/test_postclose.py`: 三项合成只调 1 次(tag=checkmd-postclose,timeout=7200);只有 1 项时走原 tag 和原提示词;`--only cls` 立即单跑;过截止时刻全部标跳过;没有任务时直接返回 → ALL OK。
- 生产脚本 dry 跑(10/16): 全量 / `--only cls` / `postclose` / `cls,fage` / `tzzb_sum` / `lhb` 都 rc=0,今天(非交易日)正常退出。
- **沙盒真跑 1 次**(`run_sandbox_postclose.py`,mini-root=复制 10/16 md(删掉刘忆青的推测段)+ 两个 skill + cls 图;权限 acceptEdits,只能改 cwd 内文件;不给 Bash): 183s,**$0.66**。合成后的标记解析正确: `cls ✗ / tzzb_sum ✓`。cls 没完成是沙盒的原因: 没有 shell,长图切不了片,模型如实没打标记,也没改任何内容;生产环境有 Bash。会话的工具调用全部在沙盒路径内,真实 md 的 md5 前后一致。

**我不确定的点(重要)**
- **合成不一定更省钱**: 合成省的是 2 次会话固定开销(写缓存约 50~67k/次 ≈ $0.3~0.4/次),但后面的任务每一轮都要背着前面任务的上下文(cls 看图后上下文很大,10/16 单跑 cls 读缓存是 1.3M),读缓存会变多。我按 cls → tzzb → fage 排是为了依赖正确,不是为了省钱。建议上线一周后看 `claude_usage_report` 里 checkmd-postclose 和原来三项合计的对比再定;回滚只要把 backup 拷回去。
- 早上兜底轮(截止 07:45)行为有变化: cls 的活现在要等 UP 步之后才跑,UP 步拖过 07:45 的话,cls 会被标"跳过(过截止)"(原来 cls 在第一步就跑)。
- 这次沙盒样本只有 2 项、而且 cls 没跑完,成本对比没有参考价值。

### ② 蒸馏素材包
**改动**
- 新建 `scripts/md/build_distill_pack.py`(参照 bilibili/build_pack.py): `--skill a,b,... --date d1[,d2]` → `downloads/distill_pack/<日>/<skill>.md`。内容: ①当天本人小节全文 ②收评 + 涨停分析/龙虎榜里的同票行 ③近 5 个交易日本人小节的同票记录 ④同票规则全文(带 rules.md 行号;单条超过 3000 字截断,总量 1.5 万字)+ 待验证规则索引行(来自 rules_index) ⑤画像目录(来自 profile_index)。只用 ≤ 目标日的 md。
- 工作流改成先读素材包: `skills/tzzb-skill/workflows/distill.md`(加 0.3 步,会话开头一次 Bash 生成全部账本的包)、`skills/taoge-skill/workflows/distill.md`(加"第零步",核销第 1 条改为走索引)、`skills/qushitiange-skill/workflows/distill.md`、`skills/lubenyuan-skill/workflows/distill.md`(各加第 0 步)。生成失败就照旧读原件;非交易日顺延块不在包里,照旧读挂载日 md。
- 启动脚本(distill_daily.py / backfill_bilibili.py)都没改,靠工作流里一次 Bash 生成包,所以不用碰 scripts/tzzb。

**验证**
- `--selftest` ok。10/16 打包 9 个 skill 用时 0.16s: taoge 87KB、gaogailvfuli 35KB、liuyiqing 23KB、qushitiange 29KB,其余 1~6KB;多日期、未知 skill(PACK_FAIL,rc=1)都测过。

### ③ "只写变更/新增,不复述原文"
- 上面 4 个 distill 工作流都加了输出纪律: persona 只写变更/新增的条目;用 Edit 局部改,不用 Write 重写整个文件;锚点 ≤30 字;最终回复只列改动清单 + 哨兵。

**我不确定的点**
- taoge 的包有 87KB(约 3 万字),tzzb 一个会话 16 人要读 16 个包,上下文会叠起来。省多少要看上线后的 `claude_usage_report`(读缓存 / 输出)才知道。
- 规则用的是当前版的 rules.md,回填旧日期时会看到之后的验证记录。这和改造前一样,工作流里也有信息截止铁律约束。

---

## 4. claude 用量日报时区复核

- **结论: 不用改**。`claude_usage_report.py` 现在的写法是 ts 按本地时间直接取日期(10/17 健壮性 L3 已经撤掉了 +8h)。这是对的: `claude_call.py` 用 `datetime.now()` 写本地时间,本机是 CST。
- 证据: 抽了 8 条(多数在 23:00~02:00 跨日附近),和会话 jsonl 最后一条的 UTC 时间对照,全部正好差 8 小时。例如 `2026-10-17T01:41:34 profile-index:daxingdaxingdadangxing` ↔ jsonl `2026-10-16T17:41:34Z`;`2026-10-16T23:01:18 bili-distill-batch:qushitiange` ↔ `2026-10-16T15:01:18Z`;`2026-10-13T23:02:04 checkmd-tzzb-spec` ↔ `2026-10-13T15:02:03Z`。
- 重跑 `--date 2026-10-16`: 270 个会话,$507.19,超线 45 个(覆盖了同名日报文件,代码和数据都没变,内容一样)。
- 不确定: 01:00 左右跑的夜间会话按自然日归到第二天,不归到"所服务的交易日"。这是口径问题,没改。

---

## 5. 需要主会话同步 / 处理的事

1. **三位新导师的 workflows 需要同步**: zjwzlclf / ynw01 / wudaokongfang 的 `workflows/distill.md` 现在是指向 tzzb-skill 通用流的薄路由,会自动继承素材包和输出纪律;如果主会话给它们写了专门的蒸馏步骤,要把"0.3 素材包先行"和"输出纪律"两段同步过去。
2. `.claude/skills/` 镜像: 我只把自己改的 4 个 distill.md 单独拷了过去(拷之前确认镜像和改前原件一致)。主会话改完新导师的 skill 后跑一次 `node scripts/sync_skills.mjs` 即可(会顺带覆盖我这 4 个,内容一致)。
3. sys_job 加周末时段周检: handler `checkMarkdownHandler`,param `--only slot_weekly`(只能用户或主会话加)。
4. docs/TODO.md 归主会话: 第 4 条可以拆成"已完成 / 待用户裁"(待裁项: §1 宽严口径、§2.4 第 1、2 条、电报 Java 备源、§3① 一周后的成本对比)。
5. scripts/README.md 我没改: 新增的 3 个脚本(slot_weekly.py / build_distill_pack.py / cixin_local.py)和 4 个源的备源说明,要不要写进 README 由主会话定。

## 6. 改动文件清单

- 新建: `scripts/dfcf/paper/slot_weekly.py`、`scripts/md/build_distill_pack.py`、`scripts/quotes/cixin_local.py`、`docs/research/slot_weekly_20261017.md`、本报告
- 修改(都有备份): `scripts/md/check_md_daily.py`、`scripts/lib/req_guard_sources.json`、`scripts/cls/fetch_cls_pool.mjs`、`scripts/cls/fetch_cls_zaobao.mjs`、`scripts/lhb/fetch_lhb.mjs`、`scripts/quotes/fetch_quotes.mjs`、`scripts/scan.mjs`、`skills/{tzzb,taoge,qushitiange,lubenyuan}-skill/workflows/distill.md`(+ `.claude/skills` 对应镜像)
- 测试产物: `scripts/temp/agent34_sandbox/`(桩测、沙盒 mini-root、各演练产物、探测 HTML)
- 回滚: `cp scripts/temp/agent34_bak/<原相对路径> <原相对路径>`
