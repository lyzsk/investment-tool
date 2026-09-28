# 投资账本(tzzb) API 参考 · 不吃土豆0

> 2026-09-27 实测探通。tzzb = **投资账本**(同花顺实盘分享社区), 非"转债"缩写。

## 凭证

- 入口页: `https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=6Mk3xjj&user_key=189268&user_name=不吃土豆0...`
- **页面是 4KB JS 空壳**, 真实数据在 capital.hexin.cn
- 分享链接的 `key` + `user_key` = 匿名凭证, **有效期未知** → fetch 脚本检测连续 401/-100 必须显式告警, 不许静默写空

## 端点格式

```
https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/<端点>?key=6Mk3xjj&user_key=189268[&page=N]
```

注意形态: `/caishen_httpserver/direct` 后拼**完整 API 路径**(直连路径 404、`direct?path=` 404, 9/27 两轮踩坑)。

## 端点字典

| 端点 | 参数 | 内容 | 实测(9/27) |
|---|---|---|---|
| position_change_by_share | page(每页50) | 调仓流水 | 174 条 |
| position_by_share | — | 当前持仓 | 空仓 |
| profit_rate_by_share | — | 胜率67.24%/回撤-5.12%/总收益273.98%/排名5/每日净值 | ✅ |
| month_by_share | — | 月度收益 | 2026-01~09 |

## 未破译字段(入库存原值, 标 [?] 不猜)

- `buy_sell=9`: 买卖枚举里出现 9, 含义未知(可能=转出/其他?)
- `op=2`: 操作类型枚举未解
- 量/金额字段是否存在未逐字段核实 → 若无, profile.md §4 仓位指纹瘸腿

## 故障模式

- `change_bs` 偶发返回 -100 "服务器繁忙" = 限流敏感 → 请求抖动 ×0.75~1.25 + 脚本内闭环重试(健壮性铁律)
- 连续失败 ≠ 限流时 → 怀疑 key 失效 → 告警用户(需重新从分享链接取 key)
