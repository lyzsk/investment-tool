# -*- coding: utf-8 -*-
"""index_constituents.py — A 股指数成分 + 个股行业 时点(point-in-time)表的原料抓取 / 区间重建 / 入库(2026-10-16 建, TODO 二B-12)

三段(互相独立, 可分别重跑):
  fetch  [--only bs,bsind,cni,sina,csi,sw] [--from 2019-01-07] [--index 000300] [--refresh]
         拉原料到 downloads/market/index_pit/raw/(逐请求落盘缓存, 已有的不重拉; 断了重跑即续; baostock 只能单进程)
         调样生效后刷新: fetch --refresh(重抓国证/中证/新浪当前名单 + 补新周一的 baostock 快照) → build → import --commit
  build  零请求: 原料 → 时点区间 jsonl(index_constituent / stock_industry / index_constituent_coverage)+ 校验报告 build_report.json
  import [--commit]
         默认 dry-run: 只打印将插入的行数与样例行, 不连库写; --commit 才写(须先执行 sql/todo/index_constituent_industry_20261016.sql 建表)
         写法: 三张新表各自整表重建(一个事务: DELETE 全表 → 批量 INSERT); 只碰这三张新表, 不改任何现有表
  import --commit --incremental(10/17 A7 用户定"动态更新"): 按自然键比对库里现有行——新键 INSERT / 同键但字段变了(如调出填 out_date) UPDATE /
         库里有、新 build 里没有的(区间被精修替换) 软删(is_deleted=1); 一个事务, 打印 增/改/删 计数; 历史可审计。定时任务一律用这个

时点口径: 一条记录=[in_date, out_date) 半开区间; 日期 D 的成分 = in_date <= D AND (out_date IS NULL OR out_date > D)
  out_date = 剔除生效日(当天已不在指数里); in_exact=0 表示左删失(覆盖起点那天已是成分, 真实纳入日更早、未知)
数据源(实测见 build_report.json / 报告):
  沪深300/中证500/上证50: baostock query_hs300/zz500/sz50_stocks(date=周一) 每周一取快照 → 差分; 周粒度, 新浪"纳入日期"精修到真实生效日
  深证成指/创业板指: 国证指数官网 cnindex 样本调整历史(index_detail_hist_adjust_cni 同源), 2021-12-13 起含临时调整
  中证1000/中证2000/中证A500/科创50/北证50: 只有"当前成分+纳入日期"(新浪 vII_NewestComponent) + 中证官网当前成分(oss-ch.csindex);
         历史已剔除样本无免费源 → 只在 coverage.pit_from 之后完整, 之前为"当前存活者子集"(见 coverage 表)
  行业: 申万研究所官网 StockClassifyUse_stock.xls(个股申万行业变动全史, 2021 版起有名称字典 SwClassCode_2021.xls)
        + 证监会行业(baostock query_stock_industry, 月度快照差分, 申万缺的票兜底)
请求节奏: 每次请求后 sleep 1.6~2.4s(≤0.5 次/秒); HTTP 走 scripts/lib/req_guard(熔断/日预算); 不碰东财 push2 / 腾讯 ifzq
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/market/index_constituents.py fetch|build|import [...]
"""
import argparse
import datetime as dt
import functools
import io
import json
import random
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
warnings.simplefilter("ignore")

OUT = ROOT / "downloads" / "market" / "index_pit"
RAW = OUT / "raw"
HS300_MD = ROOT / "md" / "hs300" / "hs300-2025-03-27.md"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9"}

# 事实观察的指数(facts/md/scripts 实际引用); method 决定区间重建方式
INDEXES = [
    dict(symbol="sh000016", code="000016", name="上证50", publisher="csindex", n=50, method="baostock", bs="query_sz50_stocks", sina=True, csi=True),
    dict(symbol="sh000300", code="000300", name="沪深300", publisher="csindex", n=300, method="baostock", bs="query_hs300_stocks", sina=True, csi=True),
    dict(symbol="sh000905", code="000905", name="中证500", publisher="csindex", n=500, method="baostock", bs="query_zz500_stocks", sina=True, csi=True),
    dict(symbol="sh000852", code="000852", name="中证1000", publisher="csindex", n=1000, method="current", sina=True, csi=True),
    dict(symbol="csi932000", code="932000", name="中证2000", publisher="csindex", n=2000, method="current", sina=True, csi=True),
    dict(symbol="sh000510", code="000510", name="中证A500", publisher="csindex", n=500, method="current", sina=True, csi=True),
    dict(symbol="sh000688", code="000688", name="科创50", publisher="csindex", n=50, method="current", sina=True, csi=True),
    dict(symbol="sz399001", code="399001", name="深证成指", publisher="cnindex", n=500, method="cnindex", sina=True, csi=False),
    dict(symbol="sz399006", code="399006", name="创业板指", publisher="cnindex", n=100, method="cnindex", sina=True, csi=False),
    dict(symbol="bj899050", code="899050", name="北证50", publisher="bse", n=50, method="current", sina=True, csi=True),
]
CSRC_L1 = {"A": "农、林、牧、渔业", "B": "采矿业", "C": "制造业", "D": "电力、热力、燃气及水生产和供应业", "E": "建筑业", "F": "批发和零售业",
           "G": "交通运输、仓储和邮政业", "H": "住宿和餐饮业", "I": "信息传输、软件和信息技术服务业", "J": "金融业", "K": "房地产业",
           "L": "租赁和商务服务业", "M": "科学研究和技术服务业", "N": "水利、环境和公共设施管理业", "O": "居民服务、修理和其他服务业",
           "P": "教育", "Q": "卫生和社会工作", "R": "文化、体育和娱乐业", "S": "综合"}
SW2021_FROM = "2021-07-30"   # 申万 2021 版个股归属起点(xls 中 3069 条同日切换)
SW2014_FROM = "2014-02-21"


def nap():
    time.sleep(1.6 + random.random() * 0.8)


def wjson(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def rjson(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def symbol_of(code):
    """6 位代码 → 全库 symbol(同 security_master): 6/9(非92)=沪, 0/2/3=深, 92/4/8=北"""
    c = str(code).zfill(6)
    if c.startswith("92") or c[0] in "48":
        return "bj" + c
    if c[0] in "69":
        return "sh" + c
    return "sz" + c


# ----------------------------------------------------------------------------------------------------------------- fetch
def mondays(beg, end):
    d = dt.date.fromisoformat(beg)
    d -= dt.timedelta(days=d.weekday())
    while d <= end:
        yield d
        d += dt.timedelta(days=7)


class BS:
    """baostock 会话: 失败自动重登 3 次; 每次查询后 nap()"""

    def __init__(self):
        import socket
        import baostock as bs
        # baostock 裸 socket 无超时: 同机第二个进程登录会把前一个会话挤掉, 前者 recv 永久卡死(10/16 实测) → 设超时让它抛错重登
        # 结论: baostock 只能单进程串行抓
        socket.setdefaulttimeout(60)
        self.bs = bs
        self.login()

    def login(self):
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            lg = self.bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login 失败 {lg.error_code} {lg.error_msg}")

    def query(self, fn, **kw):
        last = None
        for a in range(4):
            if a:
                time.sleep(5 * a)
                try:
                    self.login()
                except Exception as e:  # noqa: BLE001
                    last = e
                    continue
            try:
                rs = getattr(self.bs, fn)(**kw)
                if rs.error_code != "0":
                    last = RuntimeError(f"{fn} {kw} error {rs.error_code} {rs.error_msg}")
                    continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                nap()
                return rs.fields, rows
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"baostock {fn} {kw} 连续失败: {last}")

    def close(self):
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                self.bs.logout()
            except Exception:  # noqa: BLE001
                pass


def fetch_bs(beg, today, only_codes=None):
    """沪深300/中证500/上证50 每周一快照"""
    s = None
    try:
        for ix in [i for i in INDEXES if i["method"] == "baostock" and (not only_codes or i["code"] in only_codes)]:
            n_new = 0
            for d in mondays(beg, today):
                f = RAW / "bs" / ix["code"] / f"{d.isoformat()}.json"
                if f.exists():
                    continue
                s = s or BS()
                fields, rows = s.query(ix["bs"], date=d.isoformat())
                ups = sorted({r[0] for r in rows})
                wjson(f, {"query": d.isoformat(), "fields": fields, "updateDates": ups, "rows": rows})
                n_new += 1
                if n_new % 20 == 0:
                    print(f"  bs {ix['name']} 已取到 {d} (+{n_new})", flush=True)
            print(f"bs {ix['name']}: 新取 {n_new} 周", flush=True)
    finally:
        if s:
            s.close()


def fetch_bsind(beg, today):
    """证监会行业: 每季首月 1 日快照(baostock 返回最近 updateDate)"""
    s = None
    try:
        d = dt.date.fromisoformat(beg).replace(day=1)
        n_new = 0
        while d <= today:
            f = RAW / "bs_industry" / f"{d.isoformat()}.json"
            if not f.exists():
                s = s or BS()
                fields, rows = s.query("query_stock_industry", date=d.isoformat())
                wjson(f, {"query": d.isoformat(), "fields": fields, "updateDates": sorted({r[0] for r in rows}), "rows": rows})
                n_new += 1
            m = d.month + 3   # 季度快照(1/4/7/10 月 1 日): 单次返回全市场 ~5000 行、实测 30~40 秒/次, 月度太慢; 证监会只是申万缺失时兜底
            d = dt.date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
        print(f"bs 证监会行业: 新取 {n_new} 期", flush=True)
    finally:
        if s:
            s.close()


def http_get(url, binary=False, verify=True, params=None):
    """HTTP 走 req_guard 记账/熔断; 用 requests(带 certifi)发"""
    import requests
    from req_guard import gcall
    r = gcall(url, lambda: requests.get(url, params=params, headers=UA, timeout=60, verify=verify))
    nap()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {url}")
    return r.content if binary else r.content


def _bad_cache(f):
    """10/17: 旧事故留下的坏缓存(源站错误页被写成 .xlsx) —— 认出就删掉重抓"""
    try:
        if f.read_bytes()[:2] == b"PK":
            return False
    except OSError:
        return True
    print(f"缓存损坏, 删除重抓: {f.name}", flush=True)
    f.unlink()
    return True


def fetch_cni():
    for ix in [i for i in INDEXES if i["method"] == "cnindex"]:
        f = RAW / "cni" / f"{ix['code']}_adjust.xlsx"
        if f.exists() and not _bad_cache(f):
            continue
        b = http_get("http://www.cnindex.com.cn/sample-detail/download-adjustment", binary=True, params={"indexcode": ix["code"]})
        if not b.startswith(b"PK"):   # 10/17 事故: 源返回 200 + 45 字节文本"xxx的样本历史调样文件不存在!"(换日/换 UA 都如此),
            #   旧代码照样写进缓存 → build 没这两个指数的成分 → 增量导入把它们整段软删(10/17 误删 深证成指 686 + 创业板指 178 行)
            raise RuntimeError(f"cnindex {ix['name']} 返回的不是 xlsx(前 60 字节: {b[:60]!r}); 缓存不落盘, 本次刷新中止")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b)
        print(f"cnindex {ix['name']} 调整历史 {len(b)} B", flush=True)


SINA_ROW = re.compile(r"(\d{6})\s+(.+?)\s+(\d{4}-\d\d-\d\d)")   # 名称可含空格(京东方 A / TCL 中环)


def parse_sina(html):
    s = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ")
    s = re.sub(r"\s+", " ", s)
    i = s.find("品种代码 品种名称 纳入日期")
    if i < 0:
        return None, []
    pages = re.findall(r"共(\d+)页", s)
    j = s.find("客户服务热线", i)
    return int(pages[0]) if pages else 1, SINA_ROW.findall(s[i:j if j > 0 else None])


def sina_page(code, p):
    url = (f"https://vip.stock.finance.sina.com.cn/corp/go.php/vII_NewestComponent/indexid/{code}.phtml" if p == 1 else
           f"https://vip.stock.finance.sina.com.cn/corp/view/vII_NewestComponent.php?page={p}&indexid={code}")
    pg, rr = parse_sina(http_get(url).decode("gbk", "ignore"))
    if pg is None:
        raise RuntimeError(f"新浪 {code} 第 {p} 页解析不到表头")
    return pg, rr


def sina_resolve(j, full=None):
    """新浪分页按纳入日期倒序, 同日并列的样本跨页时排序不稳定(实测同一并列组翻页会重复/漏) →
       每页的"日期序列"是确定的, 代码在并列组内乱序。用首轮各页日期多重集 - 已见代码的日期 = 各日期的空位数;
       full(中证官网当前全名单)中没见到的代码只可能落在有空位的日期上: 只剩一个日期有空位则唯一确定。
       返回 (dates{code:d}, names{code:name}, unresolved{code:[候选日期]}, slots{d:空位})"""
    first = j["pages"]
    dates, names = {}, {}
    for rounds in [first] + j.get("rounds", []):
        for rows in rounds.values():
            for c, n, d in rows:
                dates[c], names[c] = d, n
    slots = Counter(d for rows in first.values() for _, _, d in rows)
    slots.subtract(Counter(dates.values()))
    slots = {d: k for d, k in slots.items() if k > 0}
    unresolved = {}
    for c in sorted(set(full or []) - set(dates)):
        cand = sorted(slots)
        if len(cand) == 1:
            dates[c] = cand[0]
        else:
            unresolved[c] = cand
    return dates, names, unresolved, slots


def fetch_sina():
    for ix in [i for i in INDEXES if i["sina"]]:
        f = RAW / "sina" / f"{ix['code']}.json"
        j = rjson(f)
        if j is None:
            pages, p, first = 1, 1, {}
            while p <= pages:
                pg, rr = sina_page(ix["code"], p)
                pages = max(pages, pg)
                first[str(p)] = rr
                p += 1
            j = {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "npages": pages, "pages": first, "rounds": []}
            wjson(f, j)
        full = [r[1] for r in (rjson(RAW / "csindex" / f"{ix['code']}.json", {}) or {}).get("rows", [])]
        # 补抓: 只重抓"含空位日期"的页, 最多 4 轮, 直到全名单都定了日期或不再进展
        while full and len(j["rounds"]) < 4:
            dates, _, unres, slots = sina_resolve(j, full)
            if not unres:
                break
            pages = [p for p, rows in j["pages"].items() if any(d in slots for _, _, d in rows)]
            if len(pages) > 30:
                print(f"  新浪 {ix['name']}: 待定 {len(unres)} 只涉及 {len(pages)} 页, 超过补抓上限 30 页, 不补", flush=True)
                break
            rnd = {p: sina_page(ix["code"], int(p))[1] for p in pages}
            j["rounds"].append(rnd)
            wjson(f, j)
            print(f"  新浪 {ix['name']}: 补抓第 {len(j['rounds'])} 轮 {len(pages)} 页", flush=True)
        dates, _, unres, slots = sina_resolve(j, full)
        print(f"新浪 {ix['name']}: {j['npages']} 页, 定日期 {len(dates)} 只(名义 {ix['n']}), 待定 {len(unres)} 只, 空位 {slots}", flush=True)


def fetch_csi():
    import pandas as pd
    for ix in [i for i in INDEXES if i["csi"]]:
        f = RAW / "csindex" / f"{ix['code']}.json"
        if f.exists():
            continue
        try:
            b = http_get(f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/{ix['code']}cons.xls", binary=True)
            df = pd.read_excel(io.BytesIO(b), dtype=str)
        except Exception as e:  # noqa: BLE001
            # 10/17 审计中-4: 原来写空名单缓存 + 不报错 → build 用空的中证名单继续、可能静默软删; 改为不落盘并抛出(计入 fetch 失败)
            raise RuntimeError(f"中证官网 {ix['name']} 当前成分取不到(不落缓存): {e}")
        rows = [[str(r.iloc[0]), str(r.iloc[4]).zfill(6), str(r.iloc[5])] for _, r in df.iterrows()]
        wjson(f, {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "rows": rows})
        print(f"中证官网 {ix['name']}: {len(rows)} 只, 日期 {sorted({r[0] for r in rows})}", flush=True)


def fetch_sw():
    for name in ("StockClassifyUse_stock.xls", "SwClassCode_2021.xls"):
        f = RAW / f"sw_{name}"
        if f.exists():
            continue
        # 申万官网证书链本机 certifi 校验不过(实测 SSLCertVerificationError), 公开静态文件, 关校验下载
        b = http_get(f"https://www.swsresearch.com/swindex/pdf/SwClass2021/{name}", binary=True, verify=False)
        if not b.startswith(bytes.fromhex("d0cf11e0")):   # 10/17 审计中-4: 老式 xls(OLE2)文件签名 D0 CF 11 E0; 错误页不落盘
            raise RuntimeError(f"申万 {name} 返回的不是 xls(前 40 字节 {b[:40]!r}), 不落缓存")
        f.write_bytes(b)
        print(f"申万 {name}: {len(b)} B", flush=True)
    f = RAW / "web" / "tinysoft_swhy.json"
    if not f.exists():
        # 天软公开 FAQ 页: 申万 SWHY 一/二/三级全版本代码→名称(含 2014 版及更早), 补 2021 版字典之外的旧代码名称
        html = http_get("http://www.tinysoft.com.cn/TSDN/HelpDoc/display.tsl?id=31494").decode("gbk", "ignore")
        d = {}
        for r in re.findall(r"<tr>((?:<td[^>]*>.*?</td>){6})</tr>", html, re.S):
            tds = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if tds[0].startswith("SWHY") and len(tds[0]) == 10:
                d[tds[0][4:]] = dict(name=tds[1].replace("申万", ""), parent=tds[2][4:], start=tds[4], end=tds[5])
        wjson(f, d)
        print(f"天软申万代码表: {len(d)} 个代码", flush=True)


def cmd_fetch(a):
    today = dt.date.today()
    only = set((a.only or "sw,cni,sina,csi,bs,bsind").split(","))
    prev = {}
    if a.refresh:   # "当前名单"类源(国证调样历史/中证当前成分/新浪纳入日期)缓存作废重抓; baostock 周快照按日期缓存, 新的周一自动补
        # 10/17 晚 审计(台账 Top-1): 原来先删缓存再抓, 源站坏了缓存就没了 → 改成挪进 _prev/, 该源抓成功才删, 失败就挪回来
        for sub, pat in (("cni", "*.xlsx"), ("csindex", "*.json"), ("sina", "*.json")):
            if sub.replace("csindex", "csi") in only:
                bk = RAW / sub / "_prev"
                bk.mkdir(parents=True, exist_ok=True)
                for f in (RAW / sub).glob(pat):
                    f.replace(bk / f.name)
                prev[sub.replace("csindex", "csi")] = (RAW / sub, bk)
    steps = [("sw", fetch_sw), ("cni", fetch_cni), ("csi", fetch_csi), ("sina", fetch_sina),
             ("bs", lambda: fetch_bs(a.beg, today, a.index.split(",") if a.index else None)), ("bsind", lambda: fetch_bsind(a.beg, today))]
    bad, ran = [], []
    for k, fn in steps:
        if k not in only:
            continue
        ran.append(k)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — 一个源失败不拖垮其他源, 末尾汇总非 0 退出
            print(f"[FAIL] {k}: {e}", flush=True)
            bad.append(k)
        if k in prev:
            d, bk = prev[k]
            for f in bk.iterdir():
                if k in bad and not (d / f.name).exists():
                    f.replace(d / f.name)   # 失败: 旧缓存挪回(新抓到一半的不覆盖)
                else:
                    f.unlink()
            bk.rmdir()
    print("fetch 完成" + (f", 失败: {bad}" if bad else ""), flush=True)
    return (1 if len(bad) == len(ran) else 4) if bad else 0   # 4=部分源失败(其余照常; import 会冻结受影响的指数)


# ----------------------------------------------------------------------------------------------------------------- build
def snapshots_to_intervals(snaps):
    """snaps: [(eff_date, {code: name})] 升序 → [{code,name,in,out,in_exact}]; 第一期在场者左删失(in_exact=0)"""
    open_, out = {}, []
    for i, (d, mem) in enumerate(snaps):
        for c in [c for c in open_ if c not in mem]:
            r = open_.pop(c)
            r["out"] = d
            out.append(r)
        for c, nm in mem.items():
            if c not in open_:
                open_[c] = dict(code=c, name=nm, ins=d, out=None, in_exact=1 if i else 0, prev=snaps[i - 1][0] if i else None)
    return out + list(open_.values())


def load_bs_snaps(ix):
    by_up = {}
    for f in sorted((RAW / "bs" / ix["code"]).glob("*.json")):
        j = rjson(f)
        if not j or not j["rows"]:
            continue
        up = max(j["updateDates"])
        by_up[up] = {r[1].split(".")[1]: r[2] for r in j["rows"] if r[0] == up}
    return sorted(by_up.items())


@functools.lru_cache(maxsize=1)
def periodic_dates():
    """中证/国证定期调样生效日 = 每年 6 月、12 月第二个星期五之后的第一个交易日(交易日历取行情库上证指数日线, 只读)"""
    from kline_db import db
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select trade_date from kline_day where symbol='sh000001' and trade_date >= '2018-01-01' order by trade_date")
        cal = [d.isoformat() for (d,) in cur.fetchall()]
    finally:
        conn.close()
    out = []
    for y in range(2018, dt.date.today().year + 1):
        for m in (6, 12):
            d = dt.date(y, m, 1)
            fri = d + dt.timedelta(days=(4 - d.weekday()) % 7 + 7)
            nxt = next((c for c in cal if c > fri.isoformat()), None)
            if nxt:
                out.append(nxt)
    return out


def snap_periodic(snaps, E, rep):
    """baostock 快照有停更(实测 2022-08-01 → 2023-03-20 连续 231 天 updateDate 不变): 变化被记在恢复更新那周。
       相邻两期 (P, U] 有成分变化且窗口内恰含定期调样生效日 E → 该次变化的生效日改为 E; 窗口里无 E 的(临时调整)保持 U(周粒度/停更期偏晚)"""
    out, log = [snaps[0]], []
    for (p, a), (u, b) in zip(snaps, snaps[1:]):
        eff = u
        if set(a) != set(b):          # 只比代码集合(改名不算调整)
            es = [e for e in E if p < e <= u]
            if len(es) == 1:
                eff = es[0]
            log.append(dict(prev=p, upd=u, eff=eff, stale_days=(dt.date.fromisoformat(u) - dt.date.fromisoformat(p)).days,
                            add=len(set(b) - set(a)), drop=len(set(a) - set(b)), periodic=len(es) == 1, multi_E=len(es) > 1))
        out.append((eff, b))
    rep["transitions"] = log
    return out


def load_cni_snaps(ix):
    import pandas as pd
    df = pd.read_excel(RAW / "cni" / f"{ix['code']}_adjust.xlsx", dtype=str)
    df.columns = ["beg", "end", "code", "name", "ind", "typ"]
    df["code"] = df["code"].str.zfill(6)
    snaps = []
    for (beg, end), g in df.groupby(["beg", "end"]):
        mem = {r.code: r.name for r in g.itertuples() if r.typ in ("OLD", "+")}
        snaps.append((str(beg)[:10], mem, str(end)[:10], dict(Counter(g["typ"]))))
    snaps.sort()
    return snaps


def refine_with_sina(recs, sina, last_snap_date, stats):
    """新浪"纳入日期"(当前成分的最近一次纳入生效日)精修: 仍在成分里的记录
       - 精确记录: 新浪日期落在 (上一期快照, 本期快照] 内 → 改成新浪日期(周快照 → 真实生效日)
       - 左删失记录: 新浪日期 <= 覆盖起点 → 补上真实纳入日(in_exact=1)
       同一期进场的若全部精修到同一天 d, 则同期出场者 out_date 也改成 d(调入调出同日生效)"""
    entries_by = defaultdict(list)
    for r in recs:
        if r["out"] is not None or r["code"] not in sina:
            continue
        sd = sina[r["code"]]
        if r["in_exact"]:
            if sd == r["ins"]:
                stats["sina_agree"] += 1
            elif r["prev"] and r["prev"] < sd < r["ins"]:
                entries_by[r["ins"]].append(sd)
                r["ins"], r["src_extra"] = sd, "sina_date"
                stats["sina_refined"] += 1
            else:
                stats["sina_conflict"] += 1
                stats.setdefault("sina_conflict_sample", []).append([r["code"], r["ins"], sd])
        elif sd <= r["ins"]:
            r["ins"], r["in_exact"], r["src_extra"] = sd, 1, "sina_date"
            stats["sina_uncensored"] += 1
    # 同期出场者对齐
    for d, sds in entries_by.items():
        if len(set(sds)) == 1:
            for r in recs:
                if r["out"] == d:
                    r["out"] = sds[0]
                    stats["out_aligned"] += 1
    stats["sina_conflict_sample"] = stats.get("sina_conflict_sample", [])[:10]


def append_sina_future(recs, sina, sina_names, last_date, stats):
    """新浪已登记、主源最新快照之后才生效的调入(如 10/19 生效的临时调整): 补调入;
       调出方 = 主源当前成员里新浪没出现的 —— 但新浪分页会漏并列样本, 只有"没出现的个数 == 调入个数"才能认定, 否则不预填并上报"""
    cur = {r["code"] for r in recs if r["out"] is None}
    new = {c: d for c, d in sina.items() if c not in cur and d > last_date}
    if not new:
        return
    for c, d in new.items():
        recs.append(dict(code=c, name=sina_names[c], ins=d, out=None, in_exact=1, prev=last_date, src_extra="sina_future"))
    absent = cur - set(sina)
    dates = sorted(set(new.values()))
    stats["sina_future_in"] = sorted(new.items())
    if len(absent) == len(new) and len(dates) == 1:
        for r in recs:
            if r["out"] is None and r["code"] in absent:
                r["out"], r["src_extra"] = dates[0], ((r.get("src_extra") or "") + "+pending_out").lstrip("+")
        stats["sina_future_out"] = sorted(absent)
    else:
        stats["sina_future_out_unidentified"] = f"调入 {len(new)} 只; 主源在而新浪未见 {len(absent)} 只(含分页漏抓), 调出方无法唯一认定, 未预填 out_date"


def list_dates(codes):
    """security_master 上市日(只读 SELECT); 连不上返回 {}"""
    try:
        from kline_db import db
        conn = db()
    except Exception:  # noqa: BLE001
        return {}
    try:
        cur = conn.cursor()
        out = {}
        codes = sorted(codes)
        for i in range(0, len(codes), 500):
            part = [symbol_of(c) for c in codes[i:i + 500]]
            cur.execute(f"select code, list_date from security_master where symbol in ({','.join(['%s'] * len(part))})", part)
            out.update({c: d.isoformat() for c, d in cur.fetchall() if d})
        return out
    finally:
        conn.close()


# 中证规模指数互斥: 中证1000 = 中证800(300+500)之外; 中证2000 = 中证800 与 中证1000 之外 → 身在互斥指数时不可能已是本指数成分
EXCLUSIVE = {"sh000905": ["sh000300"], "sh000852": ["sh000300", "sh000905"], "csi932000": ["sh000300", "sh000905", "sh000852"]}


def infer_dates(ix, unresolved, slots, built, today_s, st):
    """新浪分页漏掉的样本(只知候选日期集合)用硬约束收窄: ①纳入日 >= 上市日 ②>= 在互斥指数里最后一次调出日
       ③各日期空位守恒: 唯一确定的样本占掉空位, 占满的日期从别人候选里删; 迭代到不动点。
       唯一 → in_exact=1(source +inferred); 仍多解 → 取候选里最晚的作左删失 in_date(真实纳入只会更早, 保守不误报)"""
    ld = list_dates(unresolved.keys())
    excl, pending = defaultdict(list), {}
    for es in EXCLUSIVE.get(ix["symbol"], []):
        for r in built.get(es, []):
            if r["inDate"] > today_s:
                pending[r["conCode"]] = r["inDate"]    # 将调入互斥指数 = 本指数已公告的调出(同日生效)
            else:
                excl[r["conCode"]].append(r["outDate"])
    cand = {}
    for c, cs in unresolved.items():
        lo = ld.get(c, "0000")
        for b in excl.get(c, []):
            lo = max(lo, b or "9999")      # 至今仍在互斥指数里 = 数据冲突, 候选清空并上报
        cand[c] = [d for d in cs if lo <= d <= today_s]
    left = dict(slots)
    fixed = {}
    changed = True
    while changed:
        changed = False
        for c in list(cand):
            cs = [d for d in cand[c] if left.get(d, 0) > 0]
            if len(cs) == 1:
                fixed[c] = cs[0]
                left[cs[0]] -= 1
                del cand[c]
                changed = True
            else:
                cand[c] = cs
    st["inferred_unique"] = len(fixed)
    st["inferred_censored"] = sum(1 for c in cand if cand[c])
    st["inferred_conflict"] = sorted(c for c in cand if not cand[c])[:20]
    st["pending_out_by_exclusive"] = sorted(pending.items())
    return fixed, cand, pending


def build_index(ix, today, report, built):
    st = Counter()
    today_s = today.isoformat()
    cj = rjson(RAW / "csindex" / f"{ix['code']}.json", {"rows": []}) if ix["csi"] else {"rows": []}
    csi = {r[1]: r[2] for r in cj["rows"]}
    sj = rjson(RAW / "sina" / f"{ix['code']}.json")
    sina, sina_names, unresolved, slots = sina_resolve(sj, list(csi)) if sj else ({}, {}, {}, {})
    sina_seen = {c: d for c, d in sina.items() if c in sina_names}     # 新浪页面真实出现过的(不含按空位唯一推出的)
    rep = dict(name=ix["name"], method=ix["method"], sina_pages=sj and sj.get("npages"), sina_seen=len(sina_seen),
               sina_slot_resolved=len(sina) - len(sina_seen), sina_unresolved=len(unresolved), csindex_count=len(csi) or None)
    if ix["method"] in ("baostock", "cnindex"):
        if ix["method"] == "baostock":
            snaps = load_bs_snaps(ix)
            src = "baostock"
            rep["snap_dates"] = len(snaps)
            rep["snap_size_anomaly"] = [(d, len(m)) for d, m in snaps if len(m) != ix["n"]][:20]
            snaps = snap_periodic(snaps, periodic_dates(), rep)
        else:
            s4 = load_cni_snaps(ix)
            snaps = [(d, m) for d, m, _, _ in s4]
            src = "cnindex"
            rep["periods"] = [dict(beg=d, end=e, members=len(m), types=t) for d, m, e, t in s4]
        if not snaps:
            raise RuntimeError(f"{ix['name']} 没有原料快照, 先 fetch")
        recs = snapshots_to_intervals(snaps)
        # 单期缺席(前后都在)= 源数据抖动嫌疑, 列出不自动修
        pos = {d: i for i, (d, _) in enumerate(snaps)}
        by = defaultdict(list)
        for r in recs:
            by[r["code"]].append(r)
        flick = [(c, r["out"]) for c, rs in by.items() for r in rs if r["out"] and any(pos[x["ins"]] == pos[r["out"]] + 1 for x in rs)]
        rep["one_snapshot_gaps"] = flick[:20]
        rep["one_snapshot_gap_count"] = len(flick)
        refine_with_sina(recs, sina_seen, snaps[-1][0], st)
        append_sina_future(recs, sina_seen, sina_names, snaps[-1][0], st)
        # 互斥指数已公告的未来调入 = 本指数同日调出(如 10/19 中证500 成分调入沪深300)
        pend = {}
        for es in EXCLUSIVE.get(ix["symbol"], []):
            pend.update({r["conCode"]: r["inDate"] for r in built.get(es, []) if r["inDate"] > today_s})
        for r in recs:
            if r["code"] in pend and r["out"] is None and r["ins"] < pend[r["code"]]:
                r["out"], r["src_extra"] = pend[r["code"]], ((r.get("src_extra") or "") + "+pending_out").lstrip("+")
                st["pending_out_by_exclusive"] = st.get("pending_out_by_exclusive", 0) + 1
        pit_from = snaps[0][0]
        partial_from = min(r["ins"] for r in recs)     # 新浪补的左删失纳入日可早于首个快照(那段只是当前存活者子集)
        last = snaps[-1][0] if src == "baostock" else today_s   # 国证调样历史抓取当天即最新(含已公告的下一期)
        method_txt = ("baostock 每周一快照差分(周粒度), 新浪纳入日期精修到真实生效日" if src == "baostock" else
                      "国证官网样本调整历史(定期+临时)差分, 新浪纳入日期补左删失")
    else:
        src = "sina"
        recs = []
        fixed, cand, pending = infer_dates(ix, unresolved, slots, built, today_s, st)
        for c, d in sina.items():
            recs.append(dict(code=c, name=sina_names.get(c) or csi.get(c), ins=d, out=None, in_exact=1, prev=None,
                             src_extra=None if c in sina_seen else "slot"))
        for c, d in fixed.items():
            recs.append(dict(code=c, name=csi.get(c), ins=d, out=None, in_exact=1, prev=None, src_extra="inferred"))
        for c, cs in cand.items():
            if cs:
                recs.append(dict(code=c, name=csi.get(c), ins=max(cs), out=None, in_exact=0, prev=None, src_extra="censored"))
        for r in recs:
            if r["code"] in pending and r["out"] is None and r["ins"] < pending[r["code"]]:
                r["out"], r["src_extra"] = pending[r["code"]], ((r.get("src_extra") or "") + "+pending_out").lstrip("+")
        future = sorted({d for d in sina_seen.values() if d > today_s})
        cur_eff = sorted(d for d in sina_seen.values() if d <= today_s)
        # pit_from: 最近一次有调入的生效日起成员完整(样本数恒定, 调出必伴随调入); 之前=当前存活者子集
        pit_from = cur_eff[-1] if cur_eff else None
        partial_from = min(r["ins"] for r in recs) if recs else None
        last = today_s
        rep.update(latest_in=pit_from, future_in=sorted((c, d) for c, d in sina_seen.items() if d > today_s), slots=slots,
                   pending_out_note=(f"新浪已登记未来调入 {len(future)} 个日期, 对应调出方在中证官网名单里与分页漏抓无法区分, 未预填 out_date; "
                                     "生效后重跑 fetch(删 raw/csindex 与 raw/sina 对应文件)+build 即准") if future else None)
        method_txt = "仅当前成分+新浪纳入日期(分页漏抓的用空位守恒/上市日/中证规模互斥推断); pit_from 前为当前存活者子集"
    # 完整度: 抽查几个日期的成员数
    probe = {}
    for d in ("2019-07-01", "2020-06-15", "2021-06-15", "2021-12-13", "2022-06-13", "2023-06-12", "2024-06-17", "2025-03-27",
              "2025-06-16", "2025-12-15", "2026-06-15", today_s):
        probe[d] = sum(1 for r in recs if r["ins"] and r["ins"] <= d and (r["out"] is None or r["out"] > d))
    rep["members_at"] = probe
    rep.update(dict(st))
    rows = []
    for r in recs:
        rows.append(dict(indexSymbol=ix["symbol"], indexCode=ix["code"], indexName=ix["name"], conSymbol=symbol_of(r["code"]), conCode=r["code"],
                         conName=r["name"], inDate=r["ins"], outDate=r["out"], inExact=r["in_exact"],
                         source=src + ("+" + r["src_extra"] if r.get("src_extra") else "")))
    rows.sort(key=lambda x: (x["conCode"], x["inDate"] or ""))
    cov = dict(indexSymbol=ix["symbol"], indexCode=ix["code"], indexName=ix["name"], publisher=ix["publisher"], nominalCount=ix["n"],
               pitFrom=pit_from, partialFrom=partial_from, pitTo=last, method=method_txt, source=src)
    report["index"][ix["symbol"]] = rep
    return rows, cov


def load_sw_names():
    import pandas as pd
    off = pd.read_excel(RAW / "sw_SwClassCode_2021.xls", dtype=str)
    n21 = {}
    for r in off.itertuples(index=False):
        n21[r[0]] = [x if isinstance(x, str) else None for x in r[1:4]]
    ts = rjson(RAW / "web" / "tinysoft_swhy.json", {})
    return n21, ts


def sw_levels(code, n21, ts, v2021):
    l1, l2 = code[:2] + "0000", code[:4] + "00"
    if v2021 and code in n21:
        a = n21[code]
        return l1, a[0], l2, a[1], code, a[2]
    nm = lambda c: ts.get(c, {}).get("name")  # noqa: E731
    return l1, nm(l1), l2, nm(l2), code, nm(code)


def build_sw(report):
    import pandas as pd
    df = pd.read_excel(RAW / "sw_StockClassifyUse_stock.xls", dtype=str)
    df.columns = ["code", "start", "ind", "upd"]
    df["code"] = df["code"].str.zfill(6)
    df["d"] = df["start"].str[:10]
    n21, ts = load_sw_names()
    rows, miss_name = [], Counter()
    for code, g in df.sort_values(["code", "d", "upd"]).groupby("code"):
        g = g.drop_duplicates("d", keep="last")
        recs = list(g.itertuples(index=False))
        for i, r in enumerate(recs):
            v = "SW2021" if r.d >= SW2021_FROM else ("SW2014" if r.d >= SW2014_FROM else "SW_OLD")
            l1, l1n, l2, l2n, l3, l3n = sw_levels(r.ind, n21, ts, v == "SW2021")
            if not (l1n and l2n and l3n):
                miss_name[v] += 1
            rows.append(dict(symbol=symbol_of(code), code=code, classification="SW", version=v, indCode=r.ind, l1Code=l1, l1Name=l1n,
                             l2Code=l2, l2Name=l2n, l3Code=l3, l3Name=l3n, inDate=r.d, outDate=recs[i + 1].d if i + 1 < len(recs) else None,
                             inExact=1, source="swsresearch"))
    report["industry"]["sw"] = dict(raw_rows=len(df), stocks=df["code"].nunique(), rows=len(rows), name_missing_by_version=dict(miss_name),
                                    by_version=dict(Counter(r["version"] for r in rows)))
    return rows


CSRC_RE = re.compile(r"^([A-S])(\d{2})(.*)$")


def build_csrc(report):
    snaps = {}
    for f in sorted((RAW / "bs_industry").glob("*.json")):
        j = rjson(f)
        if not j or not j["rows"]:
            continue
        up = max(j["updateDates"])
        snaps[up] = {r[1].split(".")[1]: r[3] for r in j["rows"]}
    snaps = sorted(snaps.items())
    rows, open_ = [], {}
    for i, (d, mem) in enumerate(snaps):
        for c in list(open_):
            if mem.get(c, "") != open_[c]["ind"]:
                r = open_.pop(c)
                r["outDate"] = d
                rows.append(r)
        for c, ind in mem.items():
            if not ind or c in open_:
                continue
            m = CSRC_RE.match(ind)
            l1 = m.group(1) if m else None
            open_[c] = dict(symbol=symbol_of(c), code=c, classification="CSRC", version="CSRC2012", indCode=(m.group(1) + m.group(2)) if m else ind,
                            l1Code=l1, l1Name=CSRC_L1.get(l1), l2Code=(m.group(1) + m.group(2)) if m else None, l2Name=m.group(3) if m else ind,
                            l3Code=None, l3Name=None, inDate=d, outDate=None, inExact=1 if i else 0, source="baostock", ind=ind)
    rows += list(open_.values())
    for r in rows:
        r.pop("ind", None)
    report["industry"]["csrc"] = dict(snapshots=len(snaps), first=snaps[0][0] if snaps else None, last=snaps[-1][0] if snaps else None,
                                      stocks=len({r["code"] for r in rows}), rows=len(rows))
    return rows


def hs300_md_check(cons_rows, report):
    """md/hs300/hs300-2025-03-27.md(用户手工整理: 自定义类别+城市) vs 时点表 2025-03-27 成分 / baostock 当周快照"""
    if not HS300_MD.exists():
        report["hs300_md"] = "文件不存在"
        return
    txt = HS300_MD.read_text(encoding="utf-8")
    items, md = [], {}
    group = None
    for line in txt.splitlines():     # 表格行: | 类别 | 数量 | 名称(代码)(城市), ... | 主营行业 |; **粗体**行=大类
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].startswith("**"):
            group = cells[0].strip("*")
            continue
        for n, c, city in re.findall(r"([^,，|()]+?)\((\d{6})\)\(([^)]*)\)", cells[2]):
            items.append((n, c, city))
            md.setdefault(c, (n.strip(), city, group, cells[0], cells[3]))
    D = "2025-03-27"
    pit = {r["conCode"]: r["conName"] for r in cons_rows if r["indexSymbol"] == "sh000300" and r["inDate"] <= D and (r["outDate"] is None or r["outDate"] > D)}
    j = rjson(RAW / "bs" / "000300" / "2025-03-24.json")
    bsw = {r[1].split(".")[1] for r in j["rows"]} if j else set()
    # md 的自定义类别/城市不进时点表, 原样落 jsonl 备查(删 md 前的留底)
    snap = [dict(indexSymbol="sh000300", snapDate=D, conCode=c, conSymbol=symbol_of(c), conName=v[0], city=v[1], group=v[2], category=v[3],
                 mainBusiness=v[4]) for c, v in sorted(md.items())]
    with open(OUT / "hs300_md_20250327.jsonl", "w", encoding="utf-8") as fh:
        for s in snap:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    report["hs300_md"] = dict(md_items=len(items), md_unique=len(md), pit_count=len(pit), bs_week_count=len(bsw),
                              md_minus_pit=sorted(set(md) - set(pit)), pit_minus_md=sorted(set(pit) - set(md)),
                              md_minus_bs=sorted(set(md) - bsw), bs_minus_md=sorted(bsw - set(md)),
                              dup_in_md=sorted(c for c, k in Counter(c for _, c, _ in items).items() if k > 1))


def industry_coverage(sw_rows, csrc_rows, report):
    """行情库(只读)各抽查日在交易的 A 股, 有申万/证监会行业的比例"""
    try:
        from kline_db import db
        conn = db()
    except Exception as e:  # noqa: BLE001
        report["industry"]["coverage"] = f"连不上行情库, 跳过覆盖率: {e}"
        return
    def idx(rows):
        m = defaultdict(list)
        for r in rows:
            m[r["symbol"]].append((r["inDate"], r["outDate"], r.get("l1Name")))
        return m
    sw, cs = idx(sw_rows), idx(csrc_rows)
    hit = lambda m, s, d: any(a <= d and (b is None or b > d) for a, b, _ in m.get(s, []))  # noqa: E731
    cov = {}
    try:
        cur = conn.cursor()
        for d in ("2019-07-01", "2020-07-01", "2021-07-01", "2022-07-01", "2023-07-03", "2024-07-01", "2025-07-01", "2026-10-16"):
            cur.execute("select k.symbol from kline_day k join security_master s on s.symbol=k.symbol and s.sec_type='STOCK' "
                        "where k.trade_date=(select min(trade_date) from kline_day where symbol='sh000001' and trade_date>=%s) "
                        "and k.symbol regexp '^(sh|sz|bj)'", (d,))
            syms = [x[0] for x in cur.fetchall()]
            a = sum(hit(sw, s, d) for s in syms)
            b = sum(hit(sw, s, d) or hit(cs, s, d) for s in syms)
            miss = [s for s in syms if not (hit(sw, s, d) or hit(cs, s, d))]
            cov[d] = dict(stocks=len(syms), sw=a, sw_pct=round(a / max(len(syms), 1) * 100, 2), sw_or_csrc=b,
                          any_pct=round(b / max(len(syms), 1) * 100, 2), missing_sample=miss[:10],
                          missing_by_board=dict(Counter(s[:2] + ("68" if s.startswith("sh68") else s[2] if s[2] in "03" else "") for s in miss)))
    finally:
        conn.close()
    report["industry"]["coverage"] = cov


def cmd_build(a):
    today = dt.date.today()
    report = {"built_at": dt.datetime.now().isoformat(timespec="seconds"), "index": {}, "industry": {}}
    cons, covs = [], []
    built = {}
    for ix in INDEXES:
        try:
            r, c = build_index(ix, today, report, built)
            built[ix["symbol"]] = r
            cons += r
            covs.append(c)
        except Exception as e:  # noqa: BLE001
            report["index"][ix["symbol"]] = f"FAIL {e}"
            print(f"[FAIL] {ix['name']}: {e}", flush=True)
    sw = build_sw(report)
    csrc = build_csrc(report) if (RAW / "bs_industry").exists() else []
    hs300_md_check(cons, report)
    industry_coverage(sw, csrc, report)
    for name, rows in (("index_constituent", cons), ("index_constituent_coverage", covs), ("stock_industry", sw + csrc)):
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{name}.jsonl: {len(rows)} 行", flush=True)
    wjson(OUT / "build_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])
    return 0


# ----------------------------------------------------------------------------------------------------------------- import
TABLES = {
    "index_constituent": ["index_symbol", "index_code", "index_name", "con_symbol", "con_code", "con_name", "in_date", "out_date", "in_exact", "source"],
    "index_constituent_coverage": ["index_symbol", "index_code", "index_name", "publisher", "nominal_count", "pit_from", "partial_from", "pit_to",
                                   "method", "source"],
    "stock_industry": ["symbol", "code", "classification", "version", "ind_code", "l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name",
                       "in_date", "out_date", "in_exact", "source"],
}


def camel(s):
    p = s.split("_")
    return p[0] + "".join(x.title() for x in p[1:])


NATURAL_KEY = {"index_constituent": ["index_symbol", "con_symbol", "in_date"], "index_constituent_coverage": ["index_symbol"],
               "stock_industry": ["symbol", "classification", "version", "ind_code", "in_date"]}


def _norm(v):
    return None if v is None or v == "" else str(v)[:10] if isinstance(v, (dt.date, dt.datetime)) else str(v)


FROZEN = {}   # 10/17 晚: 增量导入时因软删占比过高被冻结(不动)的分组 {表: [分组]}


def import_incremental(conn, data, now):
    """10/17 A7: 增量写(见文件头); 返回 {表: (增, 改, 删)}"""
    out = {}
    cur = conn.cursor()
    for t, cols in TABLES.items():
        kc = NATURAL_KEY[t]
        cur.execute(f"select id,{','.join(cols)} from {t} where is_deleted=0")
        have = {}
        for row in cur.fetchall():
            rec = dict(zip(cols, row[1:]))
            have[tuple(_norm(rec[c]) for c in kc)] = (row[0], rec)
        ins, upd, seen = [], [], set()
        for r in data[t]:
            new = {c: r.get(camel(c)) for c in cols}
            k = tuple(_norm(new[c]) for c in kc)
            if k in seen:
                continue
            seen.add(k)
            if k not in have:
                ins.append(tuple(new[c] for c in cols) + (0, 1, now, 0))
                continue
            rid, old = have[k]
            diff = [c for c in cols if c not in kc and _norm(old[c]) != _norm(new[c])]
            if diff:
                upd.append((rid, {c: new[c] for c in diff}))
        dels = [rid for k, (rid, _) in have.items() if k not in seen]
        # 10/17 事故护栏: 某个指数整段消失(=源站坏了/缓存是错误页)时不要静默软删 —— 单指数软删超过其现有行数的 20% 直接中止整个事务
        # 分组: 指数表按指数; 行业表按分类口径(SW/CSRC + 版本)——按单只股票分组时一只票只有 3~6 行, 精修 1 行就超 20% 会误拦(审计中-4)
        grp = (lambda r: r.get("index_symbol") or "-") if t != "stock_industry" else (lambda r: f"{r.get('classification')}/{r.get('version')}")
        by_ix = {}
        for k, (rid, rec) in have.items():
            by_ix.setdefault(grp(rec), [0, 0])[0] += 1
        for k, (rid, rec) in have.items():
            if k not in seen:
                by_ix[grp(rec)][1] += 1
        bad = {ix: (v[1], v[0]) for ix, v in by_ix.items() if (v[0] >= 20 and v[1] > 0.2 * v[0]) or (v[0] and v[1] == v[0])}   # 整组消失(含覆盖表这种每指数 1 行的小组)也冻结
        if bad:
            # 10/17 晚 审计(台账 Top-1): 原来整个事务中止 → 国证一个源坏了, 其他指数也永远更新不了。
            #   改成"冻结"这些分组: 该组的增/改/删一律不做(库里保持原样), 其余分组照常写; 返回值标出冻结组, 调用方按告警(exit 4)处理
            print(f"WARN {t}: 这些分组软删占比 >20%, 本次冻结不动(多半是源站/缓存坏了, 查 fetch 日志): {bad}")
            ins = [x for x in ins if grp(dict(zip(cols, x))) not in bad]
            rec_of = {rid: rec for rid, rec in have.values()}
            upd = [(rid, ch) for rid, ch in upd if grp(rec_of[rid]) not in bad]
            dels = [rid for k, (rid, rec) in have.items() if k not in seen and grp(rec) not in bad]
            FROZEN.setdefault(t, []).extend(sorted(bad))
        allc = cols + ["status", "create_by", "create_time", "is_deleted"]
        for i in range(0, len(ins), 1000):
            cur.executemany(f"insert into {t} ({','.join(allc)}) values ({','.join(['%s'] * len(allc))})", ins[i:i + 1000])
        for rid, ch in upd:
            cur.execute(f"update {t} set {','.join(f'{c}=%s' for c in ch)}, update_by=1, update_time=%s where id=%s", (*ch.values(), now, rid))
        for i in range(0, len(dels), 1000):
            part = dels[i:i + 1000]
            cur.execute(f"update {t} set is_deleted=1, delete_by=1, delete_time=%s, remark='增量导入: 新 build 无此区间(被精修替换)' where id in ({','.join(['%s'] * len(part))})", (now, *part))
        out[t] = (len(ins), len(upd), len(dels))
        print(f"{t}: 增 {len(ins)} / 改 {len(upd)} / 软删 {len(dels)}(库里原有效 {len(have)} 行)")
    return out


def cmd_import(a):
    data = {}
    for t in TABLES:
        f = OUT / f"{t}.jsonl"
        if not f.exists():
            print(f"缺 {f}, 先 build")
            return 1
        data[t] = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    for t, rows in data.items():
        print(f"== {t}: 将插入 {len(rows)} 行")
        key = {"index_constituent": "indexSymbol", "index_constituent_coverage": "indexSymbol", "stock_industry": "classification"}[t]
        for k, n in sorted(Counter(r[key] for r in rows).items()):
            print(f"   {key}={k}: {n}")
        for r in rows[:2] + rows[-1:]:
            print("   样例", json.dumps({c: r.get(camel(c)) for c in TABLES[t]}, ensure_ascii=False))
    if not a.commit:
        print("dry-run: 未写库(加 --commit 写; 须先执行 sql/todo/index_constituent_industry_20261016.sql 建表)")
        return 0
    from kline_db import db
    conn = db()
    now = dt.datetime.now()
    try:
        cur = conn.cursor()
        cur.execute("show tables")
        have = {x[0] for x in cur.fetchall()}
        lack = [t for t in TABLES if t not in have]
        if lack:
            print(f"表不存在 {lack}, 先执行 DDL")
            return 1
        if getattr(a, "incremental", False):
            import_incremental(conn, data, now)
            conn.commit()
            return 4 if FROZEN else 0
        for t, cols in TABLES.items():
            allc = cols + ["status", "create_by", "create_time", "is_deleted"]
            sql = f"insert into {t} ({','.join(allc)}) values ({','.join(['%s'] * len(allc))})"
            vals = [tuple(r.get(camel(c)) for c in cols) + (0, 1, now, 0) for r in data[t]]
            cur.execute(f"delete from {t}")   # 新表整表重建(只本脚本写)
            for i in range(0, len(vals), 1000):
                cur.executemany(sql, vals[i:i + 1000])
            print(f"{t}: 插入 {len(vals)} 行")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("fetch")
    f.add_argument("--only", default=None)
    f.add_argument("--from", dest="beg", default="2019-01-07")
    f.add_argument("--refresh", action="store_true", help="删国证/中证/新浪当前名单缓存后重抓(调样生效后用)")
    f.add_argument("--index", default=None, help="只抓这些指数代码(逗号分隔), 例 000905")
    sp.add_parser("build")
    i = sp.add_parser("import")
    i.add_argument("--commit", action="store_true")
    i.add_argument("--incremental", action="store_true", help="10/17 A7: 按自然键增/改/软删, 不整表重建(定时任务用)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    return {"fetch": cmd_fetch, "build": cmd_build, "import": cmd_import}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
