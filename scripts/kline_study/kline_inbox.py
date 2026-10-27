# -*- coding: utf-8 -*-
"""kline_inbox.py — K 线 / 分时截图收件箱(10/25 用户定; 零 token, 只读行情库)

目录(用户定):
  原图   downloads/kline/<yyyy.mm.dd>/      只放原图(用户贴图 / Java 上传接口落这里); 定时任务可以物理删除, 不影响下面任何东西
  产物   results/kline/<yyyy.mm.dd>/         日 K 标注图(箱体 + 导师 B / S / T)· 续画图(日 K 续画日 K, 分时 / 五日续画分时)· _status.json
  案例库 results/kline/cases.jsonl           (intake.py; 一个案例 = 同一只票同一截止日的几张图)
不进 DB: 量不大, 核销记录就是 _status.json 的字段(原来"逻辑删除"那一层 = 字段 原图已删)

一张图的三次核销(_status.json 每张图一条):
  ①收件  OCR 认名称 / 代码 / 图类型 / 价格轴 → intake 建案例(事实 / 统计 / 龙虎榜 / 发哥 / 电报 / 3 秒盘口)→ 续画(见下)
  ②导师  导师逐笔(同花顺投资账本)常在 23:10 之后才拉到 / 蒸馏完才全 → 每次跑都比较"案例的 导师核销至"和"账本最新逐笔日", 有新数据就重拉导师腿 + 3 秒盘口 + 重画标注
  ③对答案 截止日后满 3 个交易日 → 真实路径落在哪个情景(intake.resolve)→ 追加 market-skill kline_cases.md
续画(10/26 起 v2 引擎, 取代 scen_next.scen3 的 强 / 震荡 / 弱):
  scen_v2.scen(代码, 截止日): 票型 10 类 × T+1 / T+2 走法 8 种(多因子 GBDT + 近邻真实样本, 样本外验证) → 续画 2 天;
  每张截图出 4 张: {code}_{图stem}_v2_1/2/3{T+1走法}-{T+2走法}.png = 两日组合 top3(各画一个最像的真实样本) + _v2_X极端.png(涨停 / 跌停 / 冲高A杀 / 深V 不在单日 top3 且 ≥3% 的);
  右侧总表 = 票型 · 单日 top3 · 两日 top3 · 极端概率 · 置信 / 样本外 n · pa_reason 关键结论(K1 形态 / 箱体 / 抛压支撑 / 竞价切换表, 全文 results/kline/pa_reason_<代码>_<截止日>.md, 没有就现跑) · 不自信点
  分时 / 五日续画的价格轴 = 原图价格轴(0% 价以库为准: 分时 = 昨收, 五日 = 窗口前一天收盘; 上下沿吸附到原图框线)
  v2 报错(多半是 scen_v2.py all 没跑、特征表没到截止日)→ 预测.err 记原因 + 旧引擎 scen3 兜底出图(引擎=v1兜底), 下一轮再试 v2(最多 V2_RETRY 轮); 转债跳过
  旧引擎出过的图: 记录挪到 预测_v1, 图文件不删; 必须用 anaconda python(项目 venv 没 sklearn); 一只票 v2 约 7~12 秒
谁调:
  check md 每轮(收盘后)--all;tzzb 蒸馏(tzzb_distill)跑完那一轮必然覆盖 ②
  Java  POST /api/kline/upload(存原图)· POST /api/kline/process?date=yyyy.mm.dd(非交易日 / 想马上看)
  OCR: RapidOCR(onnxruntime, 只用 CPU 不用 GPU), 限 2 线程: 一张 2.3~3 秒、约 2.4 核、113MB; 盘中照跑
用法:
  python kline_inbox.py --all [--day yyyy.mm.dd]          收件 + 续画 + 导师核销 + 对答案(不写 --day = 全部有新图 / 没核销完的日子)
  python kline_inbox.py --scan --day 2026.10.24 [--force]  只收件
  python kline_inbox.py --predict --day ... [--repredict]  只续画(--repredict = 已有 v2 图也重画: 模型 / 画法改了之后)
  python kline_inbox.py --status [--day ...]               看核销进度
  python kline_inbox.py --code 002354 --day ... <文件名>   OCR 认不出代码时人工指定
  衔接式续画(10/26 晚, 默认关): 加 --stitch 或环境变量 KLINE_STITCH=1 → draw_stitch.py 画(在截图图框右边接着画, 文件名不变); 例: --predict --day ... --repredict --stitch
"""
import argparse
import datetime as dt
import os
import hashlib
import json
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")   # scen_v2 的 sklearn 预测 / numpy 别吃满 24 核(盘中也可能跑)
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent)]
import intake as I   # noqa: E402

INBOX = ROOT / "downloads" / "kline"
OUT = ROOT / "results" / "kline"
EXT = {".jpg", ".jpeg", ".png", ".webp"}


def rel(p):
    """仓库内路径写相对路径(_status.json 惯例), 仓库外(自测临时目录)写绝对路径"""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


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


V2_RETRY = 5   # v2 失败(多半是特征表还没建到截止日: scen_v2.py all 没跑)最多重试几轮, 期间用旧引擎兜底出图
# 10/26 晚: 衔接式续画(draw_stitch: 在截图图框右边剖开接着画, 同价格轴 / 同 K 线宽 / 同配色 + 日 K 近日放大)。默认关, 用户审完再开:
#   环境变量 KLINE_STITCH=1 或命令行 --stitch; 文件名和旧画法一样(覆盖), 衔接画法报错就退回旧画法(预测.衔接err 记原因)
STITCH = os.environ.get("KLINE_STITCH", "0") == "1"


def _draw(shot, kind, code, v2, od, end, **kw):
    """续画一张截图: 开关开 → draw_stitch.draw_v2_stitch(失败退回旧画法); 关 → draw_future.draw_v2(原行为)。返回 (输出, C, 画法, 衔接err)"""
    import draw_future as DF
    if STITCH:
        try:
            import draw_stitch as DS
            outs, C = DS.draw_v2_stitch(shot, kind, code, v2, od, end, **kw)
            return outs, C, "衔接", None
        except Exception as e:   # noqa: BLE001
            err = f"衔接画法: {e!r}"[:200]
            outs, C = DF.draw_v2(shot, kind, code, v2, od, end, **kw)
            return outs, C, "旧", err
    outs, C = DF.draw_v2(shot, kind, code, v2, od, end, **kw)
    return outs, C, None, None


def pa_load(code, end):
    """pa_reason 逐根推理(results/kline/pa_reason_<代码>_<截止日>.json / .md); 没有就现跑一次并落盘
    → (dict 或 None, md 相对路径 或 None, 错误 或 None); ST / 北交所等 pa_reason 不收的票返回 None, 图上注明只看 v2"""
    j, md = OUT / f"pa_reason_{code}_{end}.json", OUT / f"pa_reason_{code}_{end}.md"
    err = None
    if not j.exists():
        try:
            import pa_reason as PR
            o = PR.run(code, end)
            j.write_text(json.dumps(o, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            md.write_text(PR.render(o), encoding="utf-8")
        except (Exception, SystemExit) as e:   # noqa: BLE001  pa_reason 认不了的票用 SystemExit 报
            return None, None, repr(e)[:200]
    try:
        return json.loads(j.read_text(encoding="utf-8")), (rel(md) if md.exists() else None), err
    except (OSError, ValueError) as e:
        return None, None, repr(e)[:200]


def _intra_axis(g, x):
    """分时 / 五日图的价格轴(OCR axis → 原图坐标); 对不上返回 (None, 原因)
    0% 对应价以库为准(10/26: 五日图顶部刻度被光标价格框盖住时 OCR 反推的 0% 会偏, 北新路桥五日 2.934 实为 2.98):
      分时 = 截止日昨收; 五日 = 5 日窗口前一天收盘(截止日往前第 6 根日线)。OCR 和库差 >2%(分时)/ >3%(五日)= 认错图或叠加了别的, 不画"""
    ax = (g.get("ocr") or {}).get("axis")
    if (g.get("类型") or "") not in ("分时", "五日"):
        return None, None
    if not ax or not ax.get("base"):
        return None, "OCR 没认出价格轴"
    F = x["事实"]
    base = ax["base"]
    if g["类型"] == "分时":
        if abs(ax["base"] - F["昨收"]) / ax["base"] > 0.02:
            return None, f"价格轴 0% = {ax['base']} 和库里昨收 {F['昨收']} 对不上(可能是光标 / 叠加正股)"
        base = F["昨收"]
    else:
        R = I.daily_rows(x["code"], x["截止日"], 6)
        if len(R) == 6 and R[-1][0] == x["截止日"] and R[0][4]:
            if abs(ax["base"] - R[0][4]) / R[0][4] > 0.03:
                return None, f"五日图价格轴 0% = {ax['base']} 和库里 {R[0][0]} 收盘 {R[0][4]} 对不上"
            base = R[0][4]
    return {"top": ax["top_y"], "zero": ax["zero_y"], "bot": ax["bot_y"], "pmax": ax["top_pct"], "base": base, "ocr_base": ax["base"],
            "day_w": 249 if g["类型"] == "五日" else 300}, None


def _need(g, force):
    p = g.get("预测") or {}
    if force:
        return True
    if p.get("引擎") == "v2" or p.get("跳过"):
        return False
    return (p.get("v2重试") or 0) < V2_RETRY


def predict(day, force=False):
    """续画: v2 引擎(scen_v2.scen: 票型 10 类 × 走法 8 种 → 两日组合 top3 各一张 + 极端一张, 续画 2 天) + pa_reason 关键结论;
    v2 报错(特征表没建到截止日等)→ 错误记进 预测.err, 用旧引擎 scen_next.scen3(强 / 震荡 / 弱, 3 日)兜底出图, 下一轮再试 v2(最多 V2_RETRY 轮)
    旧引擎出过的图记录挪到 预测_v1(图文件不删, 留作对照); force = 已有 v2 图也重画"""
    import draw_future as DF
    st = load_st(day)
    cases = {x["key"]: x for x in I.load_cases()}
    by_case = {}
    for name, g in st["images"].items():
        if g.get("case") and not g.get("重复") and (INBOX / day / name).exists() and _need(g, force):
            by_case.setdefault(g["case"], []).append(name)
    od = OUT / day
    for key, names in by_case.items():
        x = cases.get(key)
        if not x:
            continue
        code, end = x["code"], x["截止日"]
        # 10/26 晚: v2 已加转债(和股票同一个 K 线预测业务, 转债按 20cm 口径), 不再跳过
        for n in names:   # 旧引擎(v1)出过的图: 记录挪走, 文件留着
            p = st["images"][n].get("预测") or {}
            if p.get("图") and p.get("引擎") != "v2":
                st["images"][n]["预测_v1"] = p
                st["images"][n].pop("预测")
        try:
            import scen_v2 as SV
            v2 = SV.scen(code, end)
        except Exception as e:   # noqa: BLE001
            err = f"v2: {e!r}"[:300]
            todo = [n for n in names if not (st["images"][n].get("预测") or st["images"][n].get("预测_v1") or {}).get("图")]
            if todo:
                predict_v1(day, st, x, todo)
            for n in names:
                p = st["images"][n].setdefault("预测", {})
                p.update({"err": err, "v2重试": (p.get("v2重试") or 0) + 1, "时间": now()})
            continue
        pa, pa_md, pa_err = pa_load(code, end)
        summ = {"引擎": "v2", "票型": v2["票型"], "单日top3": [f"{y['名']} {y['概率']}%" for y in v2["top3_单日"]],
                "两日top3": [f"{y['名']} {y['概率']}%" for y in v2["top3_两日"]],
                "极端T+1": {k: v["模型"] for k, v in v2["极端"]["T+1"].items()}, "置信": v2.get("置信"),
                "pa_reason": pa_md or f"无({pa_err})"}
        days_ = DF.next_days(end, 2)
        C = None
        for n in sorted(names, key=lambda n: not (st["images"][n].get("类型") or "").startswith("日K")):   # 先日 K(拿校准后的收盘价), 再分时 / 五日
            g = st["images"][n]
            ty = g.get("类型") or ""
            try:
                if ty.startswith("日K"):
                    outs, C1, how, serr = _draw(INBOX / day / n, "daily", code, v2, od, end, days=days_, pa=pa, pa_md=pa_md)
                    C = C1
                else:
                    gg, why = _intra_axis(g, x)
                    if not gg:
                        g["预测"] = {"跳过": why or f"图类型 {ty} 不续画", "时间": now()}
                        continue
                    outs, _, how, serr = _draw(INBOX / day / n, "intra", code, v2, od, end, C=C, g=gg, days=days_, pa=pa, pa_md=pa_md)
                g["预测"] = {**summ, "图": [rel(o) for o in outs], "时间": now()}
                if how:
                    g["预测"]["画法"] = how
                if serr:
                    g["预测"]["衔接err"] = serr
            except Exception as e:   # noqa: BLE001
                p = g.setdefault("预测", {})
                p.update({"err": f"v2 画图: {e!r}"[:300], "v2重试": (p.get("v2重试") or 0) + 1, "时间": now()})
    save_st(day, st)


def predict_v1(day, st, x, names):
    """旧引擎兜底(scen_next.scen3: 强 / 震荡 / 弱, 续画 3 日; 一个情景一张图, 文件名 {code}_{图stem}_{A强|B震荡|C弱}.png)"""
    import draw_future as DF
    import scen_next as SN
    code, end = x["code"], x["截止日"]
    try:
        S_ = SN.scen3(code, I.next_day(end))
    except Exception as e:   # noqa: BLE001
        for n in names:
            st["images"][n]["预测"] = {"err_v1": f"v1: {e!r}"[:200]}
        return
    if not S_ or not S_.get("情景"):
        for n in names:
            st["images"][n]["预测"] = {"err_v1": "样本不足, 没有 3 日情景"}
        return
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
                outs.append(rel(op))
            except Exception as e:   # noqa: BLE001
                outs.append(f"失败 {e!r}"[:120])
        g["预测"] = {"图": outs, "时间": now(), "引擎": "v1兜底"}
    for n in names:
        g = st["images"][n]
        gg, why = _intra_axis(g, x)
        if not gg:
            if why:
                g["预测"] = {"跳过": why}
            continue
        F = x["事实"]
        CC = C or {"close": F["收"], "high": F["高"], "low": F["低"], "name": x["name"]}
        outs = []
        for i, sc in enumerate(S_["情景"]):
            op = od / f"{code}_{Path(n).stem}_{'ABC'[i]}{sc['名']}.png"
            try:
                DF.intraday(INBOX / day / n, code, sc, "ABC"[i], S_, op, CC, g=gg, days=dd)
                outs.append(rel(op))
            except Exception as e:   # noqa: BLE001
                outs.append(f"失败 {e!r}"[:120])
        g["预测"] = {"图": outs, "时间": now(), "引擎": "v1兜底"}


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


def _pred_tag(g):
    p = g.get("预测") or {}
    if p.get("图"):
        return "✓" + ("" if p.get("引擎") == "v2" else f"({p.get('引擎') or 'v1'})") + (" v2err" if p.get("err") else "")
    if p.get("跳过"):
        return "跳过"
    return ("✗err" if p.get("err") else "-") + ("(有v1图)" if (g.get("预测_v1") or {}).get("图") else "")


def status(day=None):
    L = []
    for d in days(day):
        st = load_st(d)
        for name, g in sorted(st["images"].items()):
            L.append(f"{d} {name} {g.get('case') or '-'} {(g.get('类型') or '')[:6]} 收件{'✓' if g.get('收件') else '✗'} 导师至{g.get('导师核销至') or '-'} "
                     f"预测{_pred_tag(g)} 对答案{'✓' if g.get('对答案') else '待'}{' 原图已删' if g.get('原图已删') else ''}{' 待:' + g['待'] if g.get('待') else ''}{' 重复' if g.get('重复') else ''}")
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
    ap.add_argument("--repredict", action="store_true", help="已有 v2 图也重画(模型 / 画法改了之后)")
    ap.add_argument("--mentor", action="store_true")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true", help="盘中也跑 OCR(盘中二次确认)")
    ap.add_argument("--stitch", action="store_true", help="衔接式续画(draw_stitch; 默认关, 也可用环境变量 KLINE_STITCH=1)")
    a = ap.parse_args()
    if a.stitch:
        global STITCH
        STITCH = True
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
        if a.predict or a.all or a.repredict:
            predict(d, force=a.repredict)
    if a.mentor or a.all:
        n, latest = mentor_recheck()
        print(f"导师核销: {n} 个案例补到 {latest}")
    if a.resolve or a.all:
        r = resolve()
        print(f"对答案 {len(r)} 个")
    print(status(a.day))


if __name__ == "__main__":
    main()
