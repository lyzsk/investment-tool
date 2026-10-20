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
T_BOOKS = {"A-dbank", "A-tbank", "A-hbank", "A-dndq", "A-tndq", "A-hndq", "A-dmuyuan", "A-tmuyuan", "A-hmuyuan"}


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
    idle, tbad, allbad, ok = [], [], [], 0
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
            idle.append(src + ("(今天出过单但全没成)" if today_o else "(今天没出单)"))
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
    if not (tbad or idle or allbad):
        lines.append("✅ 每本都有持仓 / 挂单 / 成交")
    msg = "\n".join(lines)
    print(msg)
    out = HERE / "quality_log"
    out.mkdir(exist_ok=True)
    (out / f"idle_{D}.json").write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "t_no_base": tbad, "idle": idle, "all_rejected": allbad, "ok": ok},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    if a.push and (tbad or idle or allbad):
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), "--raw", "--src", "paper_idle", msg],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=400)


if __name__ == "__main__":
    main()
