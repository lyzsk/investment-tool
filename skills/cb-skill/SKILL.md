---
name: cb-skill
description: "Use when 分析转债高手'不吃土豆0'的操作数据(投资账本 tzzb API): 行为统计画像/决策规则反推/当日调仓解读, 写 stocks md ### 转债 小节"
---

# cb-skill · 转债高手"不吃土豆0"行为画像与决策规则

> 骨架建立: 2026-09-27 (Claude Code 晚间重会话, 用户拍板设计)。
> ⚠️ 状态: **骨架预填, 数据管道未建**——fetch_tzzb.mjs / cb_tudou 表 / Java handler 均未写(见 docs/TODO.md 4b 节, 用户有空再落地)。persona/ 下内容除"已核实事实"外全是待填框架。

## 定位

学习对象 = 同花顺投资账本(tzzb)用户 **不吃土豆0**(转债日内, 排名 5)。
与 taoge-skill 的本质差异: **桃哥有口述语料=语言+行为双克隆; 不吃土豆只有 174 条沉默成交记录=纯行为克隆**。
分水岭方法论: 桃哥="他说了什么→提炼"; 不吃土豆="他做了什么→带闸门反推"(见 rules.md 五闸门)。

**语言指纹层诚实留空**: 无本人文本语料, 拟人链路里他只做表态/评分, 不模仿发言。
若未来拿到本人文本(社区帖子/电报群导出), 再补 language.md。

## 数据源(2026-09-27 实测探通)

页面 `tzzb.10jqka.com.cn/tzzbWeb/...matchHomePageWeb.html?key=...&user_key=...` 是 4KB JS 空壳,
真实 API:

```
https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/<端点>?key=6Mk3xjj&user_key=189268
```

**分享链接的 key+user_key 即匿名凭证**(有效期未知 → fetch 脚本必须带失效显式告警, 不许静默写空)。

| 端点 | 内容 | 实测 |
|---|---|---|
| position_change_by_share | 调仓流水, page 参数每页 50 | 174 条 |
| position_by_share | 当前持仓 | 空仓(9/27) |
| profit_rate_by_share | 胜率67.24% / 回撤-5.12% / 总收益273.98% / 排名5 / 每日净值 | ✅ |
| month_by_share | 月度收益 | 2026-01~09 |

未破译: `buy_sell=9` / `op=2` 枚举含义(入库存原值+payload_json 兜底, 推不出标 [?] 不猜);
change_bs 偶发 -100(限流敏感, 脚本内闭环重试+抖动)。

## 分层存储(9/27 用户定)

1. **原始凭证层**: API 返回一字不改落 `scripts/plan-b/downloads/tzzb/`(可重放/可重建)
2. **查询层**: 单表 `cb_tudou`(判别式: record_type=trade/nav_day/nav_month/position_snap + payload_json), 幂等 upsert, AI 写库走 controller
3. **不建语言层表**: 无文本语料

## 产出

- `### 账本` 小节(挂在 stocks md `## 复盘` 下; 9/27 用户定隐蔽名, 备选明示名 `### 同花顺账本-不吃土豆0`): 他有调仓的当天写操作+画像对照, 空仓期一句话净值
- `persona/profile.md`: 行为统计画像(操作指纹, 纯统计零马后炮)
- `persona/rules.md`: 决策规则反推(五闸门, 每条带置信度+证伪条件+验证状态)

## 目录

```
skills/cb-skill/
├── SKILL.md            # 本文件
├── persona/
│   ├── profile.md      # 操作指纹(统计事实层)
│   └── rules.md        # 反推规则(推断层, 五闸门)
└── references/
    └── api.md          # 端点/凭证/枚举字典/故障模式
```

## 纪律

1. 画像只写**可计数的统计事实**和**带闸门的推断**, 分界显式(事实/强推断/弱猜测三级)
2. 反例优先: 他打自己脸的操作优先记录
3. 每条结论带证据(成交记录时间+当时行情), 禁止"正确的废话"
4. 更新带日期+出处, profile/rules 头部各维护修订记录
5. 绝不编造他的"想法/说法"——推断动机时永远并列 ≥2 个竞争性假设
