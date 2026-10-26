# -*- coding: utf-8 -*-
"""plan_review_selftest.py — plan_review.py 的自测(零 token、不连库、不读真实行情; 全部用临时目录 + 注入的假行情)
断言"该发生的事发生了": 挂单合并 / 成交归属 / 草稿没挂 + 不撤的话 / 前置单没成交 / 价格没到差多少 / 撤后穿价 / 链慢了 / 情景判定 / 决策日志挂接 / 隐私目录
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/live/plan_review_selftest.py
"""
import json
import sqlite3
import sys
import tempfile
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_review as P   # noqa: E402

D = "2026-01-05"
C = "600000"


def w(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def fake_line(base):
    ld = base / D / "paper_fake"
    vers = [   # (版本号, 链开始, 耗时秒, 文件名分钟, 规则, 其他字段)
        (1, "09:04:00", 60, "0905", [{"id": "r1", "side": "BUY", "op": "<=", "px": 10.0, "qty": 100, "auction": True, "rest": True}], {"auc_draft": "09:05:00"}),
        (2, "09:20:30", 40, "0921", [{"id": "r1", "side": "BUY", "op": "<=", "px": 9.5, "qty": 100, "rest": True},
                                     {"id": "r2", "side": "SELL", "op": ">=", "px": 11.0, "qty": 100, "after": "r1", "rest": True}], {"auc_submitted": "09:21:10"}),
        (3, "09:58:00", 120, "1000", [{"id": "r1", "side": "BUY", "op": "<=", "px": 9.5, "qty": 100, "rest": True},
                                      {"id": "r2", "side": "SELL", "op": ">=", "px": 10.8, "qty": 100, "rest": True}], {}),
        (4, "10:29:00", 60, "1030", [], {}),
    ]
    for n, st, tot, hm, rules, extra in vers:
        s = {"view": "自测", "codes": [{"code": C, "name": "浦发银行", "band": [9, 11], "rules": rules}], "valid_until": "15:00", **extra}
        if n == 1:
            s["codes"][0]["scenarios"] = [{"when": "竞价涨幅 >= 1 且 未匹配买 > 未匹配卖", "action": "开盘买"},
                                          {"when": "开盘涨幅 < 0", "action": "不动"},
                                          {"when": "现价 > 均线", "action": "等信号买"}]
        w(ld / "strategies" / f"{n:02d}_{hm}.json", {"why": "自测", "tag": None, "strategy": s, "dropped": ["600000 r9 超过持仓"] if n == 3 else [], "fired": []})
        w(ld / "versions" / f"{n:02d}_{st.replace(':', '')}" / "timing.json", {"start": st, "total": tot, "result": "ok"})
        w(ld / "versions" / f"{n:02d}_{st.replace(':', '')}" / "06.json", s)
    w(ld / "state.json", {"cash": 1, "positions": {C: {"qty": 100, "cost": 9.55, "sellable": 0}},
                          "trades": [{"t": "10:05:00", "code": C, "name": "浦发银行", "side": "BUY", "px": 9.5, "qty": 100, "fee": 5.0, "rule": f"3:{C}:r1"}],
                          "start": {"cash": 100000, "positions": {}}})
    (ld / "events.jsonl").write_text("", encoding="utf-8")
    (ld / "summary.md").write_text("【自测 v3 执行器 收盘】模拟账 100065(开盘 100000, +0.07%) vs 起点持仓不动 100000(+0.00%)\n", encoding="utf-8")
    return ld


def fake_market():
    M = P.Market(D, load=False)
    M.day[C] = {"date": D, "open": 9.9, "high": 10.9, "low": 9.45, "close": 10.2, "pre_close": 10.0, "up": 11.0, "dn": 9.0}
    M.day["sh000001"] = {"date": D, "open": 3000, "close": 2985, "pre_close": 3000}
    M.names = {C: "浦发银行"}
    M.auc[C] = {"price": 9.9, "vol": 1000, "unm": -500}
    tp = [("09:25:00", 9.9), ("09:30:00", 9.9), ("09:45:00", 10.7), ("09:58:30", 9.4), ("09:59:00", 9.6), ("10:05:00", 9.45), ("10:20:00", 10.0),
          ("10:29:59", 10.0), ("11:00:00", 10.9), ("14:56:00", 10.2), ("15:00:00", 10.2)]
    M.tape[C] = [(t, p, p, p - 0.01, p + 0.01) for t, p in tp]
    return M


def main():
    tmp = Path(tempfile.mkdtemp(prefix="plan_review_selftest_"))
    ld = fake_line(tmp)
    M = fake_market()
    R = P.review_line(ld, {"id": "fake", "name": "自测线", "mode": "watch", "kind": "mimic", "skill": "mentorX"}, M,
                      {"mentorX": [{"t": "10:01:00", "code": C, "name": "浦发银行", "side": "BUY", "px": 9.48, "qty": 500.0}]})
    O = R["orders"]
    by = {(o["side"], o["px"]): o for o in O}
    # ① 合并: v2 / v3 同价 9.5 买单 = 一张, 成交归 v3
    o = by[("BUY", 9.5)]
    assert o["cat"] == "成交" and o["versions"] == [2, 3] and o["fill_t"] == "10:05:00", o
    assert o["day_pnl_pct"] == round((10.2 / 9.5 - 1) * 100, 2), o["day_pnl_pct"]
    assert o["after_high_pct"] == round((10.9 / 9.5 - 1) * 100, 2) and o["next_day"] is None
    assert o["mentor_same"] and o["mentor_same"]["n"] == 1, o["mentor_same"]
    # ② 草稿没挂 + 不撤的话(开盘价 9.9 ≤ 买价 10 → 竞价就会成交)
    o = by[("BUY", 10.0)]
    assert o["cat"] == "草稿没挂" and "竞价就会成交" in o["if_kept"], o
    # ③ 前置单没成交(v2 的 r1 没在 v2 里成交)
    o = by[("SELL", 11.0)]
    assert o["cat"] == "前置单没成交", o
    # ④ 价格没到: 10.8 卖单生效 10:00:00~10:30:00 最高 10.0 → 差 −7.41%; 10:30 撤后 11:00 穿价; 链开跑 09:58 ~ 落地 10:00 期间没到 10.8 → 不报链慢
    o = by[("SELL", 10.8)]
    assert o["cat"] == "价格没到" and o["nearest"] == 10.0 and o["gap_pct"] == round((10.0 / 10.8 - 1) * 100, 2), o
    assert o.get("after_replace_hit") == "11:00:00" and "pre_land_hit" not in o, o
    # ⑤ 汇总 + 分布 + 剔除 + 导师
    assert R["n_orders"] == 4 and R["n_filled"] == 1 and R["n_rule_instances"] == 5, (R["n_orders"], R["n_filled"], R["n_rule_instances"])
    assert R["fill_dist"]["n"] == 1 and R["dropped"] and R["mentor"]["overlap_fill"] == [f"{C}:BUY"], R["mentor"]
    assert R["check"]["state_trades"] == R["check"]["state_trades_matched"] == 1
    # ⑥ 情景: 竞价 −1% → 第 1 条没落上, 第 2 条落上, 第 3 条判不了
    sc = {s["action"]: s["verdict"] for s in R["scenarios"]}
    assert sc == {"开盘买": "没落上", "不动": "落上", "等信号买": "未能机械判定"}, sc
    V = P.scen_vars(C, M)
    assert P.eval_when("收盘涨幅 >= 5 或 收盘价 > 10", V)[0] is True
    assert P.eval_when("未封板", V)[0] is True and P.eval_when("封板", V)[0] is False
    assert P.eval_when("上证收盘涨幅 > −1%", V)[0] is True
    assert P.eval_when("现价 > 1 或 开盘涨幅 < 0", V)[0] is True   # 一组判不了、另一组为真 → 真
    assert P.eval_when("现价 > 1 且 开盘涨幅 > 0", V)[0] is False   # 且里有一条假 → 假
    # ⑦ 链慢了: 把 v3 的开跑时刻挪到 09:58:00, 09:58:30 价 9.4 已到买价 9.5 —— 但那张单成交了, 不报; 造一张没成交的买单验证
    o2 = {"code": C, "name": "", "side": "BUY", "px": 9.42, "type": None,
          "insts": [{"v": 3, "land": "10:00:00", "end": "10:10:00", "code": C, "name": "", "id": "rX", "side": "BUY", "op": "<=", "px": 9.42, "qty": 100, "type": None,
                     "floor": None, "auction": False, "carried": False, "rest": True, "after": None, "pre_fill": None, "why": "", "key": "3:x:rX", "fill": None,
                     "nomoney": False, "submitted": False, "tag": None, "chain_start": "09:58:00"}]}
    j = P.judge(o2, M)
    assert j["cat"] == "价格没到" and j.get("pre_land_hit") == "09:58:30", j
    # ⑧ 1 分钟线兜底(3 秒名单外的票)
    M.bars["000002"] = [("09:30:00", "09:30:00", 5.0, 5.0, 5.0), ("09:30:00", "09:31:00", 4.9, 5.1, 5.0)]
    assert len(M.points("000002", "09:30:00", "09:31:00")) == 2 and P.bar_cross(M, "000002", "09:30:00", "09:32:00", "BUY", 4.95) == ("09:31:00", 4.9)
    # ⑨ 决策日志: 照 → 10:00 推送, 偏 → 10:30 推送(10:35 那条没发成功不算), 照片 不算; 只写进临时隐私目录
    hh = tmp / "hermes"
    (hh / "logs").mkdir(parents=True)
    c = sqlite3.connect(hh / "state.db")
    c.execute("create table sessions (id text primary key, source text)")
    c.execute("create table messages (id integer primary key autoincrement, session_id text, role text, content text, timestamp real)")
    c.execute("insert into sessions values ('s1', 'weixin')")
    ts = lambda hm: dt.datetime.fromisoformat(f"{D}T{hm}").timestamp()   # noqa: E731
    for hm, txt in (("10:06:00", "照"), ("10:40:00", "偏 太高了不追"), ("10:41:00", "照片发我"), ("10:42:00", "你好"), ("10:06:01", "照")):
        c.execute("insert into messages (session_id, role, content, timestamp) values ('s1', 'user', ?, ?)", (txt, ts(hm)))
    c.commit()
    c.close()
    wx = tmp / "wx_sent.jsonl"
    wx.write_text("\n".join(json.dumps(x) for x in (
        {"ts": f"{D}T10:00:00", "src": "paper_fake", "chars": 100, "ok": True},
        {"ts": f"{D}T10:30:00", "src": "paper_fake", "chars": 120, "ok": True},
        {"ts": f"{D}T10:35:00", "src": "paper_fake", "chars": 120, "ok": False},
        {"ts": f"{D}T10:36:00", "src": "other", "chars": 120, "ok": True})) + "\n", encoding="utf-8")
    (ld / "wx_send.log").write_text("[09:59:58] ✅ 自测 成交 09:59\n[10:29:59] 自测 v3 新版\n", encoding="utf-8")
    P.HERMES_HOME, P.WX_SENT, P.DLOG_DIR, P.QA_DIR = hh, wx, tmp / "decision_log", tmp / "qa"
    d = P.decision_log(D, tmp / D)
    rows = [json.loads(l) for l in (tmp / "decision_log" / f"{D}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert d["n"] == 2 and d["照"] == 1 and d["偏"] == 1, d   # 10:06:01 的重复"照"被去重
    assert rows[0]["push"]["ts"].endswith("10:00:00") and rows[0]["push"]["head"].startswith("✅ 自测") and rows[0]["gap_sec"] == 360, rows[0]
    assert rows[1]["push"]["ts"].endswith("10:30:00") and rows[1]["reason"] == "太高了不追", rows[1]
    assert all("reason" not in a for a in d["attached"]), "进 results 的摘要不许带理由原文"
    # ⑩ 没有回复 → 写明"当天没有决策回复"
    c = sqlite3.connect(hh / "state.db")
    c.execute("delete from messages")
    c.commit()
    c.close()
    d = P.decision_log(D, tmp / D)
    rows = [json.loads(l) for l in (tmp / "decision_log" / f"{D}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert d["n"] == 0 and rows[0]["note"] == "当天没有决策回复", rows
    # ⑪ md 渲染: 名称第一次带代码、负号用 −、不出现"模拟账"
    md = P.render_md({"date": D, "root": "tmp", "generated_at": "x", "total": {"n_orders": 4, "n_filled": 1, "fill_dist": R["fill_dist"]}, "lines": [R],
                      "errors": [], "decision_log": d}, M)
    assert "浦发银行(600000)" in md and md.count("(600000)") == 1 and "影子" not in md and "−7.41%" in md, md[:500]
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("plan_review 自测通过")


if __name__ == "__main__":
    main()
