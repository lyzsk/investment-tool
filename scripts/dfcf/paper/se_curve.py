# -*- coding: utf-8 -*-
"""se_curve.py — 策略执行器"影子账 vs 真实链账本"日内曲线(10/21 用户今晚要看, 决定留哪条)
读 results/_live/<D>/se_*/curve.csv(se_exec 每分钟追加: 时刻,影子nav,真实nav,影子%,真实%), 每条链一个子图画到一张图。
matplotlib 可用 → se_curve.png; 否则 → se_curve.html(自带数据)。各链收盘时都调一次, 最后一个收盘的画出来的就是全量; 未收盘的链标"(未收盘)"。
用法: python se_curve.py [--date D]
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(D, live=None):
    out = {}
    for d in sorted(Path(live or ROOT / "results" / "_live" / D).glob("se_*")):
        f = d / "curve.csv"
        if not f.exists():
            continue
        rows = []
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    rows.append((r["t"], float(r["shadow_pct"]), float(r["real_pct"])))
                except (KeyError, ValueError):
                    pass
        if rows:
            out[d.name[3:]] = {"rows": rows, "done": (d / "summary.md").exists()}
    return out


def draw(D, live=None):
    """live=曲线所在目录(默认 results/_live/<D>; 自测用临时目录)"""
    data = load(D, live)
    base = Path(live or ROOT / "results" / "_live" / D) / "se_curve"
    if not data:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axs = plt.subplots(len(data), 1, figsize=(11, 3.2 * len(data)), squeeze=False)
        for ax, (sk, v) in zip(axs[:, 0], data.items()):
            ts = [dt.datetime.strptime(f"{D} {r[0][:5]}", "%Y-%m-%d %H:%M") for r in v["rows"]]
            # 午休压掉: 横轴用序号, 刻度标时刻
            x = list(range(len(ts)))
            ax.plot(x, [r[1] for r in v["rows"]], color="#2f6fdf", lw=1.6, label="新 paper: 策略执行器的模拟账(今天真实下单)")
            ax.plot(x, [r[2] for r in v["rows"]], color="#e0682b", lw=1.6, ls="--", label="对照: 起点持仓不动(只按盘中价重估)")
            ax.axhline(0, color="#999", lw=0.6)
            step = max(1, len(x) // 10)
            ax.set_xticks(x[::step])
            ax.set_xticklabels([t.strftime("%H:%M") for t in ts[::step]], fontsize=8)
            last = v["rows"][-1]
            ax.set_title(f"{sk}{'' if v['done'] else '(未收盘)'}  执行器 {last[1]:+.2f}% vs 不操作 {last[2]:+.2f}%  (起点=昨收持仓+现金)", fontsize=10)
            ax.set_ylabel("收益 %")
            ax.legend(loc="upper left", fontsize=8, frameon=False)
            ax.grid(alpha=0.25)
        fig.tight_layout()
        out = base.with_suffix(".png")
        fig.savefig(out, dpi=110)
        plt.close(fig)
        return out
    except Exception:   # noqa: BLE001
        out = base.with_suffix(".html")
        out.write_text("""<!doctype html><meta charset="utf-8"><title>se_curve %s</title><body style="font-family:sans-serif"><div id="c"></div><script>
const D=%s;for(const [sk,v] of Object.entries(D)){const W=900,H=220,P=30,r=v.rows,ys=r.flatMap(x=>[x[1],x[2]]),lo=Math.min(0,...ys),hi=Math.max(0,...ys)||1;
const X=i=>P+i*(W-2*P)/Math.max(1,r.length-1),Y=y=>H-P-(y-lo)*(H-2*P)/((hi-lo)||1),pl=k=>r.map((x,i)=>X(i)+','+Y(x[k])).join(' ');
document.getElementById('c').insertAdjacentHTML('beforeend',`<h4>${sk}${v.done?'':'(未收盘)'} 影子 ${r.at(-1)[1].toFixed(2)}%% vs 真实 ${r.at(-1)[2].toFixed(2)}%%</h4><svg width=${W} height=${H}><line x1=${P} x2=${W-P} y1=${Y(0)} y2=${Y(0)} stroke=#999 /><polyline fill=none stroke=#2f6fdf points="${pl(1)}"/><polyline fill=none stroke=#e0682b points="${pl(2)}"/><text x=${P} y=12 font-size=11>蓝=影子账 橙=真实链账本 ${r[0][0]}~${r.at(-1)[0]}</text></svg>`)}
</script>""" % (D, json.dumps(data, ensure_ascii=False)), encoding="utf-8")
        return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    print(draw(ap.parse_args().date))


if __name__ == "__main__":
    main()
