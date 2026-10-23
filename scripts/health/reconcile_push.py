# -*- coding: utf-8 -*-
"""reconcile_push.py — 对账结果推微信(10/23 用户令: 原来是 Java 直接推一串日志, 微信上很乱 → 按 notify_fmt 统一排版)

读 investment_tool.reconcile_result(只读)的一个批次, 每个检查项翻成"人话": 名称 / 已自动修复 / 缺什么 + 影响 + 打算怎么办; OK 的只计数不展开
用法:
  python reconcile_push.py --batch 20261022235000_BILIBILI [--dry]
  python reconcile_push.py --latest MARKET|BILIBILI [--dry]
Java 侧(ReconcileResultServiceImpl.saveAndNotify)存完批次后调本脚本 --batch <批次号>; 本脚本失败时 Java 退回原来的纯文本推送
退出码: 0 已推(或全部正常不推) / 1 失败
"""
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "scripts" / "backfill_bilibili")]
import notify_fmt as NF   # noqa: E402

BIZ = {"MARKET": "行情库", "BILIBILI": "UP 视频管线"}
UP = {"taoge": "桃哥", "qushitiange": "趋势天哥", "lubenyuan": "卢本圆"}
ITEM = {   # 检查项 → (名称, 影响, 打算)
    "kline_day": ("日线", "当天相似日 / 强势股库 / 必查少这一天", "下一轮对账自动重采; 连续 2 次失败看 daily_health 红项"),
    "kline_minute": ("分时线", "分钟路径 / 盘中相似走势少这一天", "下一轮对账自动重采"),
    "call_auction": ("开盘竞价过程", "竞价研究少这一天(竞价错过补不了)", "补不了, 09:25 撮合价用分时首根代替"),
    "adjustment_factor": ("除权因子", "复权价可能不准", "到期自动重校"),
    "results": ("半成品视频", "半成品视频没法蒸馏", "按 10/11 立法整夹删后重跑(B 站补跑等你说)"),
    "sum": ("没进 md 的视频", "这些视频的观点没进 md, 蒸馏 / skill 少样本", "B 站补跑按规矩等你说一声再跑(manual_backfill.py)"),
    "distill": ("进了 md 没蒸馏的视频", "已进 md 但 skill 没吸收", "今晚 check md 蒸馏会串行补"),
    "days": ("天数核对", "", ""),
    "orphan_distill": ("蒸馏账本对不上", "账本里有、产物里没有的日子, 一般是并到交易日 md 的周末稿", "不影响使用, 有空核对"),
    "db_sync": ("DB 同步", "", ""),
    "db_failed": ("重试 3 次卡住的视频", "这几条视频卡住不动", "看是不是付费 / 失效视频; 确认跳过就回复\"跳过 BV...\""),
    "db_skipped": ("已确认跳过", "", ""),
}


def rows_of(cur, batch):
    cur.execute("select biz_type, biz_key, check_item, expected, actual, result, detail, create_time from reconcile_result where batch_no=%s order by id", (batch,))
    return cur.fetchall()


def item(biz, key, ci, exp, act, res, det):
    name, impact, plan = ITEM.get(ci, (ci, "", ""))
    who = UP.get(key, key) if biz == "BILIBILI" else str(key)[5:] if re.fullmatch(r"\d{4}-\d\d-\d\d", str(key)) else key
    st = {"OK": "ok", "FIXED": "fixed", "WARN": "warn", "MISSING": "warn", "FAILED": "fail", "UNRECOVERABLE": "fail"}.get(res, "warn")
    if ci == "days" and res == "MISSING":   # 天数差是 sum / distill 缺的结果, 不重复报
        st = "ok"
    lines = []
    if st == "fixed":
        title = f"{who} {name} 已自动修复：{act}"
    elif st == "ok":
        title = f"{who} {name}"
    else:
        lst = re.findall(r"BV\w+@[\w-]+", str(det or ""))
        what = f"{len(lst)} 条：{'、'.join(x.split('@')[0][-6:] + '(' + x.split('@')[1][-5:] + ')' for x in lst[:4])}{' 等' if len(lst) > 4 else ''}" if lst else f"应 {exp} / 实 {act}"
        title = f"{who} {name}{'(失败)' if st == 'fail' and ci.startswith('kline') else ''}：{what}"
        if impact:
            lines.append(f"影响：{impact}")
        if plan:
            lines.append(f"打算：{plan}")
    return {"st": st, "title": title, "lines": lines}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch")
    ap.add_argument("--latest")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import manual_backfill as mb
    cur = mb.db().cursor()
    batch = a.batch
    if not batch and a.latest:
        cur.execute("select batch_no from reconcile_result where biz_type=%s order by id desc limit 1", (a.latest,))
        r = cur.fetchone()
        batch = r[0] if r else None
    if not batch:
        print("没有批次")
        return 1
    R = rows_of(cur, batch)
    if not R:
        print("批次没有行:", batch)
        return 1
    biz = R[0][0]
    items = [item(*r[:7]) for r in R]
    m = re.match(r"(\d{14})_", batch)
    when = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else R[0][7]
    msg = NF.render(f"对账 · {BIZ.get(biz, biz)}", when, items, foot=f"批次 {batch}")
    print(msg)
    if all(x["st"] == "ok" for x in items):
        print("(全部正常, 不推)")
        return 0
    p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "hermes" / "wx_send.py"), msg, "--raw", "--src", f"reconcile_{biz}"] + (["--dry"] if a.dry else []),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(p.stdout.strip()[-200:])
    return 0 if p.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
