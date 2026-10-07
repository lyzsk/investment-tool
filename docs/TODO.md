# investment-tool TODO（唯一工作清单, 2026-10-07 晚定稿版）

> 目标函数: 策略收益养活 Claude 订阅费（10 万本金: Pro≈年化 1.8% / Max$100≈9.1% / Max$200≈19%）
> 消费约定: **人读=前半（§1-§3）, AI 读=后半（§4 起）**; ✅ 项不存 git, 细节看 git log + bugs.md
> 优先级: ★★★=10/8 首跑必须 / ★★= 窗口期 / ★= 等触发; 【PC1】= 绑本机 / 【PC2✓】= 笔记本可干 / 【用户】= 人动手

---

# §1 待建（已拍板, 排 10/8 后）

**paper 两级制**（10/7 拍板+大部分已落: matcher 17 账本/驱动器泛化/seed/8 UP job）, ⏳剩三件:
1. **盘前档引擎**: 10 导师单会话精简链, 32B 本地+抽检, bge-m3 捞规则（quota 14万/周撑不起 11 条云端日链）
2. **相似度 scorer**: 持仓 Jaccard + 操作对齐 → scorecard（用户令: 至少给个相似度百分比）
3. **负样本 gen_tzzb_negstats.py + 05 消费钩子**（负例 5 人语料已全量入库: 大亏3+中亏1+小亏对照1）

**选手管线终态（10/7 定稿, 见 skills/tzzb-skill/references/ledgers.md）**: 16 人=11 正+5 负; 选正例三闸=每场总榜前20+出手≥30日/腿≥100+持续性≥0.15%/日; 观察池=前20宽进(⏳players.json 建档待做, 周期榜面复查零管线成本), 三闸转正严出; 速览现役=土豆+五人+发哥+两UP, 新 5 正例等盘前档引擎接入。

# §2 10/8 首跑（A 级, 无人值守）

- 盘前 09:07 Claude 自动醒（durable cron）: `node scripts/dfcf/paper/reset_books.mjs`（A 线四本 10 万发令枪, 幂等, 已 dry 验证）→ 核昨晚收尾任务 → 必要时单独重跑 9/28（下午双驱动污染过）
- 09:13 卢本圆链 → 09:15 桃哥+转债+天哥全时刻表; **观察点**: ①速览逐源回应 ②发哥刹车被 02 回应 ③cand_snap 价格锚 ④废单率 ⑤20:00 07 复盘 ⑥勘误表跳过
- 收盘后: 15:05 EOD → 明晚第一份真 report/scorecard（撮合+nav 当日新鲜出炉）
- ⚠用户睡前最后一步: **IDEA 最后 rebuild+rerun 一次**（第四刀: position_snap 按日去重——不 rebuild 则明天 15:10 起 job 对缺 9/30 nav 的账本每小时失血几十行 snap, 今天已洗 123 行）

# §3 今晚在跑（自动, log=scripts/taoge-chain/resume_1007_night.log）

- 9/28-30 A-taoge 回放（云端 claude token, 非本地模型; 每天约 30-60min）→ 天哥 10/3 补账; 9/28 结束后需单跑一次（下午孤儿驱动污染）
- 视频管线: 桃哥 2 稿处理中（17:30 job 起, ASR CPU 全核=whisper 物理特性非事故; 显存闸+单实例已上）; 卢本圆 10 稿待其 job 下载（retry 已复位）

# §4 持续线（日常/等发令）

| # | 项 | 归属 |
|---|---|---|
| 1 | backfill 下载层 45 待办（PAUSE 开关; 引擎=scripts/backfill_bilibili/backfill_bilibili.py --up 三UP） | PC1 用户 |
| 2 | 夜跑 distill 断点 2026-07-07（distill_state.json） | PC1 |
| 3 | 回放帧 16 例+taoge-sum 回放帧过滤+distill 人工审核 | PC2✓ |
| 4 | tzzb: ①五闸门审议首跑 ②op 字段破译 ③转债情绪 ④cb 分时验证 | PC1 |
| 5 | cls wjzt 解析器 23 天 PARSE_FAIL | PC1 |
| 6 | PaperChainHandler exit 3 频率→自动续链? | 等首跑 |
| 7 | persona 反问（方案 B 已落） | 等首跑 |
| 8 | fage 权重定级（核销 alpha 后） | 等 2-3 周 |
| 9 | 牧原做 T（30 日振幅现算/R-PNL-TRUE） | PC1 用户 |
| 10 | TODO 0.7 缺日回填两洞 | PC2✓ |
| 11 | §F 残留: **①数据源共享工具层(用户令, 仿 inv-common)**: `scripts/lib/`=`sources.mjs` 注册表+`ak.py` akshare 统一出口, client.mjs 升格单一入口, kline/matcher/snapshot 改 import ②跷跷板矩阵/转债域 facts 榜单/seed.json 校对/异构对抗/matcher 核销操作卡 | PC2✓ |
| 12 | 本地化梯队: 14b 纠错/32b 推测/bge-m3 检索（模型在 ~/.ollama/models）; **32B B' 欠账=stzhilang 尾段+chong5000w, ollama 重开后 llm_batch_tzzb 幂等续跑** | PC1 |
| 13 | tzzb 样本一期收尾: 16 人全量入库+注源完成; 待=数据质量核→新 5 正例 distill 准入裁决; players.json 观察池建档 | PC1 |
| 14 | venv 正名 scripts/venv→.venv: **不能 mv**（pyvenv.cfg/launcher 硬编码绝对路径）, 需重建+freeze 装回（akshare 等）+冒烟+删旧; gitignore:79+Java python() 硬路径联动 | PC1 |
| 15 | PC2 清理测试账本: `rm -rf scripts/dfcf/paper/{books,plans,facts}` | PC2✓ |
| 16 | hermes 微信桥: 微信主客户端(Weixin.exe)死于内存事故, 需杀 8 个 WeChatAppEx 孤儿+重登微信+重启桥（用户手机操作） | 用户 |

---

# §5 批判性审视（10/6 自审, 按危害排序）

1. **目标函数偏离（最重）**: 100% 工程投入, 零产出在"明天买什么"。10/8 首跑=硬 deadline。
2. 推测层质量债: 盲审 40 段 good30/fair8/poor2; 剩 3 冲突段修正。
3. rules 重审: 剩五人 rules 重审（持仓行为类, LLM 活晚链做）。
4. 东财限频: scan 挂=链中止; 对策=首跑日盯 facts, 中期降级昨日数据+标注。
5. 速览信噪比未实测（9241 字六源）: 10/8 观察项。
6. IC 样本量小, 权重全标"暂定", n≥30 再定。
7. 两套账本风险: matcher --init 签名确认。
8. TODO 治理: 活跃+存档一行, 历史靠 git log。

# §6 架构立法 → 已归档 git（10/7 整章删除）

**终裁**: tzzb=仿 arena 加权（等权速览+IC 晋升盘前档轻量链, 三闸选人）; bilibili=决策链（paper 账本即验证装置）。法条落点: switch-case=§4.11 / md 记录=gen_tzzb_md 头注 / skill 结构=各 SKILL.md / 纪律+git禁写=memory。

# §7 paper 设计（§E 精存）

> 目录 scripts/dfcf/paper/（状态 gitignore）。架构: 事实层共用(零token)→决策层分账(稀疏LLM)→执行层全自动。A级时刻表: 09:15全链→09:27纠偏→09:45/10:00/10:30确认→11:27定位→12:30午间链→14:00/14:30→14:55尾盘。契约: 条件单主形态, 废单率=质量度量。参数: 总仓≤3成/单票≤1.5成/留≥4成现金; 转债=全仓单票。回放记录(旧栈): C-taoge+6.71%/C-cb+5.15%/A-taoge-0.75%(9/28-30)。**已知不自信**: matcher 撮合=活快照, 真 replay 模式未建——回放成交数字不算数(10/4 记档)。

# §8 后排大活【全 ★】

1. 存储层 Phase 1 → 2. TaogeAnalysisController → 3. 账户感知（等语料）→ 4. 第5梯队语料（moni/tgb）→ 5. 结构件 P1 → 6. hermes 链路+全量回测+拟人化 → 7. watchlist 桥。

---

# 短板清单（hermes 10/6 审视）

**总评: 记忆系统 A 级, 神经系统 D 级**——沉淀解决"他是谁", 解决不了"他此刻怎么想"。
🔴①实时层断层(盘中人格全是昨天的)→补丁=盘前人格转条件单式预案, 盘中只做条件匹配
🔴②信号聚合层=0(谁赢靠拍脑袋, 全项目最贵的洞)
🔴③验证闭环没跑过(建议→记账→核销→调权, 一天都没转)
🟡④执行层最后一公里(废单率/失效条款机器执行)
🟡⑤失败样本库=0(用户认领)
🟡⑥基本面全盲——**方案 10/7 定稿**: akshare 主力(冬测 3/4 通: 同花顺资金流✓/东财龙虎榜✓/业绩预告✓, 解禁参数待校)+全 switch-case 加 akshare 源; 底线=妙想MCP/同花顺AI/WIND 不用; 龙虎榜 scripts/fund/ 双源脚本化; 窗口分层制=资金{1,3,5}+趋势态扩{10,20}/量能{1,5,10}/池级{20}; 池子=pools.json+ZT池+tzzb position_snap+自选; 顺序=公告层(含业绩预告日历)→资金流+龙虎榜→财务静态季更; 05 禁手先行; 排期 10/8 后。

**venv 模型 vs ollama**: venv 侧=Qwen2.5-VL-7B(16G HF 权重, process_video 视觉真值, 进程内加载独占15.4G显存); ollama 侧=qwen3 14b/32b+bge-m3(GGUF, 常驻服务 11434: 14b=ASR纠错/32b=tzzb推测/bge-m3=检索)。显存互斥→错峰立法。
