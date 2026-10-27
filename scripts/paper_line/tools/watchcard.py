# -*- coding: utf-8 -*-
"""watchcard.py — 实盘线"盯盘卡"(10/26 用户: 6 个 skill 卖完空仓后看不到它们的盯盘触发条件和挂单; 零 token, 不动总控)

原因: executor.wx 在"挂单没变 / 没有挂单"时不推新版(10/23 省额度), 空仓线只剩叫醒线 → 一条都不推。
做法: 读各线最新一版 06.json(view / 挂单 rules / 叫醒 wake / next / valid_until)+ state.json(持仓), 6 条线合成一条短卡;
      各线"挂单 + 叫醒线"签名变了才重推(同 key 顶掉没发出的旧卡), 两次至少隔 MIN_GAP 秒; 进合并推送总线
用法: python watchcard.py --once [--dry]     立刻出一张(dry 只打印)
      python watchcard.py --run [D]           盘中循环到 15:00
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "results" / "_live"
sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
MIN_GAP = 300
NAMES = {"zhiyingjuexin": "芷影攫心", "liuyiqing": "刘忆青", "buchitudou0": "不吃土豆0", "zuoshoudeirong": "做手德融", "taoge": "桃哥", "lubenyuan": "卢本圆"}


def _rule(r):
    side = {"BUY": "买", "SELL": "卖"}.get(r.get("side"), r.get("side"))
    q = r.get("qty") or (f"{r['ratio']:.0%}" if r.get("ratio") else "")
    if r.get("type") == "cond":
        how = f"条件单 {r.get('ref', '')}{'回落' if r.get('dir') == 'down' else '反弹'}{r.get('pct')}%"
    elif r.get("style"):
        how = f"{r['style']}"
    else:
        how = f"{r.get('op', '')}{r.get('px')}" + (" 竞价" if r.get("auction") else "")
    return f"{side} {how} {q}".strip()


def _wake(w):
    if not isinstance(w, dict):
        return str(w)[:40]
    t = w.get("type")
    if t == "index":
        return f"{w.get('code', '')[-6:]}{w.get('op', '')}{w.get('pct')}%"
    if t == "time":
        return f"{w.get('at')}复核"
    if t in ("price", "px"):
        return f"{w.get('code', '')}{w.get('op', '')}{w.get('px')}"
    return (w.get("why") or json.dumps(w, ensure_ascii=False))[:30]


def card(D):
    L, sig = [f"🗂 实盘线盯盘卡 {dt.datetime.now():%H:%M}(各线最新一版; 空仓也列叫醒条件)"], []
    for d in sorted(LIVE.glob(f"{D}/live_*")):
        sk = d.name[5:]
        vs = sorted((d / "versions").glob("*/06.json"))
        if not vs:
            continue
        try:
            j = json.loads(vs[-1].read_text(encoding="utf-8"))
            st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pos = st.get("positions") or {}
        ver = vs[-1].parent.name.split("_")[-1]
        hold = "、".join(f"{c}×{p.get('qty')}" for c, p in pos.items() if p.get("qty")) or "空仓"
        rules = [f"{x.get('name') or x['code']} {_rule(r)}" for x in j.get("codes") or [] for r in x.get("rules") or []]
        wakes = j.get("wake") or []
        if isinstance(wakes, str):
            try:
                wakes = json.loads(wakes.replace("'", '"'))
            except ValueError:
                wakes = [wakes]
        stopped = '"kind": "定时停' in (d / "events.jsonl").read_text(encoding="utf-8", errors="replace") if (d / "events.jsonl").exists() else False
        if stopped:   # 10/26 用户问: 土豆 10:00 后已定时停(LIVE_STOP_AFTER), 卡片只列一行
            L.append(f"【{NAMES.get(sk, sk)}】已定时停(不再叫醒) · {hold}")
            continue
        L.append(f"【{NAMES.get(sk, sk)}】{ver[:2]}:{ver[2:4]} 版 · {hold}")
        L.append("  挂单: " + ("; ".join(rules[:4]) + (f" 等{len(rules)}条" if len(rules) > 4 else "") if rules else "无"))
        nxt = (j.get("next") or "").strip()
        if nxt:
            L.append("  计划: " + nxt[:80] + ("…" if len(nxt) > 80 else ""))
        if wakes:
            L.append("  叫醒: " + " | ".join(_wake(w) for w in wakes[:4]) + (f"(有效到 {j['valid_until']})" if j.get("valid_until") else ""))
        sig.append((sk, tuple(rules), tuple(_wake(w) for w in wakes), tuple(sorted(pos))))
    return "\n".join(L), sig


def push(text, D, dry=False):
    if dry:
        print(text)
        return
    import push_bus as PB
    PB.enqueue(text, src="live_watchcard", urgent=False, key="live_watchcard", D=D)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--run", nargs="?", const="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    D = (a.run or "") or dt.date.today().isoformat()
    if a.once:
        push(card(D)[0], D, a.dry)
        return
    last_sig, last_t = None, 0.0
    while dt.datetime.now().strftime("%H:%M:%S") < "15:00:00":
        try:
            text, sig = card(D)
            if sig != last_sig and time.time() - last_t >= MIN_GAP:
                push(text, D, a.dry)
                last_sig, last_t = sig, time.time()
        except Exception as e:   # noqa: BLE001
            print(f"[watchcard] {e!r}", flush=True)
        time.sleep(20)


if __name__ == "__main__":
    main()
