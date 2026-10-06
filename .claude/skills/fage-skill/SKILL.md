---
name: fage-skill
description: "Use when 处理红旗大街发哥盘前推演: 入口①盘前蒸馏(hermes 早上贴链接后: 抓取挂载+写推演要点 spec.md) / 入口②T+1核销(Claude 晚间 check md 链: 对照实际盘面给推演打分+沉淀 persona)"
---

# fage-skill · 红旗大街发哥盘前推演线(第三导师: 盘前情绪周期事实层)

> 建立: 2026-10-02。定位: 桃哥(盘后复盘)+土豆(转债行为)+发哥(盘前推演)=三导师。
> 发现层=**人工贴链接**(用户拍板: 无可靠自动发现, 不搞 sogou/cron)。作者会删文=贴链接即抓, 不攒批。
> 📜 过程记录= 本目录 `PROCESS.md`(跑批/格式/立法/事故逐行追加)。
> ⚠️ 双副本: 编辑后必 `cp -r skills/fage-skill/. .claude/skills/fage-skill/`。

## 入口①: 盘前蒸馏(hermes, 用户早上微信贴链接后)

### hermes↔Claude 规约(用户微信对话 → 正常链路的唯一接口)

**用户语法**: 消息含"盘前"+文章链接即可(如 `今日盘前 https://mp.weixin.qq.com/s/xxx`);
补历史= `盘前 9/29 <url>`(日期可省, 页面 createTime 为准)。

**hermes 清单(机械四步, 顺序不可换)**:

```bash
# 1. 抓取+挂载(零 token, cwd=investment-tool 项目根)
node scripts/wechat/fetch_wechat.mjs --url <url> --write
#    exit 0=ok / 2=文章被GG(回执用户"已删, 下次早点贴") / 5=反爬(过5分钟重试1次) / 6=未知公众号(回执用户登记)
# 2. 读 downloads/wechat/<account>/<date>/text.md, 按下面「蒸馏口径」产出【推演要点】
# 3. 写进 downloads/wechat/<account>/<date>/spec.md(纯文本, 每行一条)
# 4. 重挂载: node scripts/wechat/fetch_wechat.mjs --remount --account <account> --date <date> --write
```

**回执用户**(一句话): `✅ <标题> | <五维度一句话定调> | 已挂载 <date>.md`; 失败=原因+不硬凑。

### 蒸馏口径(hermes 读)

固定五维度, 每行一条 `【推演要点】<维度>: <内容>`, 只压缩原文, **禁止添加原文没有的判断**;
**锚点立法(10/2, 56天核销沉淀)**: 每条必须含可证伪锚点(点位/时间窗口/方向词/事件), 纯态度句(耐心/佛系/加油/拭目以待)不提取:

- **指数**: 方向+关键条件(止跌信号/量能)
- **情绪**: 周期位置(冰点/转暖/高潮)+标志事件
- **阵营**: 多空构成+上限/下限由谁决定
- **节点**: 时间性提示(出金日/交割日/节前节后)
- **风险**: 反向警示; 原文没有就整条不写(五维度允许缺, 不硬凑——同【推测】立法)

## 入口②: T+1 核销(Claude, 晚间 check md 链)

0. **待核销发现(内容即状态, 无队列文件)**: 遍历 `downloads/wechat/*/*/meta.json`——
   有 meta.json 无 spec.md=hermes 半截(先补蒸馏再核销); T 日有推演且 T+1 已收盘且 md 小节无【核销】行=待核销
1. 读昨日 md `#### 红旗大街发哥` 小节的【推演要点】+ 昨日实际(同 md 收评/涨停分析节, 必要时 scan 数据)
2. 逐条打分: 命中 / 半命中 / 打脸 / 不可证(模糊无法判), 小节末尾补一行:
   `【核销 T+1】命中x 半命中x 打脸x 不可证x · <一行简评>`
3. 周期性沉淀 `persona/rules.md`(v1 已沉淀 10/2, 56天样本): 每 +20 个核销样本复审一次, 更新强弱项与加权口径
4. **时间纪律**: 核销=用后见验证前瞻, 天然无未来函数; 但简评只许引用 T+1 收盘前信息
5. 无文章日/无小节=跳过, 不硬凑

## 产物地图

| 层 | 位置 | 作者 |
|---|---|---|
| 证据层(原文) | `downloads/wechat/<account>/<yyyy-MM-dd>/{raw.html,text.md,meta.json}` | fetch_wechat.mjs(机械) |
| 蒸馏层 | 同目录 `spec.md` → md 小节【推演要点】 | hermes(LLM) |
| 核销层 | md 小节【核销 T+1】行 | Claude(LLM) |
| 沉淀层 | `skills/fage-skill/persona/rules.md` | Claude(周期性) |
| 账号清单 | `scripts/wechat/wechat_accounts.json` | 人工(加公众号=加一行) |

## 纪律

1. 硬数据(原文/meta)禁止手改, 要改就改脚本重跑; LLM 只写 spec.md 与【核销】行
2. 小节重挂载=整小节覆盖幂等, 保【核销】行; spec.md 是【推演要点】唯一真源(md 里手改会被覆盖)
3. 消费侧(taoge-skill chain 01 facts)引用推演要点时必须标注=**主观判断层**, 与 scan 硬榜分层, 权重归 02
4. alpha 未验证纪律: 攒 2-3 周核销样本前, 推演要点在 01 facts 只作参考不作依据

## 上下游
> **架构方向(10/6 用户立法)**: 本 skill 未来接**独立决策链**(workflows/chain.md, 与 taoge-skill 同构; 七步暂定); persona 攒厚后启动。成长触发器: rules.md>15KB 建索引+references/ 放溯源全文。
