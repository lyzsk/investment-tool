# -*- coding: utf-8 -*-
"""paper_idle_check.py — 午间体检: 哪些在跑的 paper 账本"既没持仓也没挂单 / 今天一笔没动"(10/19 用户定, 零 token)

为什么: 10/19 做 T 9 本账本全天没建底仓、日志只写"无到点动作", 收盘后才被发现。午间(12:00~13:00)查一次, 有问题推微信。
查什么(每本在跑账本; 退出 paper 的导师、停用账本跳过):
  ① 空转: 没持仓 + 没未成交挂单 + 今天没成交(可能是链没出单 / 出单被拒 / 底仓没建)
  ② 做 T 账本: 底仓(_t_base)还没定 且 今天没有建底仓成交
  ③ 今天的挂单全部被拒 / 作废(废单率 100%)
产物: 打印 + --push 时走 scripts/hermes/wx_send.py 推一条; 结果写 scripts/dfcf/paper/quality_log/idle_<日>.json
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/dfcf/paper/paper_idle_check.py [--date D] [--push]
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
T_BOOKS = {"A-dbank", "A-tbank", "A-hbank", "A-dndq", "A-tndq", "A-hndq", "A-dmuyuan", "A-tmuyuan", "A-hmuyuan", "A-sbank", "A-sndq", "A-wbank", "A-wndq"}   # 10/20 +波段T 四本
TRADE_OPS = {"1", "2", "3", "4", "7", "8", "9"}   # day_positions op 码: 建/加/减/清/当日买卖(同 mimicry_score)
LOW_FREQ = 0.35   # 10/20 用户定"体检按出手频率过滤波段型": 导师真人近 60 个交易日出手日占比低于它 = 低频 / 波段型, 链空转属正常, 只列不推


def mentor_freq(src):
    """链账本 → 导师真人近 60 个交易日的出手日占比(tzzb day_positions 有 op 码的天 / 有记录的天);
    B站 UP / 无账本 → 用 fingerprint 持有交易日中位数 ≥5 视为低频(返回 0.0), 取不到 = None(按常规报)"""
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    try:
        import mentors as MT
        mid = next((e["id"] for e in MT.all() if e.get("book") == src), None)
    except Exception:   # noqa: BLE001
        mid = None
    if not mid:
        return None
    dp = ROOT / "downloads" / "tzzb" / mid / "day_positions.json"
    if dp.exists():
        try:
            d = json.loads(dp.read_text(encoding="utf-8"))
            days = sorted(d)[-60:]
            if len(days) >= 10:
                return sum(1 for k in days if any(str(x.get("op")) in TRADE_OPS for x in (d[k] or {}).get("list") or [])) / len(days)
        except (OSError, ValueError):
            pass
    try:
        import re
        t = (ROOT / "skills" / f"{mid}-skill" / "persona" / "fingerprint.md").read_text(encoding="utf-8")
        m = re.search(r"持有交易日(?:\(非日内\))?[:：]?\s*(\d+(?:\.\d+)?)", t)
        if m and float(m.group(1)) >= 5:
            return 0.0
    except OSError:
        pass
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    D = a.date
    try:
        excl = {"A-" + k for k in json.loads((ROOT / "scripts" / "tzzb" / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded", {})}
    except (OSError, ValueError):
        excl = set()
    idle, tbad, allbad, lowfq, ok = [], [], [], [], 0
    for f in sorted((HERE / "books").glob("*.json")):
        src = f.stem
        if src in excl or not src.startswith("A-"):
            continue
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        pos = {c: p for c, p in (b.get("positions") or {}).items() if int(p.get("qty") or 0) > 0}
        today_o = [o for o in b.get("orders") or [] if o.get("date") == D]
        open_o = [o for o in b.get("orders") or [] if o.get("status") == "open"]
        fills = [t for t in b.get("trades") or [] if str(t.get("id", "")).startswith(D)]
        bad = [o for o in today_o if o.get("status") in ("reject", "void", "invalid")]
        if src in T_BOOKS and not int(b.get("_t_base") or 0) and not fills:
            tbad.append(src)
        elif not pos and not open_o and not fills:
            fq = mentor_freq(src)
            tag = src + ("(今天出过单但全没成)" if today_o else "(今天没出单)")
            if fq is not None and fq < LOW_FREQ and not today_o:
                lowfq.append(f"{src}(真人出手日 {fq:.0%})")
            else:
                idle.append(tag)
        else:
            ok += 1
        if today_o and len(bad) == len(today_o):
            allbad.append(f"{src} {len(bad)} 单全被拒/作废: {(bad[0].get('note') or '')[-50:]}")
    lines = [f"paper 午间体检 {D} {dt.datetime.now():%H:%M}: 正常 {ok} 本"]
    if tbad:
        lines.append(f"❌ 做T 底仓没建({len(tbad)}): " + "、".join(tbad))
    if idle:
        lines.append(f"⚠️ 空转=没持仓没挂单没成交({len(idle)}): " + "、".join(idle))
    if allbad:
        lines.append(f"⚠️ 今天的单全被拒({len(allbad)}): " + "; ".join(allbad[:4]))
    if lowfq:
        lines.append(f"ℹ️ 低频 / 波段型导师今天没动(真人本来就少出手, 不算空转)({len(lowfq)}): " + "、".join(lowfq))
    if not (tbad or idle or allbad):
        lines.append("✅ 每本都有持仓 / 挂单 / 成交")
    msg = "\n".join(lines)
    print(msg)
    out = HERE / "quality_log"
    out.mkdir(exist_ok=True)
    (out / f"idle_{D}.json").write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "t_no_base": tbad, "idle": idle, "low_freq": lowfq, "all_rejected": allbad, "ok": ok},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    if a.push and (tbad or idle or allbad):
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), "--raw", "--src", "paper_idle", msg],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=400)


if __name__ == "__main__":
    main()
