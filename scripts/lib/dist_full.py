# -*- coding: utf-8 -*-
"""dist_full.py — 统计分布统一口径(10/23 用户定: 不能只报中位, 要均值 + 两端 + 极值 + n; 零依赖)

full(xs, key=lambda r: r["hi"], tag=lambda r: f"{r['code']} {r['d']}")
→ {"n", "均值", "中位", "P10", "P25", "P75", "P90", "最差", "最好", "最差例", "最好例"}(数值保留 2 位)
line(d, unit="%") → 一行文本: "n=173 均 +2.4 中位 +1.3 P10 −2.5 P90 +10.0 最差 −8.7(002xxx 2024-05-06) 最好 +10.1(…)"
"""


def _q(v, p):
    return v[min(len(v) - 1, int(len(v) * p))]


def full(xs, key=None, tag=None):
    rows = [x for x in xs if (key(x) if key else x) is not None]
    if not rows:
        return {"n": 0}
    pairs = sorted((((key(x) if key else x), i, x) for i, x in enumerate(rows)), key=lambda p: (p[0], p[1]))   # 值相同按原顺序, 不比较行本身
    pairs = [(p[0], p[2]) for p in pairs]
    v = [p[0] for p in pairs]
    out = {"n": len(v), "均值": round(sum(v) / len(v), 2), "中位": round(_q(v, .5), 2), "P10": round(_q(v, .1), 2), "P25": round(_q(v, .25), 2),
           "P75": round(_q(v, .75), 2), "P90": round(_q(v, .9), 2), "最差": round(v[0], 2), "最好": round(v[-1], 2)}
    if tag:
        out["最差例"], out["最好例"] = tag(pairs[0][1]), tag(pairs[-1][1])
    return out


def line(d, unit="%"):
    if not d or not d.get("n"):
        return "n=0"
    s = f"n={d['n']} 均 {d['均值']:+.2f}{unit} 中位 {d['中位']:+.2f}{unit} P10 {d['P10']:+.2f} P25 {d['P25']:+.2f} P75 {d['P75']:+.2f} P90 {d['P90']:+.2f}"
    s += f" 最差 {d['最差']:+.2f}" + (f"({d['最差例']})" if d.get("最差例") else "") + f" 最好 {d['最好']:+.2f}" + (f"({d['最好例']})" if d.get("最好例") else "")
    return s


def _selftest():
    d = full([{"v": i, "c": f"x{i}"} for i in range(1, 11)], key=lambda r: r["v"], tag=lambda r: r["c"])
    assert d["n"] == 10 and d["均值"] == 5.5 and d["最差"] == 1 and d["最好"] == 10 and d["最差例"] == "x1" and d["P90"] == 10, d
    assert full([])["n"] == 0 and line({"n": 0}) == "n=0"
    assert "最差 +1.00(x1)" in line(d)
    print("dist_full 自测通过")


if __name__ == "__main__":
    _selftest()
