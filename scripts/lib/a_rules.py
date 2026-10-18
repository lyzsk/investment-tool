# -*- coding: utf-8 -*-
"""a_rules.py — A 股交易规则统一模块(2026-10-16 建; 与 a_rules.mjs 同口径, 共用样例 a_rules_cases.json 互相对照)

规则出处与生效日期见 docs/rules/a_share_trading_rules.md(每条标"已核实/待核实")。本模块只管"规则", 不取行情、不写库。
历史回放必须传 date(按当日规则); date=None 视为今天。

接口(价格/数量一律按交易所口径; 比例=小数):
    board(code)                       → MAIN/GEM/STAR/BSE/CB/ETF/LOF/REITS/INDEX/REPO/BSHARE/HK/OTHER
    limit_band(code, date, ...)       → (涨幅, 跌幅) 小数; 无涨跌幅限制 → None(转债首日/核准制新股首日 涨跌不对称)
    limit_pct(code, date, ...)        → 涨幅小数(对称时=跌幅); 无限制 → None
    limit_prices(code, date, prev_close, ...) → (涨停价, 跌停价), 四舍五入到最小价位; 无限制 → (None, None)
    at_limit_up(code, date, prev_close, price, ...) / at_limit_down(...)
    price_cage(code, date, side, base) → 连续竞价有效申报价上限(买)/下限(卖); 无笼子 → None
    tick(code) / price_decimals(code)
    lot_rule(code) → {min, step, max_limit, max_market, unit}; valid_qty(code, qty, side, held) / round_qty(code, qty)
    is_t0(code, name)                 → 当日回转(T+0)品种
    volume_unit(source, code)         → 源成交量 × 该倍数 = 股/份(转债=张)
    fees(side, amount, code, date, commission_rate, min_commission) → {commission, stamp, transfer, handling, total}
    sessions(date, code)              → 当日各交易阶段 [(阶段, 起, 止, 可撤单)]; phase_at(code, date, "HH:MM:SS")
    listing_day(code, date, list_date) → 上市第几个交易日(1=首日), 未知 → None
ST/上市日: 参数优先(is_st / name / list_date / listing_day); 都没给时 Python 版可从行情库 security_master 只读补(lookup=True),
    注意 security_master 的 is_st/name 是"当前"状态——回放 2026-07-06 前主板 ST(5%) 时以当时成交记录里的名称为准。
CLI: python a_rules.py --selftest  (含与 a_rules.mjs 的逐例对照; 子进程 CREATE_NO_WINDOW)
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).resolve().parent / "a_rules_cases.json"
CAL_FILE = ROOT / "downloads" / "quotes" / "daily" / "1_000001.json"   # 上证指数日线归档 = 交易日历
HOLIDAY_DIR = ROOT / "inv-common" / "src" / "main" / "resources" / "holiday"

# ---------------- 生效日期(出处见规则文档) ----------------
D_STAR_OPEN = "2019-07-22"       # 科创板开市: 20%, 新股前 5 日无限制, 2% 价格笼子, 200 股起
D_GEM_REG = "2020-08-24"         # 创业板注册制: 20%(含 ST), 新股前 5 日无限制, 2% 笼子(超笼暂存)
D_BSE_OPEN = "2021-11-15"        # 北交所开市: 30%, 新股首日无限制, 5%/10 档笼子
D_TRANSFER_FEE_HALF = "2022-04-29"   # 中国结算过户费 0.02‰(北京 0.025‰) → 0.01‰ 双向
D_CB_RULE = "2022-08-01"         # 沪深可转债交易实施细则: 首日 +57.3%/-43.3%, 次日起 ±20%(此前无涨跌幅限制)
D_MAIN_REG = "2023-04-10"        # 主板注册制首批上市日: 主板新股前 5 日无限制; 主板/创业板笼子 2%+10 档、超笼即拒
D_STAMP_HALF = "2023-08-28"      # 印花税减半 0.1% → 0.05%(卖方); 同日沪深经手费 0.00487% → 0.00341%, 北交所 0.025% → 0.0125%
D_RULES_2026 = "2026-07-06"      # 沪深北交易规则 2026 修订施行: 主板 ST 5% → 10%; 盘后固定价格扩至全部 A 股+ETF(北交所另行通知); 沪市基金收盘集合竞价

STOCK_BOARDS = ("MAIN", "GEM", "STAR", "BSE")
FUND_BOARDS = ("ETF", "LOF", "REITS")


# ---------------- 代码 / 日期 归一 ----------------
def norm(code):
    """'600000' / 'sh600000' / '600000.SH' / 600000 → (交易所 sh|sz|bj|hk|None, 代码)"""
    s = str(code).strip()
    m = re.fullmatch(r"(?i)(sh|sz|bj|hk)\.?(\d{5,6})", s) or re.fullmatch(r"(?i)(\d{5,6})\.(sh|sz|bj|hk|ss)", s)
    if m:
        a, b = m.groups()
        ex, c = (a.lower(), b) if a.isalpha() else (b.lower(), a)
        return ("sh" if ex == "ss" else ex), c
    if re.fullmatch(r"\d{5}", s):
        return "hk", s
    if re.fullmatch(r"\d{1,6}", s):
        s = s.zfill(6)
        if s.startswith(("4", "8", "92")):
            return "bj", s
        if s.startswith(("6", "900", "5", "11", "204")):
            return "sh", s
        return "sz", s
    return None, s


def symbol(code):
    ex, c = norm(code)
    return f"{ex}{c}" if ex else c


def ndate(d=None):
    """None → 今天; date/datetime/'2026-10-16'/'20261016' → 'YYYY-MM-DD'"""
    if d is None:
        return dt.date.today().isoformat()
    if isinstance(d, dt.datetime):
        return d.date().isoformat()
    if isinstance(d, dt.date):
        return d.isoformat()
    s = str(d).strip()[:10]
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def board(code):
    ex, c = norm(code)
    if ex == "hk":
        return "HK"
    if ex == "bj":
        return "INDEX" if c.startswith("899") else "BSE"
    if ex == "sh":
        if c.startswith("000"):
            return "INDEX"
        if c.startswith(("600", "601", "603", "605")):
            return "MAIN"
        if c.startswith(("688", "689")):
            return "STAR"
        if c.startswith(("110", "111", "113", "118")):
            return "CB"
        if c.startswith("508"):
            return "REITS"
        if c.startswith(("501", "502", "506")):
            return "LOF"
        if c.startswith(("51", "52", "53", "56", "58")):
            return "ETF"
        if c.startswith("900"):
            return "BSHARE"
        if c.startswith("204"):
            return "REPO"
        return "OTHER"
    if ex == "sz":
        if c.startswith(("000", "001", "002", "003", "004")):
            return "MAIN"
        if c.startswith(("300", "301", "302")):
            return "GEM"
        if c.startswith(("123", "127", "128")):
            return "CB"
        if c.startswith("159"):
            return "ETF"
        if c.startswith("16"):
            return "LOF"
        if c.startswith("180"):
            return "REITS"
        if c.startswith("399"):
            return "INDEX"
        if c.startswith("20"):
            return "BSHARE"
        if c.startswith("131"):
            return "REPO"
    return "OTHER"


BOARD_CN = {"MAIN": "沪深主板", "GEM": "创业板", "STAR": "科创板", "BSE": "北交所", "CB": "可转债", "ETF": "ETF", "LOF": "LOF",
            "REITS": "REITs", "INDEX": "指数", "REPO": "逆回购", "BSHARE": "B股", "HK": "港股", "OTHER": "其他"}


# ---------------- 名称信号 ----------------
def is_st_name(name):
    return bool(name) and "ST" in str(name).upper()


def is_delist_name(name):
    """退市整理期简称: 末尾"退"(如 XX退)"""
    return bool(name) and str(name).rstrip().endswith("退")


# 跟踪创业板/科创板(20% 档)的基金: 交易所公布名单; 无名单时按简称启发(待核实, 见文档)
_FUND20_RE = re.compile(r"科创|创业|双创|创成长|创50|创100|创蓝筹|创价值|创医药|创科技|创新能")
# T+0 基金(交易所规则 3.1.5: 债券/货币/黄金/商品期货/跨境 ETF 与跨境 LOF) —— 按简称启发
_T0_RE = re.compile(r"债|货币|现金|理财|快线|添益|日利|黄金|金ETF|上海金|白银|豆粕|有色|能源化工|商品|原油|油气|"
                    r"纳指|纳斯达克|标普|道琼斯|美国|美股|日经|日本|东证|德国|法国|欧洲|英国|恒生|港股|H股|香港|中概|海外|"
                    r"亚太|沙特|东南亚|越南|印度|巴西|QDII|全球|中韩|韩国|新兴|港美|恒指|恒科|港科|港中小|港红利|港消费|港医")


# ---------------- 交易日历 ----------------
_CAL = None


def trade_days():
    """上证指数日线归档的交易日序列(升序); 读不到 → []"""
    global _CAL
    if _CAL is None:
        try:
            _CAL = [k["d"] for k in json.loads(CAL_FILE.read_text(encoding="utf-8"))["klines"]]
        except (OSError, ValueError, KeyError):
            _CAL = []
    return _CAL


_HOL = {}


def _is_trade_day_fallback(d):
    """归档之后的日期: 周一~周五且不在法定假日表(holiday-cn: true=放假; 调休上班的周末交易所不开市)"""
    y = d[:4]
    if y not in _HOL:
        try:
            _HOL[y] = json.loads((HOLIDAY_DIR / f"{y}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _HOL[y] = {}
    return dt.date.fromisoformat(d).weekday() < 5 and _HOL[y].get(d) is not True


def count_trade_days(d0, d1):
    """[d0, d1] 闭区间交易日数(d0 > d1 → 0)"""
    import bisect
    d0, d1 = ndate(d0), ndate(d1)
    if d0 > d1:
        return 0
    cal = trade_days()
    last = cal[-1] if cal else "0000-00-00"
    n = 0
    if cal and d0 <= last:
        n += bisect.bisect_right(cal, min(d1, last)) - bisect.bisect_left(cal, d0)
    x = max(dt.date.fromisoformat(d0), dt.date.fromisoformat(last) + dt.timedelta(days=1)) if cal else dt.date.fromisoformat(d0)
    end = dt.date.fromisoformat(d1)
    while x <= end:
        n += _is_trade_day_fallback(x.isoformat())
        x += dt.timedelta(days=1)
    return n


# ---------------- security_master(只读, 懒加载, 仅 Python) ----------------
_SM = None


def sec_info(code):
    """行情库 security_master 一行: {name, is_st, list_date, sec_type, board_type}; 库不可用 → {}(当前状态, 非历史)"""
    global _SM
    if _SM is None:
        _SM = {}
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "quotes"))
            from kline_db import db   # 只读连接
            conn = db()
            try:
                cur = conn.cursor()
                cur.execute("select symbol, name, is_st, list_date, sec_type, board_type from security_master where is_deleted = 0")
                for s, nm, st, ld, sty, bty in cur.fetchall():
                    _SM[s] = {"name": nm, "is_st": None if st is None else bool(st), "list_date": ld.isoformat() if ld else None,
                              "sec_type": sty, "board_type": bty}
            finally:
                conn.close()
        except Exception as e:   # noqa: BLE001  库不可用不致命, 按参数/默认口径
            print(f"[a_rules] security_master 不可用, ST/上市日只按参数判断: {str(e)[:80]}", file=sys.stderr)
    return _SM.get(symbol(code), {})


def listing_day(code, date=None, list_date=None, name=None, lookup=True):
    """上市第几个交易日(1=首日); 未知 → None。名称 N 前缀=首日(注册制下 C 前缀=第 2~5 日, 返回 2 作"仍在 5 日内"的保守值)"""
    date = ndate(date)
    if list_date is None and lookup:
        list_date = sec_info(code).get("list_date")
    if list_date:
        ld = ndate(list_date)
        return count_trade_days(ld, date) if ld <= date else 0
    if name:
        n = str(name).strip()
        if n.startswith("N"):
            return 1
        if n.startswith("C") and board(code) in ("MAIN", "GEM", "STAR"):
            return 2
    return None


# ---------------- 涨跌幅 ----------------
def limit_band(code, date=None, name=None, list_date=None, is_st=None, listing_n=None, phase=None, lookup=True):
    """(涨幅, 跌幅) 小数; None=无价格涨跌幅限制。
    phase: '退市整理首日' / '重新上市首日' → 无限制(交易所规则 3.3.13/3.3.15/3.3.12); 名称"XX退"按退市整理期(非首日)处理
    listing_n: 上市第几个交易日(给了就不再查 list_date)"""
    b = board(code)
    date = ndate(date)
    if phase in ("退市整理首日", "重新上市首日"):
        return None if b in STOCK_BOARDS else _base_band(b, code, name, date, None)
    if b in STOCK_BOARDS or b in ("CB", "REITS"):
        n = listing_n if listing_n is not None else listing_day(code, date, list_date, name, lookup)
    else:
        n = None
    if b in STOCK_BOARDS:
        if is_st is None:
            if name is not None:
                is_st = is_st_name(name)
            elif lookup:
                info = sec_info(code)
                is_st = bool(info.get("is_st")) if info.get("is_st") is not None else is_st_name(info.get("name"))
            else:
                is_st = False
        ld = ndate(list_date) if list_date else None
        if n is not None and n >= 1:
            if b == "BSE":
                if n == 1:
                    return None
            elif b == "STAR":
                if n <= 5:
                    return None
            elif b == "GEM":
                if date >= D_GEM_REG and (ld is None or ld >= D_GEM_REG) and n <= 5:
                    return None
                if date < D_GEM_REG and n == 1:
                    return (0.44, 0.36)   # 核准制新股首日(待核实: 二手来源)
            else:   # MAIN
                reg = (ld >= D_MAIN_REG) if ld else (date >= D_MAIN_REG)
                if reg and n <= 5:
                    return None
                if not reg and n == 1:
                    return (0.44, 0.36)   # 核准制主板新股首日: 发行价 144%/64%(待核实: 二手来源)
        return _stock_band(b, date, is_st, name)
    if b == "CB":
        if date < D_CB_RULE:
            return None                    # 2022-08-01 前转债无涨跌幅限制(只有盘中临停)
        if n == 1:
            return (0.573, 0.433)          # 首日以发行价为前收
        return (0.20, 0.20)
    if b == "REITS":
        return (0.30, 0.30) if n == 1 else (0.10, 0.10)
    return _base_band(b, code, name, date, n)


def _stock_band(b, date, is_st, name):
    if b == "BSE":
        return (0.30, 0.30)
    if b == "STAR":
        return (0.20, 0.20)
    if b == "GEM":
        if date >= D_GEM_REG:
            return (0.20, 0.20)
        return (0.05, 0.05) if is_st else (0.10, 0.10)
    # MAIN
    if is_delist_name(name):
        return (0.10, 0.10)                # 退市整理股票(非首日)一直是 10%
    if is_st and date < D_RULES_2026:
        return (0.05, 0.05)
    return (0.10, 0.10)


def _base_band(b, code, name, date, n):
    if b in ("ETF", "LOF"):
        _ex, c = norm(code)
        if (b == "ETF" and c.startswith(("588", "589"))) or (name and _FUND20_RE.search(str(name))):
            return (0.20, 0.20)
        return (0.10, 0.10)
    if b == "REITS":
        return (0.30, 0.30) if n == 1 else (0.10, 0.10)
    if b == "BSHARE":
        return (0.10, 0.10)
    return None   # 指数/港股/逆回购/其他: 不适用


def limit_pct(code, date=None, name=None, list_date=None, is_st=None, **kw):
    band = limit_band(code, date, name, list_date, is_st, **kw)
    return None if band is None else band[0]


# ---------------- 价位 ----------------
def tick(code):
    b = board(code)
    if b in ("CB", "ETF", "LOF", "REITS"):
        return 0.001
    if b == "BSHARE" and norm(code)[0] == "sh":
        return 0.001   # 沪 B 美元
    return 0.01


def price_decimals(code):
    return 3 if tick(code) < 0.005 else 2


def _ticki(code):
    return 100000 if tick(code) < 0.005 else 1000000    # 以 1e-8 元为单位


def _round_half_up(xi, ti):
    """xi: 1e-8 元整数(≥0), ti: 价位(1e-8 元整数) → 四舍五入到价位(1e-8 元整数)"""
    return (xi + ti // 2) // ti * ti


def _px(v, code):
    return round(v / 1e8, price_decimals(code))


def limit_prices(code, date=None, prev_close=None, name=None, list_date=None, is_st=None, **kw):
    """(涨停价, 跌停价)。计算: 前收×(1±比例) 四舍五入至最小价位; 与前收之差 < 1 个价位 → 前收±1 价位; 跌停 < 1 价位 → 1 价位(规则 3.3.17/3.3.19)"""
    if not prev_close or prev_close <= 0:
        return None, None
    band = limit_band(code, date, name, list_date, is_st, **kw)
    if band is None:
        return None, None
    ti = _ticki(code)
    p4 = int(round(float(prev_close) * 10000))                     # 价格最多 3 位小数 → 1e-4 元整数精确; 乘比例(1e-4)后=1e-8 元整数
    pi = p4 * 10000
    upi = _round_half_up(p4 * (10000 + int(round(band[0] * 10000))), ti)
    dni = _round_half_up(p4 * (10000 - int(round(band[1] * 10000))), ti)
    if upi - pi < ti:
        upi = pi + ti
    if pi - dni < ti:
        dni = pi - ti
    if dni < ti:
        dni = ti
    return _px(upi, code), _px(dni, code)


def at_limit_up(code, date, prev_close, price, **kw):
    up, _ = limit_prices(code, date, prev_close, **kw)
    return up is not None and price is not None and price >= up - tick(code) / 2


def at_limit_down(code, date, prev_close, price, **kw):
    _, dn = limit_prices(code, date, prev_close, **kw)
    return dn is not None and price is not None and price <= dn + tick(code) / 2


def price_cage(code, date=None, side="BUY", base=None, listing_n=None):
    """连续竞价限价申报有效价上限(买)/下限(卖); 基准价=对手方最优价→本方最优价→最新成交价→前收(调用方给)。无笼子 → None。
    主板/创业板(2023-04-10 起): 买 ≤ max(基准×102%, 基准+10 价位), 卖 ≥ min(基准×98%, 基准-10 价位);
    创业板 2020-08-24~2023-04-09 与科创板: 只有 2%; 北交所: 5% 与 10 价位孰宽; 转债仅上市首日有(沪: 对手最优价 ±10%; 深: 最近成交价 ±10%)。
    超出笼子=无效申报(拒单); 例外: 创业板 2020-08-24~2023-04-09 超笼暂存主机、进入范围后自动参与竞价"""
    if not base or base <= 0:
        return None
    b, date = board(code), ndate(date)
    ti = _ticki(code)
    bi = int(round(float(base) * 10000)) * 10000
    buy = str(side).upper().startswith("B")

    def pct_tick(p, k):
        if buy:
            a = _round_half_up(int(round(float(base) * 10000)) * (10000 + int(p * 10000)), ti)
            return _px(max(a, bi + k * ti), code)
        a = _round_half_up(int(round(float(base) * 10000)) * (10000 - int(p * 10000)), ti)
        return _px(min(a, bi - k * ti), code)
    if b == "STAR" and date >= D_STAR_OPEN:
        return pct_tick(0.02, 0)
    if b == "GEM":
        if date >= D_MAIN_REG:
            return pct_tick(0.02, 10)
        if date >= D_GEM_REG:
            return pct_tick(0.02, 0)
        return None
    if b == "MAIN" and date >= D_MAIN_REG:
        return pct_tick(0.02, 10)
    if b == "BSE":
        return pct_tick(0.05, 10)
    if b == "CB" and date >= D_CB_RULE and listing_n == 1:
        return pct_tick(0.10, 0)
    return None


def cage_reject(code, date=None):
    """超笼处理: True=无效申报直接拒; False=暂存主机(创业板 2020-08-24~2023-04-09)"""
    return not (board(code) == "GEM" and D_GEM_REG <= ndate(date) < D_MAIN_REG)


# ---------------- 申报数量 ----------------
def lot_rule(code):
    b = board(code)
    if b == "STAR":
        return {"min": 200, "step": 1, "max_limit": 100000, "max_market": 50000, "unit": "股"}
    if b == "BSE":
        return {"min": 100, "step": 1, "max_limit": 1000000, "max_market": 1000000, "unit": "股"}
    if b == "GEM":
        return {"min": 100, "step": 100, "max_limit": 300000, "max_market": 150000, "unit": "股"}
    if b == "CB":
        return {"min": 10, "step": 10, "max_limit": 1000000, "max_market": 1000000, "unit": "张"}   # 1000 元面额=10 张, 单笔 ≤1 亿元面额
    if b in FUND_BOARDS:
        return {"min": 100, "step": 100, "max_limit": 1000000, "max_market": 1000000, "unit": "份"}
    return {"min": 100, "step": 100, "max_limit": 1000000, "max_market": 1000000, "unit": "股"}


def valid_qty(code, qty, side="BUY", held=None, market=False):
    """(是否合法, 原因)。卖出: 余额不足最小申报数量的部分须一次性卖出(qty == held 合法)"""
    r = lot_rule(code)
    q = int(qty) if qty == int(qty) else None
    if not q or q <= 0:
        return False, "数量须为正整数"
    mx = r["max_market"] if market else r["max_limit"]
    if q > mx:
        return False, f"单笔上限 {mx}{r['unit']}"
    sell = str(side).upper().startswith("S")
    if sell and held is not None:
        h = int(held)
        if q > h:
            return False, "超过持仓"
        if q == h:
            return True, "清仓(含零股一次性卖出)"
        if r["step"] == r["min"] and q % r["step"] == h % r["step"]:
            return True, "零股部分一次性卖出"
    if q < r["min"]:
        return False, f"不足最小申报 {r['min']}{r['unit']}"
    if (q - r["min"]) % r["step"]:
        return False, f"须为 {r['min']}{r['unit']} 起、{r['step']}{r['unit']} 递增" if r["step"] != r["min"] else f"须为 {r['step']}{r['unit']} 整数倍"
    return True, ""


def round_qty(code, qty):
    """向下取到合法买入数量(不足最小申报 → 0)"""
    r = lot_rule(code)
    q = int(qty)
    if q < r["min"]:
        return 0
    return min(r["max_limit"], r["min"] + (q - r["min"]) // r["step"] * r["step"])


# ---------------- T+0 ----------------
def is_t0(code, name=None):
    """当日回转: 可转债; 债券/货币/黄金/商品期货/跨境 ETF 与跨境 LOF(规则 3.1.5)。股票/普通 ETF=T+1。
    基金按代码段(沪 511 债券货币/518 黄金/513 跨境)+简称启发判断; 判不了 → False(保守按 T+1)"""
    b = board(code)
    if b == "CB":
        return True
    if b in ("ETF", "LOF"):
        _ex, c = norm(code)
        if b == "ETF" and c.startswith(("511", "518", "513")):
            return True
        return bool(name and _T0_RE.search(str(name)))
    return False


# ---------------- 成交量单位 ----------------
# 源原始成交量 × 倍数 = 股/份(转债=张)。verified: 本地数据反推(成交额/成交量≈价)已核实的格子
_VOL = {
    "tencent_qt": {"default": 100, "STAR": 1, "CB": 10},       # qt.gtimg.cn f[6]: 手; 科创板=股(10/12-14 facts 快照反推已核实); 转债 1 手=10 张
    "tencent_kline": {"default": 100, "STAR": 1, "CB": 10},    # web.ifzq fqkline 日线: 同上(科创板=股, 10/16 晚 backfill_history 发现)
    "sina": {"default": 1, "INDEX_SH": 100},                   # 新浪 hq/行情中心: 股/份/张; 沪市指数给"手"
    "em": {"default": 100, "CB": 10},                          # 东财 push2/clist f5·f47/kline: 手; 科创板口径待核实(按手)
    "tdx": {"default": 100, "CB": 10},                         # 通达信 pytdx 逐笔/分钟: 手(科创板也是手, 10/15 分钟 vs 日线逐只核实)
    "db": {"default": 1},                                      # 行情库 kline_day/kline_minute: 已归一 股/份/张
    "tzzb": {"default": 1},                                    # 同花顺投资账本成交: 股/张
}
_VOL_ALIAS = {"tencent": "tencent_qt", "qt": "tencent_qt", "tencent_batch": "tencent_qt", "ifzq": "tencent_kline", "dfcf": "em",
              "eastmoney": "em", "em_push2": "em", "pytdx": "tdx", "tdx_mt": "tdx", "kline_day": "db", "market_db": "db"}


def volume_unit(source, code):
    src = _VOL_ALIAS.get(str(source).lower(), str(source).lower())
    t = _VOL.get(src)
    if t is None:
        raise ValueError(f"未知成交量源 {source}(已知: {sorted(_VOL)})")
    b = board(code)
    if b == "INDEX" and norm(code)[0] == "sh" and "INDEX_SH" in t:
        return t["INDEX_SH"]
    return t.get(b, t["default"])


# ---------------- 费用 ----------------
def fees(side, amount, code, date=None, commission_rate=0.00025, min_commission=5.0, include_handling=False):
    """单笔费用(元)。印花税: 股票卖方 0.05%(2023-08-28 起; 此前 0.1%), 基金/转债免; 过户费: 沪深北 A 股双向 0.001%(2022-04-29 起),
    基金/转债不收; 佣金: 券商协议费率, 单笔最低 5 元(券商惯例, 非交易所规定; 参数化)。经手费/证管费一般含在佣金里, include_handling=True 才单列"""
    amount = float(amount)
    b, date = board(code), ndate(date)
    sell = str(side).upper().startswith("S")
    comm = max(float(min_commission), amount * float(commission_rate)) if amount > 0 else 0.0
    stamp = 0.0
    if sell and b in STOCK_BOARDS + ("BSHARE",):
        stamp = amount * (0.0005 if date >= D_STAMP_HALF else 0.001)
    transfer = 0.0
    if b in STOCK_BOARDS:
        if date >= D_TRANSFER_FEE_HALF:
            transfer = amount * 0.00001
        else:
            transfer = amount * (0.000025 if b == "BSE" else 0.00002)
    handling = 0.0
    if include_handling and b in STOCK_BOARDS:
        if b == "BSE":
            handling = amount * (0.000125 if date >= D_STAMP_HALF else 0.00025)
        else:
            handling = amount * (0.0000341 if date >= D_STAMP_HALF else 0.0000487)
    r2 = _r2
    return {"commission": r2(comm), "stamp": r2(stamp), "transfer": r2(transfer), "handling": r2(handling),
            "total": r2(r2(comm) + r2(stamp) + r2(transfer) + r2(handling))}


def _r2(x):
    """分位四舍五入(与 JS 同算法: floor(x*100+0.5+1e-9)/100, 避开 round() 的银行家舍入)"""
    import math
    return math.floor(x * 100 + 0.5 + 1e-9) / 100


# ---------------- 交易时段 ----------------
def sessions(date=None, code=None):
    """[(阶段, 起, 止, 可撤单)]; 非交易日 → []。阶段: 开盘集合竞价 / 连续竞价 / 收盘集合竞价 / 盘后固定价格。
    9:25~9:30 交易所不撮合(券商可收单暂存); 11:30~13:00 休市"""
    date = ndate(date)
    if not count_trade_days(date, date):
        return []
    b = board(code) if code else "MAIN"
    ex = norm(code)[0] if code else "sh"
    out = [("开盘集合竞价", "09:15:00", "09:20:00", True), ("开盘集合竞价", "09:20:00", "09:25:00", False),
           ("连续竞价", "09:30:00", "11:30:00", True)]
    if b == "CB" and ex == "sh":
        out.append(("连续竞价", "13:00:00", "15:00:00", True))          # 沪市转债无收盘集合竞价(收盘价=最后 1 分钟 VWAP)
    elif b in FUND_BOARDS and ex == "sh" and date < D_RULES_2026:
        out.append(("连续竞价", "13:00:00", "15:00:00", True))          # 2026-07-06 前沪市基金收盘阶段为连续竞价
    else:
        out += [("连续竞价", "13:00:00", "14:57:00", True), ("收盘集合竞价", "14:57:00", "15:00:00", False)]
    after = False
    if b == "STAR" and date >= D_STAR_OPEN:
        after = True
    elif b == "GEM" and date >= D_GEM_REG:
        after = True
    elif date >= D_RULES_2026 and (b in ("MAIN", "GEM", "STAR") or (b == "ETF")):
        after = True                                                       # 北交所盘后固定价格: 施行时间另行通知(待核实)
    if after:
        out.append(("盘后固定价格", "15:05:00", "15:30:00", True))
    return out


def phase_at(code, date, t):
    """'HH:MM:SS' → (阶段, 可撤单) ; 不在任何阶段 → (None, None)"""
    t = (str(t) + ":00")[:8] if len(str(t)) == 5 else str(t)[:8]
    for name, a, b, can in sessions(date, code):
        if a <= t < b or (t == b and b in ("11:30:00", "15:00:00") and name != "盘后固定价格"):   # 11:30/15:00 整点成交归本段
            return name, can
    return None, None


# ---------------- selftest ----------------
def _eval_case(c):
    fn, a = c["fn"], c["args"]
    if fn == "limit_prices":
        return list(limit_prices(a["code"], a.get("date"), a["prev_close"], name=a.get("name"), list_date=a.get("list_date"),
                                 is_st=a.get("is_st"), listing_n=a.get("listing_n"), lookup=False))
    if fn == "limit_band":
        r = limit_band(a["code"], a.get("date"), name=a.get("name"), list_date=a.get("list_date"), is_st=a.get("is_st"),
                       listing_n=a.get("listing_n"), phase=a.get("phase"), lookup=False)
        return None if r is None else [r[0], r[1]]
    if fn == "board":
        return board(a["code"])
    if fn == "tick":
        return tick(a["code"])
    if fn == "lot_rule":
        r = lot_rule(a["code"])
        return [r["min"], r["step"], r["max_limit"]]
    if fn == "valid_qty":
        return valid_qty(a["code"], a["qty"], a.get("side", "BUY"), a.get("held"))[0]
    if fn == "round_qty":
        return round_qty(a["code"], a["qty"])
    if fn == "is_t0":
        return is_t0(a["code"], a.get("name"))
    if fn == "volume_unit":
        return volume_unit(a["source"], a["code"])
    if fn == "fees":
        r = fees(a["side"], a["amount"], a["code"], a.get("date"), a.get("commission_rate", 0.00025), a.get("min_commission", 5.0))
        return [r["commission"], r["stamp"], r["transfer"], r["total"]]
    if fn == "price_cage":
        return price_cage(a["code"], a.get("date"), a["side"], a["base"], a.get("listing_n"))
    if fn == "sessions":
        return [list(x) for x in sessions(a["date"], a["code"])]
    if fn == "phase_at":
        return list(phase_at(a["code"], a["date"], a["t"]))
    if fn == "count_trade_days":
        return count_trade_days(a["d0"], a["d1"])
    raise ValueError(fn)


def selftest():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    ok = True
    py = []
    for c in cases:
        got = _eval_case(c)
        py.append(got)
        good = got == c["want"]
        ok &= good
        print(("PASS " if good else "FAIL ") + c["id"] + ("" if good else f"  got={got} want={c['want']}"))
    # 与 a_rules.mjs 逐例对照(同一份样例, 两边输出必须逐位相同)
    import shutil
    import subprocess
    node = shutil.which("node")
    if node:
        flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
        p = subprocess.run([node, str(Path(__file__).with_name("a_rules.mjs")), "--dump"], capture_output=True, text=True, encoding="utf-8",
                           creationflags=flags, timeout=60)
        if p.returncode != 0:
            print("FAIL JS 对照: a_rules.mjs --dump 退出码", p.returncode, p.stderr[:300])
            ok = False
        else:
            js = json.loads(p.stdout)
            diff = [(c["id"], a, b) for c, a, b in zip(cases, py, js) if a != b]
            for d in diff:
                print("FAIL PY≠JS", d)
            ok &= not diff and len(js) == len(py)
            print(f"{'PASS' if not diff else 'FAIL'} PY/JS 逐例对照 {len(py)} 例, 不一致 {len(diff)}")
    else:
        print("SKIP JS 对照: 找不到 node")
    print("A_RULES SELFTEST", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
