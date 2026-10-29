# -*- coding: utf-8 -*-
"""route_image.py — 用户发来的图片先分流(10/25 用户: 微信 / CLI 发的图不一定都是 K 线图; 零 token, RapidOCR 2 线程, 一张约 3 秒)

判类(只看图本身, 不看用户说了什么; 用户文字另说的以用户为准):
  K线图   东方财富行情页截图: 认得出图类型(分时 / 五日 / 日K / 周K / 月K 的 tab 蓝色下划线)且顶部有 6 位代码
          → 复制到 downloads/kline/<yyyy.mm.dd>/(K 线收件箱, 夜间 / 盘中 kline_inbox 处理; 二次确认用 confirm_ctx.py)
  成交截图 OCR 里有 "成交 / 委托 / 持仓 / 可用 / 盈亏 / 资产" 这类词 ≥ 2 个 → 复制到 scripts/dfcf/snapshots/images/<日>/(隐私区, 不进 git)
  其他    → downloads/wx_images/<yyyy.mm.dd>/ + 同名 .txt 存 OCR 文字(给对话里看, 不进任何管线)
用法: python route_image.py <图片...> [--date yyyy.mm.dd] [--dry]   → 每张一行: 类别 → 目标路径(代码 / 名称 / 图类型)
"""
import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
TRADE_WORDS = ("成交", "委托", "持仓", "可用", "盈亏", "资产", "撤单", "可卖", "成本价", "市值")


def classify(path):
    import ocr_shot as OS
    o = OS.parse(path)
    texts = " ".join(t for _, _, t in o.get("texts") or [])
    if o.get("类型") not in (None, "未知") and o.get("code"):
        return "K线图", o
    if sum(1 for w in TRADE_WORDS if w in texts) >= 2:
        return "成交截图", o
    return "其他", o


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--date", default=dt.date.today().strftime("%Y.%m.%d"))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--keep", action="store_true", help="不删系统 Downloads 里的原图")
    a = ap.parse_args()
    dl = Path("C:/Users/admin/Downloads").resolve()
    dest = {"K线图": ROOT / "downloads" / "kline" / a.date, "成交截图": ROOT / "scripts" / "dfcf" / "snapshots" / "images" / a.date.replace(".", "-"),
            "其他": ROOT / "downloads" / "wx_images" / a.date}
    for f in a.files:
        p = Path(f)
        kind, o = classify(p)
        d = dest[kind]
        out = d / p.name
        if not a.dry:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            if kind == "其他":
                out.with_suffix(".txt").write_text("\n".join(t for _, _, t in o.get("texts") or []), encoding="utf-8")
            if not a.keep and p.resolve().parent == dl:   # 10/28 晚用户令: 从系统 Downloads 搬进来的图, sha1 一致就删原图
                import hashlib
                if hashlib.sha1(p.read_bytes()).hexdigest() == hashlib.sha1(out.read_bytes()).hexdigest():
                    p.unlink()
        print(f"{kind} → {out.relative_to(ROOT)}  ({o.get('code') or '-'} {o.get('name') or ''} {o.get('类型')})")


if __name__ == "__main__":
    main()
