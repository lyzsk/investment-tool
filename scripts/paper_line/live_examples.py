# -*- coding: utf-8 -*-
"""live_examples.py — 实盘线逐步示例页的数据(10/25 用户: 明天人工审实盘线的每个细节, 示例放进 live_line.html)

收集(零 token, 只读): 盘前选人 · 账本起点(只列股票名, 不写数量金额) · 02 新材料 + 一次真跑的 02 输出 · 回放(桩)里某条线的
  盘前首跑材料目录 / 必查示例 / 04、06 提问原文 / 盘前汇总推送 · 触发一览 · 电报: 位置选项 / 分类 v2 / 随机示例 / 点名后开板拆分
落地: results/_live/live_examples.js(results 已 gitignore; docs/graph/live_line.html 的「⑤ 示例」页用相对路径读它)
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/paper_line/live_examples.py [--replay results/_replay/2026-10-23] [--line live_zhiyingjuexin]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "paper_line"), str(ROOT / "scripts" / "paper_line" / "tools")]
OUT = ROOT / "results" / "_live" / "live_examples.js"


def rd(p, cap=None):
    try:
        t = Path(p).read_text(encoding="utf-8")
    except OSError:
        return f"(没有文件: {Path(p).relative_to(ROOT) if Path(p).is_absolute() else p})"
    return t if cap is None or len(t) <= cap else t[:cap] + f"\n\n…(截断, 全文 {len(t)} 字: {Path(p).relative_to(ROOT)})"


def outline(t):
    """材料目录: 各级标题 + 这一节多少 KB"""
    parts = re.split(r"(?m)^(#{1,4} [^\n]+)$", t)
    L = ["| 节 | 大小 |", "|---|---|"]
    for i in range(1, len(parts) - 1, 2):
        lv = len(parts[i]) - len(parts[i].lstrip("#"))
        if lv <= 3:
            L.append(f"| {'　' * (lv - 1)}{parts[i].lstrip('#').strip()[:80]} | {len(parts[i + 1].encode()) / 1024:.1f} KB |")
    return "\n".join(L[:160])


def must_example(t, n=2):
    """盘前首跑材料里必查清单的前 n 只票(### 代码 名称 …)"""
    m = re.search(r"(?ms)^(### \d{6} .*?)(?=^### \d{6} |\Z)", t)
    blocks = re.findall(r"(?ms)^### \d{6} .*?(?=^### \d{6} |^## |\Z)", t)
    return "\n".join(blocks[:n]) if blocks else (m.group(1) if m else "(材料里没找到必查块)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", default=str(ROOT / "results" / "_replay" / "2026-10-23_stub" / "2026-10-23"))
    ap.add_argument("--line", default="live_zhiyingjuexin")
    ap.add_argument("--D", default="2026-10-26")
    a = ap.parse_args()
    S = []

    def sec(step, title, desc, items, q=None):
        S.append({"step": step, "title": title, "desc": desc, "items": [{"label": k, "md": v} for k, v in items], "q": q or []})

    import mentor_select as MS
    import pack
    s = MS.load(a.D) or MS.select(a.D)
    sec("盘前", f"盘前选人({a.D})", "净值截至 T−1; 近 20 日收益 ≥10% 且日均 ≥0.2% 入选; ≥5 个交易日没更新净值不进盘前; 2 位 UP(桃哥 / 卢本圆)固定进盘前, 趋势天哥只当市况参考; 盘前跑完按序号推给你挑",
        [("选人结果", "```\n" + MS.text(s) + "\n```")])
    try:
        rs = pack.real_start(a.D)
        names = pack_names(list((rs or {}).get("positions") or {}))
        sec("盘前", "每条线的账本起点", "= 你最近一份收盘持仓(去掉中国银行); 数量 / 金额只在内存和 snapshots 里, 示例页不写",
            [("持仓(只列名称)", "、".join(names) or "(没有)"), ("来自", str((rs or {}).get("from", "-")))])
    except Exception as e:   # noqa: BLE001
        sec("盘前", "每条线的账本起点", "", [("读取失败", repr(e))])
    ex = ROOT / "results" / "_live" / "_example02" / "2026-10-23" / "_market"
    j = {}
    try:
        j = json.loads((ex / "02_0900.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    sec("02", "02 共用市况 · 新材料 + 真跑一次的输出(10/23 09:00, $0.53)",
        "10/25 新增方向证据包: 导师 T−1 / T−2 / T−3 实际买卖 → 题材(按近 20 日收益加权) · UP 近 3 日定调 · 发哥近 3 日推演 + 近 20 日核销命中率 · 指数 K 线 · market-skill; 02 每个方向要写支持 / 反对的来源",
        [("02 输出(json)", "```json\n" + json.dumps(j.get("json"), ensure_ascii=False, indent=1) + "\n```"),
         ("02 输出(正文)", j.get("text") or "(没有)"),
         ("02 材料目录", outline(rd(ROOT / "results" / "_live" / "02_example_1023_0900.md"))),
         ("02 材料全文", rd(ROOT / "results" / "_live" / "02_example_1023_0900.md"))],
        q=["这次 02 判'中性 · 冰点', 当天实际创业板 +4.16% V 形反转; 翻转条件里 国证2000 ≥ +1.5% 应该会在盘中命中 → 02 刷新(不叫醒线, 附在下一次叫醒消息里)"])
    rp = Path(a.replay)
    lines = sorted(d for d in rp.glob("live_*") if d.is_dir())
    ln = next((d for d in lines if d.name == a.line), lines[0] if lines else None)
    if ln:
        vs = sorted((ln / "versions").glob("*"))
        boot = next((v for v in vs if (v / "00_boot_msg.md").exists()), None)
        bt = rd(boot / "00_boot_msg.md") if boot else ""
        sec("盘前首跑", f"盘前首跑材料({ln.name}, 回放桩 {rp.name})", "第 1 条消息 = 共享开头(全部线逐字相同, 缓存共用) + 本线材料(skill / 导师近况 / 账本起点 / 必查); 下面是目录和大小, 全文在回放目录",
              [("目录", outline(bt)), ("必查示例(前 2 只)", must_example(bt)), ("01 事实包", rd(boot / "01_facts.md", 20000) if boot else "-")])
        for v in vs[:4]:
            items = [(f.stem, rd(f, 30000)) for f in sorted(v.glob("00_trigger_msg.md"))] + [(f.stem, rd(f, 30000)) for f in sorted(v.glob("*_ask.md"))]
            items += [(f"{f.stem}(桩回答)", rd(f, 6000)) for f in sorted(v.glob("0[2-6].json"))]
            if items:
                sec("chain", f"{v.name} 这一轮每步的提问原文", "回放是桩(模型回答是假的), 但提问原文 = 周一真跑时模型看到的; 叫醒原因见 strategies/<版>.json 的 why", items)
        dg = rp / "premarket_digest.txt"
        if not dg.exists():
            dg = next(iter(rp.rglob("premarket_digest.txt")), None)
        if dg:
            dtxt = rd(dg)
        else:   # 回放不推盘前汇总 → 用各线第一版(盘前版)策略现拼一条, 和总控 09:12 推的是同一个函数(live.digest_text)
            try:
                import types
                import live as LV
                D0 = rp.name[:10]
                L0 = pack.lines(D0)
                books = {}
                for d in lines:
                    lid = d.name
                    sp = sorted((d / "strategies").glob("*.json"))
                    st0 = (json.loads(sp[0].read_text(encoding="utf-8")).get("strategy") if sp else None) or {}
                    if lid in L0:
                        books[lid] = types.SimpleNamespace(strategy=st0, line=L0[lid])
                dtxt = LV.digest_text(D0, books, pack.live_sel(D0))
            except Exception as e:   # noqa: BLE001
                dtxt = f"(拼不出来: {e!r})"
        sec("推送", "盘前汇总(推给你的那条微信)", "桩回放里每条线的看法是假的, 看格式和序号; 你回「留下 1、3」/「暂停 2」/「恢复 2、4」", [("汇总原文", "```\n" + dtxt + "\n```")])
        sm = []
        for d in lines:
            sp = sorted((d / "strategies").glob("*.json"))
            ws = [str(json.loads(f.read_text(encoding="utf-8")).get("why"))[:60] for f in sp]
            sm.append(f"- **{d.name}**: {len(sp)} 版 · " + " | ".join(f"{f.stem}: {w}" for f, w in list(zip(sp, ws))[:6]) + (" …" if len(sp) > 6 else ""))
        sec("触发", f"回放桩里每条线被叫醒了几次、为什么({rp.name})",
            "注意: 桩的 06 每次都挂一张现价附近的买单 → 一成交就'本链成交'再叫醒 → 版本数虚高(芷影 80 版里 68 次是这个); 真跑 10/23 paper v3 芷影是 18 版。taoge / lubenyuan 只有 1 版 = 09:19 后没留下、休眠",
            [("各线叫醒", "\n".join(sm))])
    else:
        sec("盘前首跑", "盘前首跑材料", "", [("还没有回放", f"{rp} 下没有 live_* 目录(先跑 replay.py --fake)")])
    sec("触发", "什么会叫醒一条线(周一一条不改)", "",
        [("盯盘模式", pack.MODE["watch"]),
         ("02 刷新条件(不叫醒线, 只附在下一次叫醒消息里)", rd(ROOT / "scripts" / "paper_line" / "market02.py").split('"""')[1].split("材料(")[0])])
    sec("对比", "live line vs paper v3 · 叫醒 + chain 逐项对比", "两者同一个执行器; live = 拟人线 · 盯盘模式 + 几处 live 专属分支", [("对比表", rd(ROOT / "docs" / "live" / "live_vs_paperv3.md"))])
    sec("样例库", "样例库 · 07 规则体检 · 规则来源检查 · 用户发现核销(10/25 新建, 每晚 check md 重算)", "",
        [("样例库(各导师 / 板型 / 箱体 / 连板 / 市况 / 怎么出的)", rd(ROOT / "docs" / "research" / "sample_lib.md")),
         ("规则体检(可疑规则待你核销)", rd(ROOT / "docs" / "review" / "rule_suspects.md")),
         ("rules.md 来源检查", rd(ROOT / "docs" / "review" / "rules_lint.md")),
         ("U1~U3 核销", rd(ROOT / "docs" / "research" / "user_found_check.md"))])
    sec("电报", "电报点名放在 chain 哪里 · 选项", "每个位置可单独开关; 我的建议在文末", [("选项", rd(ROOT / "docs" / "research" / "telegraph_placement.md"))])
    sec("电报", "电报点名分类 v2 · 近 100 个交易日", "", [("统计", rd(ROOT / "docs" / "research" / "telegraph_kind.md")),
                                                     ("随机示例(人工核对分类)", rd(ROOT / "docs" / "research" / "telegraph_kind_samples.md"))])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.EXAMPLES=" + json.dumps(S, ensure_ascii=False) + ";\n", encoding="utf-8")
    print("→", OUT, f"{OUT.stat().st_size / 1024:.0f} KB", len(S), "节")


def pack_names(codes):
    sys.path.insert(0, str(ROOT / "scripts" / "chain"))
    import chain_steps
    try:
        nm = chain_steps.names("2099-12-31")
    except Exception:   # noqa: BLE001
        nm = {}
    return [f"{nm.get(c, '')}({c})" if nm.get(c) else c for c in codes]


if __name__ == "__main__":
    main()
