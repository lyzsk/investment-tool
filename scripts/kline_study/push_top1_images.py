# -*- coding: utf-8 -*-
"""持仓K线top1预测图推送：每只票日K+五日各一行，只保留概率最高路径。"""
import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "kline_study"), str(ROOT / "scripts" / "hermes")]
from morning_push import compose, latest_imgs  # noqa: E402


def run(codes, names, day, dry=False):
    out = []
    for code in codes:
        got = latest_imgs(code, dt.date.today().isoformat())
        got = {k: v[:1] for k, v in got.items()}   # 用户最新口径：每类只保留top1
        im = compose(code, names.get(code) or code, got, day)
        if not im:
            out.append({"code": code, "ok": False, "error": "缺日K/五日预测图"})
            continue
        if not dry:
            import wx_send
            wx_send.send(f"MEDIA:{im} {names.get(code) or code} 上=日K top1 · 下=五日 top1(原衔接画法)", src="kline_top1_image", raw=True, wait=120)
        out.append({"code": code, "ok": True, "image": str(im), "dry": dry})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--codes", default="002241,601988,600785")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    names = {"002241": "歌尔股份", "601988": "中国银行", "600785": "新华百货"}
    print(run(a.codes.split(","), names, a.date, a.dry))
