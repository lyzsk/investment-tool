# -*- coding: utf-8 -*-
"""kline_inbox.py — K 线 / 分时截图收件箱(10/25 用户定; 零 token, 只读行情库)

目录(用户定):
  原图   downloads/kline/<yyyy.mm.dd>/      只放原图(用户贴图 / Java 上传接口落这里); 定时任务可以物理删除, 不影响下面任何东西
  产物   results/kline/<yyyy.mm.dd>/         日 K 标注图(箱体 + 导师 B / S / T)· 未来 3 日续画图(日 K 续画日 K, 分时 / 五日续画分时)· _status.json
  案例库 results/kline/cases.jsonl           (intake.py; 一个案例 = 同一只票同一截止日的几张图)
不进 DB: 量不大, 核销记录就是 _status.json 的字段(原来"逻辑删除"那一层 = 字段 原图已删)

一张图的三次核销(_status.json 每张图一条):
  ①收件  OCR 认名称 / 代码 / 图类型 / 价格轴 → intake 建案例(事实 / 统计 / 龙虎榜 / 发哥 / 电报 / 3 秒盘口)→ 续画未来 3 日
  ②导师  导师逐笔(同花顺投资账本)常在 23:10 之后才拉到 / 蒸馏完才全 → 每次跑都比较"案例的 导师核销至"和"账本最新逐笔日", 有新数据就重拉导师腿 + 3 秒盘口 + 重画标注
  ③对答案 截止日后满 3 个交易日 → 真实路径落在哪个情景(intake.resolve)→ 追加 market-skill kline_cases.md
谁调:
  check md 每轮(收盘后)--all;tzzb 蒸馏(tzzb_distill)跑完那一轮必然覆盖 ②
  Java  POST /api/kline/upload(存原图)· POST /api/kline/process?date=yyyy.mm.dd(非交易日 / 想马上看)
  OCR: RapidOCR(onnxruntime, 只用 CPU 不用 GPU), 限 2 线程: 一张 2.3~3 秒、约 2.4 核、113MB; 盘中照跑
用法:
  python kline_inbox.py --all [--day yyyy.mm.dd]          收件 + 续画 + 导师核销 + 对答案(不写 --day = 全部有新图 / 没核销完的日子)
  python kline_inbox.py --scan --day 2026.10.24 [--force]  只收件
  python kline_inbox.py --status [--day ...]               看核销进度
  python kline_inbox.py --code 002354 --day ... <文件名>   OCR 认不出代码时人工指定
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent)]
import intake as I   # noqa: E402

INBOX = ROOT / "downloads" / "kline"
OUT = ROOT / "results" / "kline"
EXT = {".jpg", ".jpeg", ".png", ".webp"}


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def st_path(day):
    return OUT / day / "_status.json"


def load_st(day):
    f = st_path(day)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"day": day, "images": {}}


def save_st(day, st):
    f = st_path(day)
    f.parent.mkdir(parents=True, exist_ok=True)
    st["更新"] = now()
    f.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def days(day=None):
    if day:
        return [day]
    ds = {p.name for p in INBOX.iterdir() if p.is_dir()} if INBOX.exists() else set()
    ds |= {p.name for p in OUT.iterdir() if p.is_dir() and (p / "_status.json").exists()} if OUT.exists() else set()
    return sorted(ds)


def trading_now():
    t = dt.datetime.now()
    return t.weekday() < 5 and "09:15" <= t.strftime("%H:%M") < "15:00"


def last_trade_day(day):
    """收件日(yyyy.mm.dd)当天或之前最近一个有日线的交易日(分时 / 五日图的截止日)"""
    D = day.replace(".", "-")
    c = I.cur()
    c.execute("select max(trade_date) from investment_market.kline_day where symbol='sh000001' and trade_date<=%s and is_deleted=0", (D,))
    return str(c.fetchone()[0])


def scan(day, force=False, manual=None):
    """①收件: 新图 OCR → 按代码分组 → intake 建案例 / 并入案例; manual = {文件名: 代码}"""
    st = load_st(day)
    src = INBOX / day
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXT) if src.exists() else []
    for name, g in st["images"].items():   # 原图被定时任务删了: 只记一笔, 案例不受影响
        if not (src / name).exists() and not g.get("原图已删"):
            g["原图已删"] = now()
    todo = [p for p in files if (st["images"].get(p.name) or {}).get("收件") is None or (manual and p.name in manual)]
    if not todo:
        save_st(day, st)
        return st
    # 10/25 实测: OCR 限 2 线程后一张 2.3~3 秒、CPU 约 2.4 核、内存 113MB(原来默认吃满 24 核) → 盘中也跑, 不再等收盘
    import ocr_shot as OS
    groups = {}
    for p in todo:
        g = st["images"].setdefault(p.name, {})
        g["sha1"] = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
        dup = next((k for k, v in st["images"].items() if k != p.name and v.get("sha1") == g["sha1"]), None)
        if dup:   # 同一张图贴了两次(10/24 img_2d7019121fe8 = img_909da350c71d)
            g.update({"收件": now(), "重复": dup, "case": st["images"][dup].get("case")})
            continue
        try:
            o = OS.parse(p)
            g["ocr"] = {k: o.get(k) for k in ("name", "code", "类型", "axis", "日期轴", "光标", "最右日期", "最右日期贴边", "超级复盘", "复盘日")}
        except Exception as e:   # noqa: BLE001
            g["ocr"] = {"err": repr(e)[:200]}
        code = (manual or {}).get(p.name) or g["ocr"].get("code")
        if not (manual and p.name in manual) and g["ocr"].get("类型") in (None, "未知"):   # 10/25 用户: 发来的图不一定是 K 线图 —— 认不出图类型(分时 / 五日 / 日K / 周K / 月K)的不建案例
            g.update({"收件": now(), "非K线图": True, "待": f"不像东方财富行情截图(认不出图类型); 是 K 线图就手动: --day {day} --code <代码> {p.name}"})
            continue
        if not code:
            g["待"] = f"认不出代码: python scripts/kline_study/kline_inbox.py --day {day} --code <代码> {p.name}"
            continue
        ty = g["ocr"].get("类型") or "未知"
        if ty.startswith("日K"):   # 日 K: 横轴最右日期标签贴着右边 = 最右一根就是它; 否则(往左滑过的历史窗口)让 intake 按 K 线颜色 + 价格自己认
            end = g["ocr"].get("最右日期") if g["ocr"].get("最右日期贴边") else None
            if not end and g["ocr"].get("超级复盘"):   # 横轴被"超级复盘"盖住: 截图一般是最新的(用户 10/24 两张都是), 最右一根按收件日最近交易日
                end = last_trade_day(day)
        else:
            end = last_trade_day(day)
        groups.setdefault((code, end), []).append(p)
    for (code, end), ps in groups.items():
        try:
            case = I.intake([str(p) for p in ps], code, end, out_day=day)
            for p in ps:
                g = st["images"][p.name]
                g.update({"收件": now(), "case": case["key"], "导师核销至": case.get("导师核销至")})
                g.pop("待", None)
                hit = next((x for x in case["图"] if x["file"] == p.name), {})
                g["类型"] = hit.get("类型")
                if hit.get("标注图"):
                    g["标注图"] = hit["标注图"]
        except Exception as e:   # noqa: BLE001
            for p in ps:
                st["images"][p.name]["err"] = repr(e)[:300]
    save_st(day, st)
    return st


def predict(day):
    """续画未来 3 日: 日 K → 3 根日 K; 分时 / 五日 → 3 天分时(价格轴来自 OCR); 一个情景一张图"""
    import draw_future as DF
    import scen_next as SN
    st = load_st(day)
    cases = {x["key"]: x for x in I.load_cases()}
    by_case = {}
    for name, g in st["images"].items():
        if g.get("case") and not g.get("预测") and not g.get("重复") and (INBOX / day / name).exists():
            by_case.setdefault(g["case"], []).append(name)
    for key, names in by_case.items():
        x = cases.get(key)
        if not x:
            continue
        code, end = x["code"], x["截止日"]
        try:
            S_ = SN.scen3(code, I.next_day(end)) if not code.startswith(("11", "12")) else None
        except Exception as e:   # noqa: BLE001
            S_ = None
            for n in names:
                st["images"][n]["预测"] = {"err": repr(e)[:200]}
        if not S_ or not S_.get("情景"):
            for n in names:
                st["images"][n].setdefault("预测", {"跳过": "转债 / 样本不足, 没有 3 日情景"})
            continue
        dd = DF.next_days(end)
        od = OUT / day
        od.mkdir(parents=True, exist_ok=True)
        C = None
        for n in names:   # 先日 K(顺便拿到收盘价 / 高低), 再分时
            g = st["images"][n]
            if not (g.get("类型") or "").startswith("日K"):
                continue
            outs = []
            for i, sc in enumerate(S_["情景"]):
                op = od / f"{code}_{Path(n).stem}_{'ABC'[i]}{sc['名']}.png"
                try:
                    C = DF.daily(INBOX / day / n, code, sc, "ABC"[i], S_, op, end=end, days=dd)
                    outs.append(str(op.relative_to(ROOT)))
                except Exception as e:   # noqa: BLE001
                    outs.append(f"失败 {e!r}"[:120])
            g["预测"] = {"图": outs, "时间": now()}
        for n in names:
            g = st["images"][n]
            ax = (g.get("ocr") or {}).get("axis")
            if (g.get("类型") or "") not in ("分时", "五日") or not ax or not ax.get("base"):
                continue
            F = x["事实"]
            CC = C or {"close": F["收"], "high": F["高"], "low": F["低"], "name": x["name"]}
            if abs(ax["base"] - (F["昨收"] if g["类型"] == "分时" else ax["base"])) / ax["base"] > 0.02:
                g["预测"] = {"跳过": f"价格轴 0% = {ax['base']} 和库里昨收 {F['昨收']} 对不上(可能是光标 / 叠加正股)"}
                continue
            gg = {"top": ax["top_y"], "zero": ax["zero_y"], "bot": ax["bot_y"], "pmax": ax["top_pct"], "base": ax["base"],
                  "day_w": 249 if g["类型"] == "五日" else 300}
            outs = []
            for i, sc in enumerate(S_["情景"]):
                op = od / f"{code}_{Path(n).stem}_{'ABC'[i]}{sc['名']}.png"
                try:
                    DF.intraday(INBOX / day / n, code, sc, "ABC"[i], S_, op, CC, g=gg, days=dd)
                    outs.append(str(op.relative_to(ROOT)))
                except Exception as e:   # noqa: BLE001
                    outs.append(f"失败 {e!r}"[:120])
            g["预测"] = {"图": outs, "时间": now()}
    save_st(day, st)


def mentor_latest():
    c = I.cur()
    c.execute("select max(date(record_time)) from investment_tool.tzzb_record where record_type='bs_leg' and is_deleted=0")
    return str(c.fetchone()[0])


def mentor_recheck():
    """②导师核销: 账本最新逐笔日 > 案例的 导师核销至 → 重拉导师腿 + 3 秒盘口 + 重画标注图"""
    latest = mentor_latest()
    L = I.load_cases()
    n = 0
    for x in L:
        if (x.get("导师核销至") or "") >= latest:
            continue
        x["导师买卖点"] = I.mentor_legs(x["code"], x["截止日"], n_after=3)   # 截止日之后 3 天的导师操作也拉(看他们事后怎么做)
        try:
            I.enrich(x)
        except Exception as e:   # noqa: BLE001
            x["盘口err"] = repr(e)[:200]
        for g in x["图"]:
            if (g.get("类型") or "").startswith("日K") and g.get("原图") and Path(ROOT / g["原图"]).exists():
                try:
                    od = Path(g.get("标注图") or "").parent if g.get("标注图") else OUT / I.day_dir()
                    op, _ = I.draw_marks(ROOT / g["原图"], x["code"], x["截止日"], x["导师买卖点"], ROOT / od / f"{x['code']}_{Path(g['file']).stem}_标注.png")
                    g["标注图"] = str(Path(op).relative_to(ROOT))
                except Exception as e:   # noqa: BLE001
                    g["标注图err"] = repr(e)[:100]
        x["导师核销至"] = latest
        x.setdefault("核销记录", []).append(f"{now()} 导师核销至 {latest}(导师腿 {len(x['导师买卖点'])} 笔)")
        n += 1
    I.save_cases(L)
    for day in days():   # 状态文件同步
        st = load_st(day)
        if not st["images"]:
            continue
        for g in st["images"].values():
            if g.get("case"):
                hit = next((y for y in L if y["key"] == g["case"]), None)
                if hit:
                    g["导师核销至"] = hit.get("导师核销至")
        save_st(day, st)
    return n, latest


def resolve():
    out = I.resolve()
    done = {x["key"]: x["对答案"]["落在"] for x in out}
    for day in days():
        st = load_st(day)
        ch = False
        for g in st["images"].values():
            if g.get("case") in done:
                g["对答案"] = f"{now()} 落在 {done[g['case']]}"
                ch = True
        if ch:
            save_st(day, st)
    return out


def status(day=None):
    L = []
    for d in days(day):
        st = load_st(d)
        for name, g in sorted(st["images"].items()):
            L.append(f"{d} {name} {g.get('case') or '-'} {(g.get('类型') or '')[:6]} 收件{'✓' if g.get('收件') else '✗'} 导师至{g.get('导师核销至') or '-'} "
                     f"预测{'✓' if (g.get('预测') or {}).get('图') else '-'} 对答案{'✓' if g.get('对答案') else '待'}{' 原图已删' if g.get('原图已删') else ''}{' 待:' + g['待'] if g.get('待') else ''}{' 重复' if g.get('重复') else ''}")
    return "\n".join(L)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--day")
    ap.add_argument("--code")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--mentor", action="store_true")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true", help="盘中也跑 OCR(盘中二次确认)")
    a = ap.parse_args()
    if a.code and a.files:
        d = a.day or I.day_dir()
        st = scan(d, force=True, manual={Path(f).name: a.code for f in a.files})
        predict(d)
        print(status(d))
        return
    if a.status:
        print(status(a.day))
        return
    for d in days(a.day):
        if a.scan or a.all:
            scan(d, a.force)
        if a.predict or a.all:
            predict(d)
    if a.mentor or a.all:
        n, latest = mentor_recheck()
        print(f"导师核销: {n} 个案例补到 {latest}")
    if a.resolve or a.all:
        r = resolve()
        print(f"对答案 {len(r)} 个")
    print(status(a.day))


if __name__ == "__main__":
    main()
