# -*- coding: utf-8 -*-
"""seat_style_llm.py — 席位"风格一句话"(唯一需要语言模型归纳的部分, 1 个 claude -p 批量; 2026-10-15 建)
输入: scripts/lhb/seat_profile.json(seat_profile.py 零 token 统计产物) 的前 50 活跃营业部 + 知名游资别名组 + 拉萨天团/机构/北向三组
输出: scripts/lhb/seat_style.json {id: 一句话}; render_seat_md.py 读它
纪律: 同一时刻只一个 claude -p(用户立法) → 启动前查有无别的 `claude.exe -p` 在跑, 有就等(最多 40 分钟); 08:00~09:20 不开
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/lhb/seat_style_llm.py
"""
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from claude_call import call, LEAN_ARGS  # noqa: E402

SRC = ROOT / "scripts" / "lhb" / "seat_profile.json"
OUT = ROOT / "scripts" / "lhb" / "seat_style.json"
FIELDS = ["buy_n", "appear_n", "sell_n", "avg_net_buy_wan", "limitup_rate", "gem_star_share", "bj_share", "multi_day_share", "both_side_share",
          "o1_mean", "c1_mean", "c1_median", "red1_rate", "c3_mean", "c1_excess_mean", "quick_sell_rate", "top_boards"]


def other_claude_p():
    ps = "Get-CimInstance Win32_Process -Filter \"name='claude.exe'\" | ForEach-Object { $_.CommandLine }"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [l for l in r.stdout.splitlines() if " -p" in l]


def main():
    now = dt.datetime.now()
    if dt.time(8, 0) <= now.time() <= dt.time(9, 20):
        print("08:00~09:20 不开新 claude 会话")
        return 2
    j = json.loads(SRC.read_text(encoding="utf-8"))
    items = []
    for s in [s for s in j["seats"] if s["kind"] == "营业部"][:50]:
        items.append({"id": s["key"], "席位": s["short"], "别名": s["alias"], **{k: s[k] for k in FIELDS}})
    for a, v in j["aliases"].items():
        items.append({"id": f"alias:{a}", "席位": f"{a}(合并席位: {'/'.join(v['seats'])})", **{k: v.get(k) for k in FIELDS if k in v}})
    for g, v in j["groups"].items():
        items.append({"id": f"group:{g}", "席位": f"{g}整体", **{k: v.get(k) for k in FIELDS if k in v}})
    base = {k: {f: v[f] for f in ("buy_n", "o1_mean", "c1_mean", "red1_rate", "c3_mean")} for k, v in j["baseline"].items()}
    prompt = f"""你是 A 股龙虎榜数据分析助手。下面是 {j['range'][0]}~{j['range'][1]} 龙虎榜席位的零 token 统计(已算好, 你只做归纳, 禁止重新计算或编造数字之外的事实, 禁止用任何工具)。
字段口径: buy_n=净买入上榜次数; appear_n=出现在买五/卖五总次数; sell_n=净卖出次数; avg_net_buy_wan=平均每次净买入(万元); limitup_rate=买入当天该股涨停的比例%;
gem_star_share=创业板+科创板占比%; bj_share=北交所占比%; multi_day_share=多日累计榜占比%; both_side_share=同时出现在买五和卖五的比例%(做T/对倒迹象);
o1_mean/c1_mean/c1_median=T+1 开盘/收盘溢价均值/中位(%, 以 T 收盘为基准); red1_rate=T+1 收红率%; c3_mean=T+3 收益均值%;
c1_excess_mean=扣掉同类(T 日涨停/非涨停)全市场上榜票基准后的 T+1 超额%(衡量"跟它买"有没有超额, 比 c1_mean 更公平); quick_sell_rate=买入后 T+1/T+2 又在同票榜上净卖出的比例%(下界);
top_boards=常做行业前三[行业, 次数]。
全市场基准: {json.dumps(base, ensure_ascii=False)}

任务: 给每个条目写"风格一句话"(中文, 20~45 字): 概括它的操作风格(打板/低吸/趋势/机构式大单/散户集中营/做T 等, 只能从数字推断, 用"疑似/偏"等词表达不确定)+跟随价值(以 c1_excess_mean 与样本量为准, 样本 <30 要说样本少)。
不要提及真实人名身份猜测以外的内容; 别名是用户给的标签, 可以沿用但不扩展。
最终回复只输出一个 ```json 代码块: {{"items": [{{"id": "...", "style": "..."}}, ...]}}, 覆盖全部 {len(items)} 个 id, 顺序不限。

条目:
{json.dumps(items, ensure_ascii=False)}
"""
    for i in range(40):
        o = other_claude_p()
        if not o:
            break
        print(f"有别的 claude -p 在跑({len(o)} 个), 等 1 分钟", flush=True)
        time.sleep(60)
    else:
        print("等了 40 分钟仍有 claude -p 在跑, 放弃")
        return 3
    schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["id", "style"]}}}}
    r = call(prompt, tag="lhb-seat-style", permission="default", timeout=1500, json_schema=schema,
             extra_args=LEAN_ARGS + ["--tools", "Read"])
    print(f"ok={r.ok} cost=${r.cost_usd:.3f} {r.duration_s:.0f}s errors={r.errors}")
    if not r.ok or not r.parsed:
        return 1
    m = {x["id"]: x["style"] for x in r.parsed["items"]}
    miss = [x["id"] for x in items if x["id"] not in m]
    OUT.write_text(json.dumps({"generated_at": now.strftime("%Y-%m-%d %H:%M:%S"), "session_id": r.session_id, "cost_usd": r.cost_usd,
                               "missing": miss, "style": m}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写 {OUT.relative_to(ROOT)}: {len(m)} 条, 缺 {len(miss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
