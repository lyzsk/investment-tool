# 不吃土豆0 · distill 工作流(薄路由)

> 反向沉淀走 **tzzb-skill 通用流**(五人=LLM 提取型), 固定 `--ledger buchitudou0`; 产物进本 skill persona/。
> 全文契约: `skills/tzzb-skill/workflows/distill.md`。

```bash
scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/... # 经 tzzb-skill distill 流程, --ledger buchitudou0
```

## 规则时间状态(10/17 晚用户批)

每条规则头下第一行是 `- **时间状态**: 建立 YYYY-MM-DD · 最后验证 YYYY-MM-DD · 状态 活跃|待复核|已否定(...)`(列表式规则写成下一行缩进子项 `  - 时间状态: ...`)。新增规则→写这一行(建立=目标日, 最后验证=最近证据日); 本次核销兑现或打脸了某条→把它的「最后验证」改成目标日; 导师的新做法否定了旧规则→旧规则**不删不改正文**, 只把状态改成 `已否定(YYYY-MM-DD, 由 Rxx 取代)`, 新做法另起一条; 活跃/待复核两态由 scripts/md/rule_time_state.py 每晚按最近证据日机械刷新, 不用手改。
