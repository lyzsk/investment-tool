# 含笑96998 · sum 工作流(薄路由)

> 本 ledger 的合成走 **tzzb-skill 通用流**(硬数据层 gen_tzzb_md 零 token), 固定参数 `--ledger hanxiao`。
> 全文契约: `skills/tzzb-skill/workflows/sum.md`(10/7 结构立法: 不复制全文防双副本漂移)。
> 10/18 入库时 32B【推测】层已退役, 只回填硬数据层, 不生成推测。

```bash

# 硬数据层(机械)

node scripts/tzzb/gen_tzzb_md.mjs --ledger hanxiao --all --write
```
