# 星见野 · sum 工作流(薄路由)

> 本 ledger 的合成走 **tzzb-skill 通用流**(硬数据层 gen_tzzb_md 零 token + LLM 补【推测】层), 固定参数 `--ledger xingjianye`。
> 全文契约: `skills/tzzb-skill/workflows/sum.md`(10/7 结构立法: 不复制全文防双副本漂移)。

```bash

# 硬数据层(机械)

node scripts/tzzb/gen_tzzb_md.mjs --ledger xingjianye --all --write

# 推测层(批量, 32B pre-sum + 抽检)

scripts/venv/Scripts/python.exe scripts/tzzb/llm_batch_tzzb.py --ledger xingjianye
```
