#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fmt_cli_reply.py — CLI 回复 → 微信友好格式(零 token, 纯规则; 10/19 正式版, 草稿备份在 scripts/temp/fmt_cli_reply.draft_1019.py)

为什么: hermes 把 Claude Code 的回复转到微信时常直接贴原文, 用户多次要求重排; 让 LLM 自觉排版不可靠 → 机械排。
规则来源: hermes skills/productivity/weixin-delivery/references/auto-push-reformat.md(emoji 分节 / 表 ≤5 列 / 异常前置 / 正常压一句)
          + SKILL.md 第 4 条(挂单: 📊状态 / 🔴B档(买, 红=买入的中国习惯) / 🟢S档 / 🔗配对 / ⚡改单条件, 触发价加粗; 10/19 用户改序)

输入(三选一):
  python fmt_cli_reply.py "原文"                    参数
  echo 原文 | python fmt_cli_reply.py              stdin
  python fmt_cli_reply.py --from-jsonl [--at 10:41] [--grep 关键词] [--session <jsonl>]
        拉 Claude Code 会话存档里最新(或 --at 本地时间之前最后一条、或含关键词)的一条长回复
其他: --kind order|report|forecast|generic 强制类型; --debug 打印每行的归类; --send 排好后 hermes 推微信
类型判断(不靠 LLM): 挂单 = 出现 ≥2 个"价+方向+量"单子(41.62B300 / 41.76 买 300 / 卖 42.22 300 / 表格里 41.80 × 300)或 挂单关键词 + ≥1 单;
                   日报 = 红黄绿 / OK / FAIL / 批次 / 对账 类词 ≥3; 预判 = 情景 / 概率 / 支撑 / 压力 ≥2; 其余兜底
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

# ================================================================ 输入
def from_jsonl(at=None, grep=None, session=None):
    files = [session] if session else sorted(glob.glob(os.path.expanduser(r"~\.claude\projects\C--Users-admin\*.jsonl")), key=os.path.getmtime)
    if not files:
        return None
    best = None
    with open(files[-1], "rb") as fh:
        fh.seek(0, 2)
        n = fh.tell()
        fh.seek(max(0, n - 6_000_000))
        tail = fh.read().decode("utf-8", "ignore")
    for ln in tail.splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        try:
            loc = dt.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
        except (KeyError, ValueError):
            continue
        if at and loc.strftime("%H:%M") > at:
            continue
        for b in (d.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text" and len(b.get("text", "")) > 120 and (not grep or grep in b["text"]):
                best = (loc, b["text"])
    return best


# ================================================================ 公共
MD = re.compile(r"\*\*|`|__")
P = r"(?<![\d.])(\d{1,3}\.\d{1,3})(?![\d.])"          # 价
PA = r"(?<![\d./])(\d{1,3}\.\d{1,3}(?:/\d{1,3}\.\d{1,3})?)(?![\d.])"   # 挂单里的价, 允许"41.36/41.40"(两个候选价, 原样进表)
Q = r"(\d{2,6})(?![\d.])\s*股?"                         # 量
TOKEN_RES = [   # (正则, 方向组, 价组, 量组)
    (re.compile(PA + r"\s*([SBsb])\s*" + Q), 2, 1, 3),                     # 41.62B300 / 41.36/41.40B400
    (re.compile(r"([SB])\s*" + PA + r"\s*[×xX*@]\s*" + Q), 1, 2, 3),       # B41.62×300
    (re.compile(r"(买|卖)(?:出|入)?\s*" + PA + r"\s*[×xX*@]?\s*" + Q), 1, 2, 3),   # 卖 42.22 300 / 买 41.62×300
    (re.compile(PA + r"\s*(买|卖)(?:出|入)?\s*" + Q), 2, 1, 3),             # 41.76 买 300
    (re.compile(PA + r"\s*[×xX*]\s*" + Q), None, 1, 2),                    # 41.80 × 300(方向看上下文)
]
SIDE = {"S": "S", "s": "S", "卖": "S", "B": "B", "b": "B", "买": "B"}
CANCEL = re.compile(r"撤(?!回)")
NEW = re.compile(r"新增|新挂|加挂|再挂|再加|补挂|加一档|新开")
KEEP = re.compile(r"保留|留着|留(?!意)|不动|不变|不降|照旧")
CHANGE = re.compile(r"→|->|改成|改为|改挂|改到|提到|降到|上移到|下移到|(?<!复核)改(?!单|动|口|了)")
CONDITIONAL = re.compile(r"成交后|成交了就|成了就|成后|卖成|买成|成交就|成交再")
TRIGGER = re.compile(r"强势|弱势|转弱|转强|再强|突破|站上|站稳|跌破|放量|若|如果|一旦|复查|收口|\b1[34]:\d\d\b|不追|不再往下|不再追|没成交|未成交|不成交|没成|成不了")
VERB = re.compile(r"就|则|→|撤|改|挂|不追|不再|不加|不补|不挂|过夜|你来定|收口|补齐|接回|买回|复查|再接|再补")
PAIRKW = re.compile(r"配对|保本线|净卖|净买|还差|全成交|全部成交|都成|全成|回到 ?\d{3,4}|你的账|对一下账")


def tokens(s):
    """抽 (起, 止, 方向|None, 价, 量); 不同正则命中重叠时取先命中、更长的"""
    hits = []
    for rx, gs, gp, gq in TOKEN_RES:
        for m in rx.finditer(s):
            hits.append((m.start(), m.end(), SIDE.get(m.group(gs)) if gs else None, m.group(gp), m.group(gq)))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, end = [], -1
    for h in hits:
        if h[0] >= end:
            out.append(h)
            end = h[1]
    return out


def clean(s):
    return MD.sub("", s).strip()


def shorten(s, n=20):
    """压到 ~n 字: 超出不多(≤4 字)就整句留着; 否则在 n 之前最后一个断句处切, 不切在数字 / 区间(41.41~41.50)中间"""
    s = re.sub(r"\s+", " ", s).strip(" ，,。;；:：、-—|·")
    if len(s) <= n + 4:
        return s
    cut = max((m.end() for m in re.finditer(r"[，,；;。、 ]", s[:n])), default=0)
    if cut < n // 2:
        cut = n - 1
        while cut > 0 and re.match(r"[\d.~/%-]", s[cut - 1]) and re.match(r"[\d.~/%-]", s[cut]):
            cut -= 1                 # 退到数字前
        if cut < n // 2:
            m = re.match(r"[\d.~/%-]+", s[n - 1:])
            cut = n - 1 + (m.end() if m else 0)   # 数字太靠前就把整个数字带上
    return s[:cut].rstrip(" ，,；;、") + "…"


def clean_inline(s):
    """短消息只去 md 记号(粗体 / 反引号 / 标题井号), 不重排"""
    s = MD.sub("", s)
    return re.sub(r"^#{1,4}\s*", "", s, flags=re.M).strip()


def table(rows, header):
    if not rows:
        return ""
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows])


def bold_prices(s):
    return re.sub(P, r"**\1**", s)


# ================================================================ 类型识别
KW_ORDER = re.compile(r"挂单|改单|买回|接回|卖单|买单|S档|B档|做T|反T|正T|保本线")
KW_REPORT = re.compile(r"日报|对账|批次|FAIL|OK=|红项|黄项|\[红\]|\[黄\]|\[绿\]|熔断|净值|拟人度|前三|后三|体检|自检")
KW_FORE = re.compile(r"预判|走势|情景|概率|支撑|压力|剧本")


def classify(t):
    # 代码块 / 反引号里的单子是"举例"(比如在讲排版器本身), 不算; 单子行占比太低(长篇进度汇报里顺带提一句价位)也不算挂单
    body = re.sub(r"`[^`\n]*`", "", re.sub(r"```[\s\S]*?```", "", t))
    lines = [clean(l) for l in body.splitlines() if l.strip()]
    tok_lines = [l for l in lines if tokens(l)]
    n_tok = sum(len(tokens(l)) for l in tok_lines)
    n_o, n_r, n_f = len(KW_ORDER.findall(body)), len(KW_REPORT.findall(body)), len(KW_FORE.findall(body))
    dense = len(tok_lines) >= 2 and len(tok_lines) / max(len(lines), 1) >= 0.12
    if (n_tok >= 2 and dense) or (n_o >= 2 and n_tok >= 1 and len(lines) <= 12):
        return "order"
    # 日报 = 至少 2 行以红 / 黄 / 绿 / ❌ / ✅ / FAIL / OK 这类状态标记开头(或表格第一格是状态), 光提到"日报""对账"不算
    st_lines = sum(bool(re.match(r"^\W{0,4}(\[?[红黄绿]\]?(?=\s|\||\])|❌|✅|⚠️|FAIL|OK\b)", l)) for l in lines)
    if st_lines >= 2 and n_r >= 2:
        return "report"
    if n_f >= 3 and re.search(r"预判|走势|情景|剧本", body):
        return "forecast"
    return "generic"


# ================================================================ 挂单
STATUS_RES = [("现", r"现价?\s*[:：]?\s*" + P), ("均价线", r"均价线\s*(?:约)?\s*" + P), ("今高", r"(?:今天)?最高\s*(?:只到|到)?\s*" + P),
              ("保本", r"保本线\s*[约≈:：]*\s*" + P), ("持仓", r"持仓\s*(?:应该是)?\s*\**\s*(\d{3,6})"), ("成本", r"成本\s*" + P)]


def units(text):
    """把原文切成"单元": 表格行 = 一单元(带表头上下文); 散文 = 一行; 同时跟踪当前小节标题(买回/卖出语境)"""
    head, ctx_side, out = "", None, []
    for raw in text.splitlines():
        l = clean(raw)
        if not l:
            continue
        if re.match(r"^\|?\s*:?-{2,}", l):
            continue
        is_head = bool(re.match(r"^#{1,4}\s", raw.strip())) or (raw.strip().startswith("**") and raw.strip().rstrip("：:").endswith("**"))
        if is_head:
            head = l.lstrip("# ").rstrip("：:")
            ctx_side = "B" if re.search(r"买回|接回|买单|补回", head) else ("S" if re.search(r"卖出|减仓|卖单", head) else None)
            out.append(("head", head, None, None))
            continue
        if l.startswith("|"):
            cells = [c.strip() for c in l.strip("|").split("|")]
            if not any(tokens(c) for c in cells) and not any(re.search(r"撤|留|改|新增", c) for c in cells):
                hs = "".join(cells)    # 表头: 记方向语境
                if re.search(r"买入价|买回|买单", hs):
                    ctx_side = "B"
                elif re.search(r"卖出价|卖单", hs):
                    ctx_side = "S"
                continue
            out.append(("row", cells, head, ctx_side))
        else:
            out.append(("line", l, head, ctx_side))
    return out


def side_near(s, pos, default):
    """token 前 12 字里最近的 买/卖/S/B 字样"""
    seg = s[max(0, pos - 12):pos]
    m = list(re.finditer(r"买|卖|(?<![A-Za-z])[SB](?![A-Za-z])", seg))
    return SIDE.get(m[-1].group(0)) if m else default


def act_of(s):
    if CANCEL.search(s):
        return "撤"
    if NEW.search(s):
        return "新增"
    if KEEP.search(s):
        return "留"
    return "挂"


def reason_of(s, n=20):
    s = re.sub(P + r"\s*[SBsb]\s*\d{2,6}", "", s)
    for rx, *_ in TOKEN_RES:
        s = rx.sub("", s)
    par = re.findall(r"[（(]([^）)]{4,})[）)]", s)
    main = re.sub(r"[（(][^）)]*[）)]", "", s)
    main = re.sub(r"改成|改为|改挂|改|撤掉?|新增|新挂|加挂|保留|留着|留|不动|现在的挂单|建议|[①-⑩]|→|->|\||(?<![一-龥])[买卖](?![一-龥])|\b和\b", " ", main)
    main = re.sub(r"^\W+", "", main.strip())
    main = main.replace("=", " ")
    cand = main if len(main.strip(" ，,。")) >= 4 and not (par and not re.search(r"\d", main)) else (par[0] if par else main)   # 正文没数字而括号里有说明 → 用括号
    # 压到 ~20 字: 去口水词 → 按逗号切子句 → 优先带数字的子句(数字=依据), 两句能放下就拼
    cand = re.sub(r"参照的是|过去|所以|就是|属于|用来|这笔|大约|在这里|的日子|日子|的", "", cand)
    cl = [c.strip() for c in re.split(r"[，,；;。：:]", cand) if len(c.strip()) >= 3]
    if not cl:
        return shorten(cand, n)
    dig = [c for c in cl if re.search(r"\d", c)]
    pick = dig[0] if dig else cl[0]
    rest = [c for c in cl if c != pick]
    if rest and len(pick) + len(rest[0]) + 1 <= n:
        pick = (rest[0] + "，" + pick) if cl.index(rest[0]) < cl.index(pick) else (pick + "，" + rest[0])
    return shorten(pick, n)


def fmt_order(text, debug=False):
    S, B, pair, cond, notes, seen = [], [], [], [], [], set()

    def put(side, px, q, act, why):
        key = (side, px) if not act.startswith("撤") else (side, px, "撤")   # 同一价同方向只出一行(先到的"改/留"为准)
        if key in seen:
            return
        seen.add(key)
        (S if side == "S" else B).append([px, q, act, why])

    for kind, body, head, ctx in units(text):
        if kind == "head":
            continue
        s = " | ".join(body) if kind == "row" else body
        tk = tokens(s)
        if debug:
            print(f"[{kind}] {s[:70]} → {[(t[2], t[3], t[4]) for t in tk]}", file=sys.stderr)
        # 改单条件 = 触发词 + 动作词(只有"跌破了均价线"这种描述、没有要你做什么的, 是依据不是条件)
        trig = bool(TRIGGER.search(s)) and bool(VERB.search(s)) and not (kind == "row" and tk)
        if not tk:
            if kind == "line" and PAIRKW.search(s):
                pair.append(s)
            elif trig:
                cond.append(s)
            elif kind == "line" and len(notes) < 3 and len(s) > 10 and re.search(r"转弱|转强|板块|统计|同形态|大概率|概率|结论|不改", s):
                notes.append(s)
            continue
        if CONDITIONAL.search(s) and kind == "line":
            pair.append(s)
            continue
        if trig and kind == "line" and not re.match(r"^[-*]?\s*(?:[①-⑩]|\d\.|卖|买|[SB](?=\s*[:：]))?\s*[:：]?\s*\d{1,3}\.\d", s):   # 行首就是单子(含"卖: 41.92S500 若…") = 挂单行, 不是条件
            cond.append(s)
            continue
        if kind == "row":
            # 条件格在单子格前面("| 41.80 卖出成交后加挂 | 41.48 × 300 |") = 这笔是后手单 → 整行进配对, 不进表
            ci = next((i for i, c in enumerate(body) if CONDITIONAL.search(c)), None)
            ti = next((i for i, c in enumerate(body) if tokens(c)), None)
            if ci is not None and ti is not None and ci < ti:
                pair.append(f"{body[ci].strip(' ，,')} → {body[ti].strip()}")
                continue
            # 条件在单子后面("| 42.07 卖 300 | 留着。如果冲上去成交, 就在 41.75 下方再买回 |") → 条件进配对, 单子照常进表
            cl = [c for c in re.split(r"[。；;|]", s) if CONDITIONAL.search(c) or re.search(r"如果|若", c)]
            for c in cl:
                pair.append(f"{tk[0][3]} 那笔: {c.strip(' ，,')}")
                s = s.replace(c, "")
            tk = tokens(s)
        # 改单的旧价没写量("43.36 → 41.40 × 400"): 补成同量的旧单, 让下面的改单配对认得出
        for t in list(tk):
            m = re.search(P + r"\s*(?:→|->|改成|改为)\s*$", s[max(0, t[0] - 16):t[0]])
            if m:
                st0 = max(0, t[0] - 16) + m.start(1)
                if not any(u[0] <= st0 < u[1] for u in tk):
                    tk.append((st0, st0 + len(m.group(1)), t[2], m.group(1), t[4]))
        tk.sort()
        # 方向: 显式 > token 前就近字样 > 本行/本表头语境 > 本行"买/卖"字样
        row_side = "B" if ("买" in s and "卖" not in s) else ("S" if ("卖" in s and "买" not in s) else None)
        sides = [t[2] or side_near(s, t[0], None) or ctx or row_side for t in tk]
        # 改单: ≥2 单且中间夹着 改/→ → (旧, 新) 成对
        i, used = 0, set()
        while i < len(tk) - 1:
            between = s[tk[i][1]:tk[i + 1][0]]
            if CHANGE.search(between):
                o, n = tk[i], tk[i + 1]
                sd = sides[i] or sides[i + 1]
                why = reason_of(s[n[1]:]) or reason_of(s)
                put(sides[i + 1] or sd, n[3], n[4], f"改(原{o[3]})", why)
                put(sd, o[3], o[4], f"撤→{n[3]}", "")
                used |= {i, i + 1}
                i += 2
                continue
            i += 1
        for j, t in enumerate(tk):
            if j in used:
                continue
            lo = max(tk[j - 1][1] if j else 0, t[0] - 10)   # 不跨进上一单
            seg = s if len(tk) == 1 else s[lo:(tk[j + 1][0] if j + 1 < len(tk) else len(s))]
            sd = sides[j] or "?"
            if sd == "?":
                notes.append("(方向没认出) " + s)
                continue
            why = reason_of(s if kind == "row" else seg)
            if len(why) < 4 and kind == "line":
                why = reason_of(s)          # 一行几单共用一个理由("41.70 买 300 和 41.62 买 300，大约各有一半机会")
            put(sd, t[3], t[4], act_of(seg), why)
    # ---------- 组装
    st = {}
    flat = clean(text)
    for k, rx in STATUS_RES:
        m = re.search(rx, flat)
        if m:
            st[k] = m.group(1)
    hhmm = re.search(r"\b(\d{1,2}:\d\d)\b", flat[:200])
    name = next((n for n in ("牧原", "中国银行", "中行", "纳指") if n in flat), None)   # 只认持仓 / 做 T 品种, 温氏这类是依据里的参照
    out = []
    head = " ｜ ".join(([name] if name else []) + ([hhmm.group(1)] if hhmm else []) + [f"{k}{v}" for k, v in st.items()])
    if re.search(r"以这条为准|作废", flat):
        out.append("⚠️ 以这条为准(之前的作废)")
    out.append("📊 " + head)
    order_key = lambda r: -float(str(r[0]).split("/")[-1])   # noqa: E731
    hdr = ["价格", "量", "动作", "依据"]
    # 10/19 用户定: 红 = 买(中国习惯), B 档在前; 顺序 📊 → 🔴B → 🟢S → 🔗 → ⚡
    if B:
        out += ["", "🔴 B 档(买 / 接回)", table(sorted(B, key=order_key), hdr)]
    if S:
        out += ["", "🟢 S 档(卖)", table(sorted(S, key=order_key), hdr)]
    live = lambda R: sum(int(r[1]) for r in R if not r[2].startswith("撤"))   # noqa: E731
    pl = [f"挂着的: 卖 {live(S)} 股 / 买 {live(B)} 股 → 全成交净{'买' if live(B) >= live(S) else '卖'} {abs(live(B) - live(S))} 股"] if (S or B) else []
    pl += [shorten(x, 60) for x in dict.fromkeys(pair)]
    if pl:
        out += ["", "🔗 配对"] + ["- " + x for x in pl[:5]]
    if cond:
        out += ["", "⚡ 改单条件"] + ["- " + bold_prices(shorten(x, 70)) for x in list(dict.fromkeys(cond))[:6]]
    if notes:
        out += ["", "📝 要点"] + ["- " + shorten(x, 50) for x in notes[:3]]
    return "\n".join(out)


# ================================================================ 日报 / 对账
BAD = re.compile(r"红|❌|FAIL|失败|异常|缺|熔断|报错|超时|没跑|未跑|不一致|对不上|⚠|黄")
GOOD = re.compile(r"绿|✅|OK|正常|成功|已最新|通过|已闭环|自动修好|完成")
ICON = [("大盘", "📊"), ("前三", "🏆"), ("后三", "📉"), ("对照", "👥"), ("修复", "🔧"), ("自愈", "🔧"), ("异常", "⚠️"), ("paper", "📊"),
        ("链", "⛓️"), ("行情", "📈"), ("健康", "🩺"), ("体检", "🩺"), ("B站", "🎬"), ("UP", "🎬"), ("tzzb", "📒"), ("账本", "📒")]


def sections(text):
    secs, cur = [], ["概要", []]
    for raw in text.splitlines():
        l = clean(raw)
        if not l or re.match(r"^\|?\s*:?-{2,}", l):
            continue
        if re.match(r"^#{1,4}\s", raw.strip()) or re.match(r"^【[^】]{1,20}】\s*$", l) or (raw.strip().startswith("**") and raw.strip().rstrip("：:").endswith("**")):
            if cur[1]:
                secs.append(cur)
            cur = [l.lstrip("# ").strip("【】：:"), []]
        else:
            cur[1].append(re.sub(r"^[-*•]\s*", "", l))
    if cur[1]:
        secs.append(cur)
    return secs


def fmt_report(text):
    bad, good = [], []
    for title, lines in sections(text):
        b = [x for x in lines if BAD.search(x) and not re.search(r"^\|?\s*绿", x)]
        g = [x for x in lines if x not in b]
        icon = next((e for k, e in ICON if k in title), "📋")
        if b:
            bad.append((icon, title, b))
        if g:
            good.append((icon, title, g))
    out = []
    for icon, title, b in bad:
        out += [f"❌ {title}" if any(re.search(r"红|❌|FAIL|失败", x) for x in b) else f"⚠️ {title}"] + ["- " + shorten(x.replace("|", " "), 90) for x in b[:5]] + [""]
    if good:
        out.append("✅ 正常: " + "；".join(f"{icon}{title} {len(g)} 项" for icon, title, g in good))
    return "\n".join(out).strip()


# ================================================================ 预判
def fmt_forecast(text):
    out = []
    for title, lines in sections(text):
        out.append(f"\n📈 {shorten(title, 30)}")
        for x in lines:
            if x.startswith("|"):
                cells = [shorten(c, 16) for c in x.strip("|").split("|")][:5]
                out.append("| " + " | ".join(cells) + " |")
            elif re.search(r"概率|支撑|压力|情景|若|如果|%", x):
                out.append("▸ " + bold_prices(shorten(x, 80)))
            else:
                out.append("· " + shorten(x, 60))
    return "\n".join(out).strip()


# ================================================================ 通用消息(进度汇报 / 结论 / 说明; 兜底)
SEC_ICON = [(r"问题|异常|失败|报错|没做|没发|卡住|错", "⚠️"), (r"需要你|你定|等你|请你|确认", "🙋"), (r"结论|判断|结果|发现", "📌"),
            (r"改了|修了|修复|改动|文件|新建|落地", "🔧"), (r"完成|做好|已推|已发|搞定|上线", "✅"), (r"测试|验证|回归", "🧪"),
            (r"下一步|待办|计划|今晚|明天|周三", "⏭️"), (r"账|仓位|持仓", "💰"), (r"盘面|大盘|行情|现价", "📈")]


def _icon(title):
    return next((e for rx, e in SEC_ICON if re.search(rx, title)), "📋")


def _is_head(raw):
    s = raw.strip()
    return bool(re.match(r"^#{1,4}\s", s)) or bool(re.match(r"^\*\*[^*]{2,40}\*\*[：:]?$", s))


def fmt_generic(text):
    """md 标题 / 整行粗体 = 小节 → emoji 分节; 列表 → ▸; 表格 ≤5 列、单元格 ≤24 字; 代码块只留前 6 行; 去粗体 / 反引号"""
    out, in_code, code_n = [], False, 0
    for raw in text.splitlines():
        l = raw.rstrip()
        if l.strip().startswith("```"):
            in_code, code_n = not in_code, 0
            continue
        if in_code:
            code_n += 1
            if code_n <= 6:
                out.append("  " + shorten(l.strip(), 100))
            elif code_n == 7:
                out.append("  …")
            continue
        if not l.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        if l.lstrip().startswith("|"):
            if re.match(r"^\|?\s*:?-{2,}", l.strip()):
                out.append("|" + "---|" * min(5, l.count("|") - 1))
                continue
            cells = [shorten(clean(c), 24) for c in l.strip().strip("|").split("|")][:5]
            out.append("| " + " | ".join(cells) + " |")
        elif _is_head(l):
            t = clean(l.lstrip("# ")).rstrip("：:")
            out += (["", f"{_icon(t)} {t}"] if out and out[-1] != "" else [f"{_icon(t)} {t}"])
        elif re.match(r"^\s*[-*•]\s+", l):
            ind = "   " if len(l) - len(l.lstrip()) >= 2 else ""
            out.append(ind + "▸ " + shorten(clean(re.sub(r"^\s*[-*•]\s+", "", l)), 150))
        else:
            out.append(shorten(clean(l), 200))
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out).strip()


def format_text(raw, kind=None, hhmm="", debug=False):
    """对外接口(wx_send.py 用): 返回 (类型, 排好的整条消息)"""
    raw = raw.strip()
    kind = kind or classify(raw)
    body = {"order": lambda t: fmt_order(t, debug), "report": fmt_report, "forecast": fmt_forecast}.get(kind, fmt_generic)(raw) or fmt_generic(raw)
    tag = {"order": "挂单", "report": "日报", "forecast": "预判", "generic": "消息"}[kind]
    return kind, f"【{tag}{'·' + hhmm if hhmm else ''}】\n{body}"


def main():
    for s in (sys.stdout, sys.stdin):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--from-jsonl", action="store_true")
    ap.add_argument("--at")
    ap.add_argument("--grep")
    ap.add_argument("--session")
    ap.add_argument("--kind", choices=["order", "report", "forecast", "generic"])
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    hhmm = ""
    if a.from_jsonl:
        got = from_jsonl(a.at, a.grep, a.session)
        if not got:
            print("(会话存档里没找到符合条件的长回复)")
            return
        loc, raw = got
        hhmm = loc.strftime("%H:%M")
    else:
        raw = a.text if a.text else sys.stdin.read()
    kind, msg = format_text(raw, a.kind, hhmm, a.debug)
    print(msg)
    if a.send:   # 发送统一走 wx_send(配额退避 / 分段 / 落账); 这里只排版
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wx_send
        wx_send.send(msg, src="fmt_cli_reply", raw=True)


if __name__ == "__main__":
    main()
