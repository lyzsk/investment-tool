# 投资账本 (tzzb) API 参考 · 不吃土豆 0

> 2026-09-27 实测探通；2026-10-02 前端 bundle 逆向补全端点字典+ 破译 buy_sell 枚举。
> tzzb = **投资账本**(同花顺实盘分享社区), 非 "转债" 缩写。

## 凭证

- 入口页: `https://tzzb.10jqka.com.cn/tzzbWeb/community/matchHomePageWeb.html?key=6Mk3xjj&user_key=189268&user_name=不吃土豆0...`
- **页面是 4KB JS 空壳**, 真实数据在 capital.hexin.cn
- 分享链接的 `key` + `user_key` = 匿名凭证, **有效期未知** → fetch 脚本检测连续 401/-100 必须显式告警, 不许静默写空

## 端点格式

```
https://capital.hexin.cn/caishen_httpserver/direct/caishen_fund/community_share/v1/<端点>?key=6Mk3xjj&user_key=189268[&page=N]
```

注意形态: `/caishen_httpserver/direct` 后拼 **完整 API 路径**(直连路径 404、`direct?path=` 404, 9/27 两轮踩坑)。

## 端点字典 (10/2 从前端 bundle xcs-tzzb-front-app-community 逆向全量)

| 端点                     | 参数         | 内容                                                                          | 状态                       |
| ------------------------ | ------------ | ----------------------------------------------------------------------------- | -------------------------- |
| position_change_by_share | page(每页 50) | 调仓流水 (**总览口径: 每日每票 1 条**), buy_sell= 操作类型                      | ✅ 已入 fetch_tzzb.mjs     |
| position_by_share        | —            | 当前持仓 (盘后恒空仓= 国标准券)                                                 | ✅ 已入                    |
| profit_rate_by_share     | —            | 胜率 / 回撤 / 总收益 / 排名 + index_list 每日净值 (逐日收益无现成字段, 链算)         | ✅ 已入                    |
| month_by_share           | —            | 月度只有月份列表无数值 → nav_month 已弃                                       | ✅(无数值)                 |
| change_bs_by_share       | **stock_code(必传!)** + page(每页38) | **逐笔买卖腿**: 秒级trans_date/真实qty/amount, op=1买入腿 2=卖出腿 | ✅ 已入 fetch_tzzb.mjs(10/2 解锁) |
| daily_history_by_share   | stock_code+trans_date | 个股每日操作历史(buy_avgprice/sell_avgprice)                        | ❌ 废弃(change_bs 是超集)      |
| clear_by_share           | page?        | 清仓股票 tab                                                                  | ❌ 废弃(可由 bs_leg 推导)      |
| article_ex_by_share      | —            | 比赛信息 (桃粉杯第二届, 805 人, 2026 全年)                                     | ✅ 通, 暂未入              |

- 端点发现法: 分享页 JS 空壳 → 拉 `s.thsi.cn/cd/xcs-tzzb-front-app-community/*.bundle.js` → grep `_by_share`
- **-100 "服务器繁忙" 的真相(10/2 消融实验破案)**: 多数情况=**缺必传参数**, 不是反爬也不是限流!
  change_bs 不传 stock_code → 稳定 -100; 传了之后无 token 连打 6 发全通
- **hexin-v 与此 API 无关**: 假token/短token/不带token 三组全通(消融证伪)。页面 F12 弹回主页是前端反调试, 只挡浏览器不挡 API
- 教训: 参数名要用浏览器 Network 里的原文(`stock_code` 不是 `code`)

## buy_sell 枚举 (10/2 从 bundle module 53941 破译, 权威)

```
0=不变 1=加仓 2=减仓 3=建仓 4=清仓 5=小幅加仓 6=小幅减仓 7=大幅加仓 8=大幅减仓 9=做T
```

- **是操作类型, 不是买卖方向!** 不吃土豆 0 全部 178 条=9(做 T), 与日内画像自洽
- UI 图例: "做T: 当天既有买入又有卖出操作"; 加减仓幅度按单笔金额占总资产比例 (大幅=15%~100%)
- 买卖方向在 change_bs_by_share 的逐笔腿里 (买入 / 卖出字面量)

## op 字段 (10/2 由 change_bs 逐笔腿破译)

- **change_bs 口径: 1=买入腿 2=卖出腿**(与 buy_sell 对照: 买腿 buy_sell=3建仓, 卖腿 buy_sell=4清仓)
- position_change 日汇总口径 177×"2" + 1×"1", 做T日汇总全标 2, 语义待更多样本确认

## 操作记录页 (分时+ 买卖点, 10/2 用户给)

```
https://tzzb.10jqka.com.cn/tzzbWeb/common/hqChartsWeb.html?key=<key>&command=tzzb_kl_<key>
  &user_key=<uk>&code=<标的代码>&name=<名称>&query_type=2&upload_time=<毫秒>&defaultTab=record&defaultTimeop=day
```

- JS bundle=thsxcs-tzzb-front-app-common-h5, 行情走同花顺 hq infra(fuyao/common_hq_aggr: single_trend/single_kline/tick_history)
- **分时行情属行情管线, 不进 tzzb_record**(tzzb_record 只装账本数据)

## 故障模式

- -100 "服务器繁忙" → **先查必传参数是否带全**(10/2 教训: change_bs 缺 stock_code 稳定 -100), 再按限流处理
- 真限流(参数正确仍 -100) → 请求抖动 ×0.75~1.25 + 脚本内闭环重试 (健壮性铁律)
- 连续失败 ≠ 限流时 → 怀疑 key 失效 (exit 2) → 告警用户 (需重新从分享链接取 key)
