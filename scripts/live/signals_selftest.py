# -*- coding: utf-8 -*-
"""signals_selftest.py — signals.py 的 S1~S7 构造序列自测(零 token、不读行情、不连库、不推送)

每个信号至少一正一反: 该触发时触发(且只触发这一个信号的这一条), 不该触发时不触发。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/live/signals_selftest.py   (全过退出 0, 有失败退出 1)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as S   # noqa: E402

D = "2099-01-05"


class FakeMeta:
    def __init__(self, **kw):
        self.m = {"prev": 10.0, "up": 11.0, "dn": 9.0, "tick": 0.01, "sigma": 0.005, "sigma_src": "构造", "name": "测试票"}
        self.m.update(kw)

    def get(self, c):
        return dict(self.m)

    def name(self, c):
        return "测试票"


def hms(x):
    return f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d}"


def path(pts, vwap=None, step=3):
    """pts = [(t, 价, 累计量)], 两点间每 3 秒线性插值; 累计额 = 累计量 × vwap(给了 vwap 就固定均价线, 否则均价 = 价)"""
    rows = []
    for (t0, p0, v0), (t1, p1, v1) in zip(pts, pts[1:]):
        a, b = S.secs(t0), S.secs(t1)
        for x in range(a, b, step):
            f = (x - a) / (b - a)
            p, v = round(p0 + (p1 - p0) * f, 2), int(v0 + (v1 - v0) * f)
            rows.append(snap(hms(x), p, v, vwap))
    t, p, v = pts[-1]
    rows.append(snap(t, p, v, vwap))
    return rows


def snap(t, p, v, vwap=None, b1=None, k1=None):
    bp = b1 if b1 is not None else round(p - 0.01, 2)
    return {"s": "sz000001", "t": t, "p": p, "v": v, "a": v * (vwap if vwap else p), "b": [[bp, 100], [round(bp - 0.01, 2), 100]] + [[0, 0]] * 3,
            "k": [[k1 if k1 is not None else round(p + 0.01, 2), 100], [round(p + 0.02, 2), 100]] + [[0, 0]] * 3}


def auc(t, px, ub, us):
    return {"s": "sz000001", "t": t, "p": 0.0, "v": 0, "a": 0.0, "b": [[px, 1000], [0.0, ub]] + [[0, 0]] * 3, "k": [[px, 1000], [0.0, us]] + [[0, 0]] * 3}


def run(rows, **kw):
    det = S.Detector(D, FakeMeta(**kw))
    out = []
    for r in rows:
        out += det.feed(r)
    return out


FAIL = []


def check(name, evs, sig, want):
    got = [e for e in evs if e["sig"] == sig]
    ok = (len(got) >= 1) if want else (len(got) == 0)
    print(f"{'OK  ' if ok else 'FAIL'} {name}: 期望{'触发' if want else '不触发'} {sig}, 实得 {len(got)} 条" + (f" | {got[0]['t']} {got[0]['detail']}" if got else ""))
    if not ok:
        FAIL.append(name)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    S.P.update(S4_N=10, S7_X=6.0)   # 不读 yaml, 固定成 yaml 当前值, 自测不受用户改参数影响
    open25 = [snap("09:25:00", 10.0, 1000)]

    # S1: σ=0.5% → 阈 1%; 10.00 平 → 2 分钟跌到 9.85(-1.5%) → 30 秒拉到 9.95(收回 2/3, 均价 9.90 之上)
    base = [("09:31:00", 10.0, 10000), ("09:40:00", 10.0, 20000)]
    check("S1 正例", run(open25 + path(base + [("09:42:00", 9.85, 22000), ("09:42:30", 9.95, 23000)], vwap=9.9)), "S1", True)
    check("S1 反例: 90 秒后才拉回", run(open25 + path(base + [("09:42:00", 9.85, 22000), ("09:43:00", 9.86, 22500), ("09:43:30", 9.95, 23000)], vwap=9.9)), "S1", False)
    check("S1 反例: 拉回但在均价下", run(open25 + path(base + [("09:42:00", 9.85, 22000), ("09:42:30", 9.95, 23000)], vwap=10.0)), "S1", False)
    check("S1 反例: 跌 0.8% 不够 2σ", run(open25 + path(base + [("09:42:00", 9.92, 22000), ("09:42:30", 9.99, 23000)], vwap=9.9)), "S1", False)

    # S2: 均价 10.00; 10.10 待命 → 10.02 回到带内 → 3 分 30 秒在 9.98~10.02 → 10.05 回升
    s2 = [("09:40:00", 10.10, 10000), ("09:45:00", 10.02, 20000), ("09:48:30", 9.98, 25000), ("09:49:00", 10.05, 26000)]
    check("S2 正例", run(open25 + path(s2, vwap=10.0)), "S2", True)
    check("S2 反例: 带内跌破 -0.3%", run(open25 + path([("09:40:00", 10.10, 10000), ("09:45:00", 10.02, 20000), ("09:46:00", 9.95, 22000), ("09:48:30", 10.0, 25000), ("09:49:00", 10.05, 26000)], vwap=10.0)), "S2", False)
    check("S2 反例: 没先站上 +0.6%", run(open25 + path([("09:40:00", 10.04, 10000), ("09:45:00", 10.02, 20000), ("09:48:30", 9.98, 25000), ("09:49:00", 10.05, 26000)], vwap=10.0)), "S2", False)

    # S3: 开 10.00; 10 分钟冲到 10.50(+5%, 第一波放量) → 回落到 10.20(-2.9%) → 10:05 再到 10.45, 最后 5 分钟量 ≥ 70%
    w1 = [("09:30:00", 10.0, 1000), ("09:40:00", 10.5, 101000), ("09:50:00", 10.2, 121000)]
    check("S3 正例", run(open25 + path(w1 + [("10:00:00", 10.2, 131000), ("10:05:00", 10.45, 171000)])), "S3", True)
    check("S3 反例: 二次冲高缩量(5 分钟量 < 70%)", run(open25 + path(w1 + [("10:00:00", 10.2, 131000), ("10:05:00", 10.45, 141000)])), "S3", False)
    check("S3 反例: 第一波只涨 1%", run(open25 + path([("09:30:00", 10.0, 1000), ("09:40:00", 10.1, 101000), ("09:50:00", 9.85, 121000), ("10:00:00", 9.9, 131000), ("10:05:00", 10.08, 171000)])), "S3", False)

    # S4: 涨停 11.00; 封 → 开板 2 分钟 → 回封
    def board(open_min):
        rows = open25 + [snap(hms(S.secs("10:00:00") + i * 3), 11.0, 1000 + i, b1=11.0, k1=0) for i in range(20)]
        x0 = S.secs("10:01:00")
        rows += [snap(hms(x0 + i * 3), 10.9, 2000 + i, b1=10.89) for i in range(open_min * 20)]
        x1 = x0 + open_min * 60
        rows += [snap(hms(x1 + i * 3), 11.0, 5000 + i, b1=11.0, k1=0) for i in range(5)]
        return rows
    check("S4 正例: 开板 2 分钟回封", run(board(2)), "S4", True)
    check("S4 反例: 开板 12 分钟才回封", run(board(12)), "S4", False)
    check("S4 反例: 没封过", run(open25 + path([("10:00:00", 10.9, 1000), ("10:05:00", 10.95, 2000)])), "S4", False)

    # S5: 14:30 低点 10.00, 14:36 到 10.16(+1.6%)
    pre = [("14:20:00", 10.1, 1000), ("14:30:00", 10.0, 2000)]
    check("S5 正例", run(open25 + path(pre + [("14:36:00", 10.16, 3000)])), "S5", True)
    check("S5 反例: 只涨 1.4%", run(open25 + path(pre + [("14:36:00", 10.14, 3000)])), "S5", False)
    check("S5 反例: 低点后 12 分钟才到 +1.6%", run(open25 + path([("14:20:00", 10.1, 1000), ("14:44:00", 10.0, 2000), ("14:55:00", 10.15, 2500), ("14:56:30", 10.16, 3000)])), "S5", False)

    # S6: 09:20 撮合 10.00 → 09:22 10.31(+3.1%) 未匹配 买 500 > 卖 100
    check("S6 正例", run([auc("09:19:30", 9.9, 0, 0), auc("09:20:00", 10.0, 100, 200), auc("09:22:00", 10.31, 500, 100)]), "S6", True)
    check("S6 反例: 未匹配卖更多", run([auc("09:20:00", 10.0, 100, 200), auc("09:22:00", 10.31, 100, 500)]), "S6", False)
    check("S6 反例: 只抬 2.9%", run([auc("09:20:00", 10.0, 100, 200), auc("09:22:00", 10.29, 500, 100)]), "S6", False)
    check("S6 反例: 09:20 前的抬价不算", run([auc("09:16:00", 10.0, 100, 200), auc("09:19:00", 10.4, 500, 100)]), "S6", False)

    # S7: 开 10.00, 09:45 到 10.60(+6%)
    check("S7 正例", run(open25 + path([("09:30:00", 10.0, 2000), ("09:45:00", 10.6, 5000)])), "S7", True)
    check("S7 反例: 只到 10.59", run(open25 + path([("09:30:00", 10.0, 2000), ("09:45:00", 10.59, 5000)])), "S7", False)
    check("S7 反例: 10:01 才到", run(open25 + path([("09:30:00", 10.0, 2000), ("10:00:00", 10.5, 4000), ("10:01:00", 10.6, 5000)])), "S7", False)

    # 节流: 同票同信号 30 分钟只记一次
    th = S.Throttle()
    e = lambda t: {"code": "000001", "sig": "S1", "t": t}   # noqa: E731
    r = [th.ok(e("10:00:00")), th.ok(e("10:20:00")), th.ok(e("10:31:00"))]
    ok = r == [True, False, True]
    print(f"{'OK  ' if ok else 'FAIL'} 节流 30 分钟: {r}")
    if not ok:
        FAIL.append("节流")
    # 排版: 持仓在前
    msg = S.compose([{"t": "10:12:03", "code": "000002", "name": "乙", "sig": "S2", "sig_name": "回踩均价线不破", "px": 3.56},
                     {"t": "10:20:00", "code": "000001", "name": "甲", "sig": "S1", "sig_name": "急跌后拉起", "px": 7.09}], D, {"000001"})
    ok = msg.index("甲(000001) S1 急跌后拉起 10:20 价 7.09") < msg.index("乙(000002) S2 回踩均价线不破 10:12 价 3.56")
    print(f"{'OK  ' if ok else 'FAIL'} 推送排版持仓在前\n{msg}")
    if not ok:
        FAIL.append("排版")

    print(f"\n{'全部通过' if not FAIL else '失败: ' + ', '.join(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
