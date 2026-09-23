# 转写文本股票名纠错 v4: jieba 分词 + 拼音反查 + 首字母校验 + 实体表
# 校验1: 无声调全拼反查 (沐溪->沐曦, SK海利市->SK海力士)
# 校验2: 首字母反查 (全拼未命中时的兜底, skhls->SK海力士; 仅 len>=3 且首字母唯一)
# 级别:
#   L0 单字重组: jieba 切成单字的连续片段(OOV 词), 2-4 字滑窗全拼唯一命中 -> 替换 (句首 沐溪 残留)
#   L1 单词: 2-4 字, 非常见词+含罕字, 全拼唯一命中简称 -> 替换
#   L2 词组: 相邻两词拼接 4-6 字, 全拼唯一命中全名 -> 替换 (国防集团->国芳集团)
#   LE 实体: 相邻 <=3 词拼接(允许含字母数字), 命中实体表(SK海力士/英伟达等非A股) -> 替换
#   L3 首字母: 全拼未命中时, 首字母唯一命中且 len>=3 -> 替换 (记日志待抽查)
#   歧义(一音多股/一首字母多股)不替换, 仅记录
# 用法: correct_names.py [in_dir] [out_dir]
import os, re, sys, json
from pypinyin import pinyin, Style
import jieba

BASE = os.path.dirname(os.path.abspath(__file__))
IN_DIR = os.path.join(BASE, "downloads", sys.argv[1] if len(sys.argv) > 1 else "txt")
OUT_DIR = os.path.join(BASE, "downloads", sys.argv[2] if len(sys.argv) > 2 else "txt_fixed")
os.makedirs(OUT_DIR, exist_ok=True)
LOG = os.path.join(OUT_DIR, "_corrections.log")
open(LOG, "w", encoding="utf-8").close()

def py(text):
    return "".join(p[0] for p in pinyin(text, style=Style.NORMAL, errors="ignore")).lower()

def ini(text):
    return "".join(p[0][0] for p in pinyin(text, style=Style.NORMAL, errors="ignore") if p[0]).lower()

dict_raw = json.load(open(os.path.join(BASE, "downloads", "stock_dict.json"), encoding="utf-8"))
entities = json.load(open(os.path.join(BASE, "downloads", "entity_dict.json"), encoding="utf-8"))

def norm_name(name):
    return re.sub(r"^[NC]\s*", "", name)

# 全名索引(3字以上) + 简称索引(去后缀/前缀) + 实体索引(非A股: SK海力士/英伟达/台积电...)
full_index = {}   # pinyin -> set(name)
short_index = {}
entity_index = {}
for full in dict_raw:
    n = norm_name(full)
    if len(n) >= 3:
        full_index.setdefault(py(n), set()).add(n)
    shorts = set()
    n2 = re.sub(r"(股份|集团|控股|环境|环保|新材|材料)$", "", n)
    if 2 <= len(n2) <= 4:
        shorts.add(n2)
    if len(n) == 4:
        shorts.add(n[:2])
    for s in shorts:
        short_index.setdefault(py(s), set()).add(s)
for e in entities:
    entity_index.setdefault(py(e), set()).add(e)

full_unique = {p: list(s)[0] for p, s in full_index.items() if len(s) == 1}
short_unique = {p: list(s)[0] for p, s in short_index.items() if len(s) == 1}
entity_unique = {p: list(s)[0] for p, s in entity_index.items() if len(s) == 1}

# 首字母索引(校验2): 全名+简称+实体一起, 只保留唯一映射
ini_all = {}
for idx in (full_index, short_index, entity_index):
    for p, names in idx.items():
        for nm in names:
            ini_all.setdefault(ini(nm), set()).add(nm)
ini_unique = {k: list(s)[0] for k, s in ini_all.items() if len(s) == 1}
print(f"full_unique={len(full_unique)} short_unique={len(short_unique)} entity_unique={len(entity_unique)} ini_unique={len(ini_unique)}")

# 常见金融/口语词, 拼音命中也绝不替换
BLOCK = set("""知道 可以 因为 所以 如果 但是 就是 还是 已经 今天 明天 昨天 现在 我们 他们 大家 什么 怎么 这个 那个
一个 没有 不是 时候 可能 应该 觉得 这样 那样 然后 而且 或者 市场 资金 股价 股票 板块 涨停 跌停 开盘 收盘 成交 放量 缩量
龙头 题材 概念 利好 利空 解禁 新股 次新 创业板 科创板 半导体 芯片 科技 农业 消费 医药 军工 地产 银行 证券 保险
电池 光伏 风电 化工 钢铁 煤炭 有色 黄金 原油 美元 加息 降息 指数 大盘 情绪 高位 低位 回调 反弹 尾盘 早盘 盘中
跳水 拉升 下杀 承接 换手 封板 炸板 连板 打板 低吸 追高 抄底 止损 仓位 满仓 空仓 减仓 加仓 阴线 阳线 市值 估值
其实 心里 机会 风险 收益 亏钱 赚钱 兄弟 姐妹 注意 提醒 记录 经典 复盘 操作 逻辑 预期 落地 兑现 异动 监管 停牌
一波 套利 高开 低开 高走 低走 震荡 分时 均线 缺口 压力 支撑 突破 回踩 缩量 放量 换手 市盈 市净 分红 定增 回购 减持 增持""".split())
BLOCK_PY = {py(w) for w in BLOCK}

jieba.initialize()  # 必须先初始化, 否则 FREQ 是空表
FREQ = jieba.dt.FREQ
from collections import defaultdict
CHAR_FREQ = defaultdict(int)
for _w, _f in FREQ.items():
    for _c in set(_w):
        CHAR_FREQ[_c] += _f
CHAR_RARE_TH = 30000
WORD_FREQ_TH = 50

def is_common_word(w):
    if w in BLOCK or py(w) in BLOCK_PY:
        return True
    return FREQ.get(w, 0) >= WORD_FREQ_TH

def has_rare_char(w):
    return any(CHAR_FREQ[c] < CHAR_RARE_TH for c in w if re.match(r"[一-鿿]", c))

CJK = r"[一-鿿]"
ALNUM_CJK = r"[A-Za-z0-9一-鿿]"

# 拉丁前缀实体锚点: SK -> [SK海力士], AMD -> [AMD] ... (实体匹配不依赖分词)
LATIN_ENT = {}
for _e in entities:
    _m = re.match(r"^([A-Za-z0-9]+)", _e)
    if _m:
        LATIN_ENT.setdefault(_m.group(1).lower(), []).append(_e)

def entity_anchor_pass(line, log, tag):
    """字符串级实体锚定: 找到拉丁前缀(SK), 取其后 <=6 个汉字窗口, 与实体逐音节比较, <=1 音节不同即替换"""
    if not LATIN_ENT:
        return line
    out = []
    pos = 0
    for m in re.finditer(r"[A-Za-z]{2,}", line):
        lat = m.group(0)
        cands = LATIN_ENT.get(lat.lower())
        if not cands:
            continue
        for e in cands:
            latlen = len(re.match(r"^[A-Za-z0-9]+", e).group(0))
            L = len(e) - latlen
            if L <= 0:
                continue
            cand_tail = line[m.end():m.end() + L]
            if not re.fullmatch(CJK + "{" + str(L) + "}", cand_tail):
                continue
            cand = lat + cand_tail
            if cand == e:
                break
            se, sc = syll(e), syll(cand)
            if len(se) == len(sc) and sum(1 for a, b in zip(se, sc) if a != b) <= 1:
                log.append(f"{tag}\t{cand}\t->\t{e}\tLE")
                out.append(line[pos:m.start()]); out.append(e)
                pos = m.end() + L
                break
    if not out:
        return line
    out.append(line[pos:])
    return "".join(out)

def syll(text):
    return [p[0].lower() for p in pinyin(text, style=Style.NORMAL, errors="ignore") if p[0]]

def try_l3(word, log, tag):
    """校验2: 首字母相同且全拼仅 1 个音节不同(ASR 元音级错误), 唯一命中; 需 len>=3+含罕字+非常见词"""
    if len(word) < 3 or not re.fullmatch(ALNUM_CJK + "+", word):
        return None
    if is_common_word(word) or not has_rare_char(word):
        return None
    k = ini(word)
    if k not in ini_unique:
        return None
    name = ini_unique[k]
    if word == name or py(word) in BLOCK_PY:
        return None
    sw, sn = syll(word), syll(name)
    if len(sw) != len(sn):
        return None
    diff = sum(1 for a, b in zip(sw, sn) if a != b)
    if diff <= 1:
        log.append(f"{tag}\t{word}\t->\t{name}\tL3")
        return name
    return None

def correct_line(line, log, tag):
    line = entity_anchor_pass(line, log, tag)
    tokens = list(jieba.cut(line, HMM=True))
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        # L0: 连续单字片段, 2-4 字滑窗重组 (jieba 对 OOV 词会切成单字)
        if re.fullmatch(CJK, t):
            run = []
            j = i
            while j < len(tokens) and re.fullmatch(CJK, tokens[j]):
                run.append(tokens[j]); j += 1
            s = "".join(run)
            # 若前一个 token 是字母数字(如 SK), 先尝试 前缀+run头部 命中实体 (SK海利市->SK海力士)
            if out and re.fullmatch(r"[A-Za-z0-9]+", out[-1]):
                for wlen in range(min(6, len(s)), 0, -1):
                    cand = out[-1] + s[:wlen]
                    if len(cand) <= 8 and py(cand) in entity_unique and cand != entity_unique[py(cand)]:
                        log.append(f"{tag}\t{cand}\t->\t{entity_unique[py(cand)]}\tLE")
                        out[-1] = entity_unique[py(cand)]
                        s = s[wlen:]
                        break
            k = 0
            while k < len(s):
                hit = None
                for wlen in (4, 3, 2):
                    w = s[k:k + wlen]
                    if len(w) < 2:
                        continue
                    p = py(w)
                    # 实体: 全拼相等即采信 (多音节约束强, 免罕字要求)
                    if p in entity_unique and w != entity_unique[p]:
                        hit = (wlen, entity_unique[p], "LE")
                        break
                    # 股名简称: 必须每个字都是罕字 (否则 买的->迈得 这类灾难)
                    if all(CHAR_FREQ[c] < CHAR_RARE_TH for c in w) and not is_common_word(w):
                        if p in short_unique and w != short_unique[p]:
                            hit = (wlen, short_unique[p], "L0")
                            break
                if hit:
                    log.append(f"{tag}\t{s[k:k+hit[0]]}\t->\t{hit[1]}\t{hit[2]}")
                    out.append(hit[1]); k += hit[0]
                else:
                    out.append(s[k]); k += 1
            i = j
            continue
        # LE: 相邻 <=3 词拼接命中实体表 (允许字母数字混合, 如 SK海利市); n=1 处理整词被切成一个 token 的情况
        le_hit = False
        for n in (3, 2, 1):
            if i + n <= len(tokens):
                combo = "".join(tokens[i:i + n])
                if 2 <= len(combo) <= 8 and re.fullmatch(ALNUM_CJK + "+", combo) and FREQ.get(combo, 0) < WORD_FREQ_TH:
                    p = py(combo)
                    if p in entity_unique and combo != entity_unique[p]:
                        log.append(f"{tag}\t{combo}\t->\t{entity_unique[p]}\tLE")
                        out.append(entity_unique[p]); i += n
                        le_hit = True
                        break
        if le_hit:
            continue
        # L2: 两词拼接匹配全名
        if i + 1 < len(tokens):
            combo = t + tokens[i + 1]
            if 4 <= len(combo) <= 6 and re.fullmatch(CJK + "+", combo) and FREQ.get(combo, 0) < WORD_FREQ_TH:
                p = py(combo)
                if p in full_unique and combo != full_unique[p] and p not in BLOCK_PY:
                    log.append(f"{tag}\t{combo}\t->\t{full_unique[p]}\tL2")
                    out.append(full_unique[p]); i += 2; continue
                r3 = try_l3(combo, log, tag)
                if r3:
                    out.append(r3); i += 2; continue
        # L1: 单词匹配简称 (需: 不是常见词 + 含罕字)
        if 2 <= len(t) <= 4 and re.fullmatch(CJK + "+", t) and not is_common_word(t) and has_rare_char(t):
            p = py(t)
            if p in short_unique and t != short_unique[p] and p not in BLOCK_PY:
                log.append(f"{tag}\t{t}\t->\t{short_unique[p]}\tL1")
                out.append(short_unique[p]); i += 1; continue
            r3 = try_l3(t, log, tag)
            if r3:
                out.append(r3); i += 1; continue
            # 歧义记录
            if p in short_index and len(short_index[p]) > 1 and t not in short_index[p]:
                log.append(f"{tag}\t{t}\t??\t{'/'.join(sorted(short_index[p]))}\tAMBIG")
        out.append(t)
        i += 1
    return "".join(out)

files = sorted(f for f in os.listdir(IN_DIR) if f.endswith(".txt"))
cnt = defaultdict(int)
for fname in files:
    tag = fname[:-4]
    log = []
    lines = open(os.path.join(IN_DIR, fname), encoding="utf-8").read().splitlines()
    fixed = [correct_line(l, log, tag) for l in lines]
    with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
        f.write("\n".join(fixed) + "\n")
    for entry in log:
        cnt[entry.rsplit("\t", 1)[-1]] += 1
    if log:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
print(f"done files={len(files)} " + " ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
