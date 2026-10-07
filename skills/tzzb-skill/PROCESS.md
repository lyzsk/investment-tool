# tzzb-sum 过程记录(2026-10-02 用户立法: 过程可追溯, skill 更新/格式更新/意外都可回查)

> 追加约定: 每次跑批、格式变更、立法、事故, 在最上方加一行 `YYYY-MM-DD 事件: 经过 → 结果/产物`。
> 本文件只记"过程", 规则结论去 `skills/buchitudou0-skill/persona/rules.md`, 管线知识去 Claude 记忆。

- 2026-10-02 **tzzb-distill 建立**(串行链第三棒, 对齐 taoge 侧): 机械层零token必跑
  (profile+review+gen_cb_cases), 漂移/新标的/证伪才 LLM 审议; 与 taoge-distill 差异=行为统计 vs 语言。
- 2026-10-02 **cases.md 建立**(用户立法: 各种案例全进 cases.md, 全量按日期不截断):
  curated 反例 4 条自 rules.md 迁入 + 双尾样本库(逃顶102/卖飞78 全量, `scripts/gen_cb_cases.py` 机械重生成);
  rules.md 反例录改指针。scripts 大重组同 taoge-sum PROCESS 当日条目。
- 2026-10-02 推测层回填 sweep 进行中: `scripts/sweep_tzzb_spec.py`(内容即状态无 state 文件,
  **倒序=新的先补**, 5 日/批 headless `claude -p`, 批后逐日复检【推测】真出现才算成)。
  运行日志=`scripts/backfill_taoge/tzzb_spec_sweep.log`。17:31 进度 105/144 完成, 批13(03-09~03-13)。
  **01-21/01-22/03-06 等早期日无【推测】=还没轮到, 非漏跑**(用户抽查提出, 此条释疑)。
- 2026-10-02 §2.5 立法: 每次合成前必跑 `node scripts/quotes/fetch_quotes.mjs --market cb --trends-all` 归档当日分时
  (东财分钟级只留 ~5 天, 当天不归档永远丢失; 执行质量复盘依赖)。
- 2026-10-02 字段语义纠正: pre/aftPositionPercent=**日级**字段(144/144 天恒 0=从不隔夜),
  腿级仓位方向校验假阳性刷屏 → 消融后从 gen_tzzb_md.mjs 删除, 仅保留缺日哨兵。
- 2026-10-02 硬数据层 177 天回填完成: `node scripts/gen_tzzb_md.mjs --all`(整小节覆盖保【推测】行);
  数据完整性终局核查=51 标的 0 缺日, 75 顶格=服务端重复返回第 1 页(冗余非丢失)。
- 2026-10-02 沉默边界立法: 推测层禁止复述硬数据; ⚠️数据校验标的只许描述可见腿时间特征。
- 2026-10-01 立法: 空仓日照常写小节(空仓=纪律信号, 不许跳过)。
- 2026-09-27 骨架建立(与 buchitudou0-skill 同日): 两层制=脚本硬数据(零 token) + LLM【推测】逆推层;
  双副本防漂移(改 SKILL.md 必 cp 到 .claude/skills/tzzb-sum/)。
- 2026-10-05 新增 5 账本(用户令): 刘忆青(liuyiqing)/量化短线小号实验(lianghuaxiaohao)/A658正好蓝天(a658)/边学本领边实践(bianbenling)/星见野(xingjianye)入 tzzb_ledgers.json; 5 人均为**非纯转债**混合选手(探针实证含股票/北交所票), 硬数据层照常, 【推测】层不变; 各自 persona 线未建(攒样本后按 taoge/fage 模式立项); 量化短线小号实验=疑似程序化实盘(1185 条腿), 其实现方式=待研究 TODO。同日修 gen_tzzb_md.mjs 读旧路径 scripts/tzzb_ledgers.json 断链(10/2 迁移漏改, 硬数据层曾全断)。

- 2026-10-07: tzzb-sum + tzzb-distill 合并为 tzzb-skill(SKILL.md 薄路由 + workflows/{sum,distill}.md); 五人 skill 更名对齐 ledger id(lnq→liuyiqing 等); 逆回购展示保留 API 原值含负号(负=T-1 借出回笼镜像, 用户 10/7 破译: 星见野 4/13 +100.0% → 4/14 -99.7% 镜像对实证)。
- 2026-10-07(晚): cb-skill→buchitudou0-skill 全链正名(用户纠正: K3 原拼 bchitudou0 丢 u); ledger 不进 tzzb API(只 key/user_key)故纯本地改名安全; 同步修两个静默 bug——facts.mjs 导师速览土豆条目双 persona 死路径(土豆规则从未进过速览)、gen_cb_cases.py OUT 平行分叉(curated 保留读不到真文件)。PC1 需执行 tzzb_record UPDATE(见 TODO §2)。
- 2026-10-07(晚) 续: `gen_cb_cases.py`→`gen_tzzb_cases.py` 改名并入 gen_tzzb_ 家族(与 md/profile/review 统一前缀; 纯改名, 数据源仍 review_cb_daily.py 日内口径, 未切 gen_tzzb_review.py——含跨日+缺日涨跌列, 换源=口径变更需立法); 联动引用全改(README/distill 工作流/cases.md/rules.md/本文件历史条目保持原名)。同晚残留 `bchitudou0`→`buchitudou0` 清零: 本机工件 tzzb_profile_all.json/tzzb_review_all.json 的 key 正名(无消费方硬编码, 重跑同效); K3 原拼引文(SKILL.md/PROCESS.md/TODO)与 TODO §2 PC1 迁移 SQL 的 WHERE 旧值按语义保留。
- 2026-10-07(晚) 续2: cases 统一立法(用户取决授权)——**数据层机械+归因层 LLM 两区共存**: gen_tzzb_cases.py 泛化六人(--ledger|--all), 直连 gen_tzzb_review.build(不再依赖 review_cb_daily.json 中间件); review 补"日涨跌%"=卖出日收盘/前收-1(修正 K3 旧口径 c/o-1=开盘基准与列名不符, 例: 鼎捷 1/13 旧-4.21%/新+0.89%=低开4%收平); 跨日 trip 日期列标"(跨N日)", 土豆 trips 435→436(双良跨日腿 FIFO 新配对); 五人 cases.md 首次附机械双尾区(LLM 叙事区保留)。
- 2026-10-07(晚): 15 账本注源落 tzzb_ledgers.json(key 保留为凭证字段名, 新增 match/rank/rate_pct/entered); 选拔规则三闸定稿(排名前20+证据量+持续性0.15%%日, 否决0.75%%日均阈值——土豆0.26%%/日被毙反例), 全表=references/ledgers.md; 6 比赛 key 齐档另 CM3ntt2/Yp6WWwx 发现未采用。
- 2026-10-07(晚二): 第5负例入库=买入太急(mairutaiji, yNkQm2X rank971, -98%, 750trade/768腿/237日, fetch+sync 实证高活跃); 负例候选直查链接(position_change API JSON)已交用户复核, 备选 f1l1y2(双场尾部)/起飞贵/00小满; 信阳谷神=四场收益恒 -73.16%(半死账户)+198trade 最不活跃, 建议换但待用户点链接裁决。
- 2026-10-07(晚三): 负例分层制定稿候选(大亏3+中亏1+小亏对照1)进 references/ledgers.md 待用户点链接复核; 信阳谷神出列(半死账户,可回滚), 鳄狼King(elangking,-10.3%满仓)入列小亏对照组; 窗口审计结论=16 ledger 当前 key 全为最大样本窗口无需换(跨场 nav 长度实测相等); 9/28"污染"考据=9/24 PCB虚构表被勘误立法正确跳过, 产物 01_facts L16 已自带标注, §1.3 可关。
