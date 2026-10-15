# -*- coding: utf-8 -*-
"""distill_cls_zaobao.py — 交易日早上自动挂财联社早报(10/14 建; 10/15 由 zaobao_morning.py 更名, 对齐「动词_cls_对象」命名)
分工: 抓取/挂载本体 = fetch_cls_zaobao.mjs(node, 零 token); 本脚本 = 早上的编排 + 蒸馏【早报要点】(一次 claude -p)
Java ClsZaobaoHandler 定时 07:00~09:15 每 15 分钟(同加红电报频率), 一轮做三件事, 已做完的跳过(幂等, 每 15 分钟重入安全):
  ① 发现+抓取+挂 md: node scripts/cls/fetch_cls_zaobao.mjs --discover --date <今天> --write(出口 6=今天的早报还没发 → 本轮结束等下一轮)
  ② 蒸馏【早报要点】: 早报原文直接拼进 prompt(不让模型自己读文件, 一轮出结果), 五栏 宏观/行业/公司/环球/机会 → downloads/cls_zaobao/<日>/spec.md
  ③ 重挂: fetch_cls_zaobao.mjs --remount --date <今天> --write(把要点挂进 md ### 财联社早报)
用户手贴链接的老路(--url)保留; 若用户已手贴且 spec.md 已有, 本脚本直接跳过。
非交易日(当天 md 不存在) / 09:15 之后 → 直接跳过。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/cls/distill_cls_zaobao.py [--date yyyy-MM-dd] [--force-time]
出口 0 = 本轮正常(含 未发布/已完成/跳过); 1 = 失败(抓取或蒸馏出错)。末行 JSON:{...}
"""
import argparse, datetime as dt, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
NOWIN = 0x08000000

PROMPT = """你是财联社早报的要点提炼员。下面是 {date} 的【早报】原文。
任务: 按五栏提炼要点, 每条一行, 格式严格为 `【早报要点】<栏>: <内容>`, 栏只能是 宏观/行业/公司/环球/机会 之一。
规则:
- 只压缩原文, 禁止添加原文没有的判断或推测; 数字/日期/公司名照抄原文
- 宏观 2~4 条、行业 2~4 条、公司 1~3 条(同类公告可合并一条, 如"三季报预增密集——A +x%、B +y%")、环球 1~3 条、机会 1~3 条; 原文某栏没有就不写
- 每条 ≤ 120 字, 能带锚点(日期/数值/方向)就带
最后只输出一个 ```json 代码块: {{"lines": ["【早报要点】宏观: ...", ...]}}

===== 早报原文 =====
{text}
"""


def run(cmd, timeout=180):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NOWIN)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--force-time", action="store_true", help="忽略 07:00~09:15 时间窗(补跑/测试用)")
    a = ap.parse_args()
    d = a.date
    out = {"date": d}
    y, m = d.split("-")[0], int(d.split("-")[1])
    md = ROOT / "md" / f"{y}S{(m + 2) // 3}" / f"{d}.md"
    if not md.exists():
        out["result"] = "非交易日(无当天 md), 跳过"
        return out, 0
    now = dt.datetime.now().strftime("%H:%M")
    if not a.force_time and not ("07:00" <= now <= "09:15"):
        out["result"] = f"时间窗外({now}), 跳过"
        return out, 0
    pdir = ROOT / "downloads" / "cls_zaobao" / d
    spec, text = pdir / "spec.md", pdir / "text.md"
    meta = pdir / "meta.json"
    # 10/15: 原文比 spec 新(手贴/重抓过) = spec 是旧原文蒸馏的, 作废重蒸; 原先只看 spec 存在就跳过, 10/15 07:29 重抓了正确原文仍沿用错 spec
    stale = spec.exists() and text.exists() and text.stat().st_mtime > spec.stat().st_mtime + 1
    if not stale and spec.exists() and spec.read_text(encoding="utf-8").count("【早报要点】") >= 3:
        out["result"] = "已完成(spec 已有), 跳过"
        return out, 0
    if stale:
        out["restale"] = "原文比 spec 新, 重蒸"
    # ① 发现+抓取+挂 md
    if not text.exists():
        rc, lines = run(["node", "scripts/cls/fetch_cls_zaobao.mjs", "--discover", "--date", d, "--write"])
        if rc == 6:
            out["result"] = "今天的早报还没发布, 等下一轮"
            return out, 0
        if rc != 0 or not text.exists():
            out["result"] = f"抓取失败 exit={rc}: {' | '.join(lines[-2:])[:200]}"
            return out, 1
    # 10/15 防线二: 原文发布日必须=目标日(防专题页还挂着昨天那期时被误收), 不对就删产物等下一轮
    try:
        cdate = (json.loads(meta.read_text(encoding="utf-8")).get("ctime") or "")[:10]
    except Exception:  # noqa: BLE001
        cdate = ""
    if cdate and cdate != d:
        for f in (text, meta, pdir / "raw.html", spec):
            f.unlink(missing_ok=True)
        out["result"] = f"原文发布日 {cdate} ≠ {d}(收到的是旧一期), 已删产物等下一轮"
        return out, 0
    # ② 蒸馏
    from claude_call import call
    r = call(PROMPT.format(date=d, text=text.read_text(encoding="utf-8")), tag="zaobao-spec", timeout=600,
             permission="skip", allowed_tools=["Read"],
             json_schema={"type": "object", "required": ["lines"],
                          "properties": {"lines": {"type": "array", "minItems": 5, "items": {"type": "string", "pattern": "^【早报要点】(宏观|行业|公司|环球|机会): .+"}}}})
    if not r.ok:
        out["result"] = f"蒸馏失败: {'; '.join(r.errors)[:200]}"
        return out, 1
    lines = r.parsed["lines"]
    spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # ③ 重挂
    rc, tail = run(["node", "scripts/cls/fetch_cls_zaobao.mjs", "--remount", "--date", d, "--write"])
    out.update(result="完成" if rc == 0 else f"重挂失败 exit={rc}", lines=len(lines),
               cols=sorted({l.split("】")[1].split(":")[0] for l in lines}))
    return out, 0 if rc == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    o, code = main()
    print(o.get("result"))
    print("JSON:" + json.dumps(o, ensure_ascii=False))
    sys.exit(code)
