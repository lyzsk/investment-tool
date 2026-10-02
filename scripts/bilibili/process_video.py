# 桃哥视频处理管线 (2026-09-27 由 transcribe.py + correct_names.py + vision_extract.py + aggregate_pages.py 四合一并迁至 scripts/)
# 业务: 一个视频从原始产物(mp4/m4a)到可读知识(txt+vision.json), 一次调用全链路
# 用法(用 scripts/venv 的 python, cwd=项目根):
#   python scripts/process_video.py --bvid BVxxxx --mp4 <mp4路径> --m4a <m4a路径> --out <结果目录>
#   --stage asr,correct,vision,aggregate   # 逗号分隔子集, 默认 all (调试/回填逃生口)
#   --keep-frames                          # 保留抽帧中间产物(默认聚合后删除)
#   --download-model                       # 下载 Qwen2.5-VL-7B 到 scripts/models/(一次性)
# 产物(全部落在 --out 目录): <bvid>.raw.txt(whisper原始稿,纠错翻车诊断用) + <bvid>.tsv(时间戳边车)
#   + <bvid>.txt(纠错后, 合成真正读的) + <bvid>.vision.json(逐帧vlm/ocr + pages聚合段)
# 幂等: 阶段产物已存在则跳过, 重跑只补缺; 退出码 0=所求阶段产物全部就位, 1=任一失败
# GPU 串行: whisper(ASR)跑完卸载再加载 7B(视觉), 不共驻显存
# 数据依赖: 股名/实体字典 + 7B 模型在 scripts/models/(2026-10-02 从 plan-a/downloads 迁出)
import argparse, gc, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

# 防 cudnn64_9.dll 同名劫持(2026-10-02 定位, 0xC0000409 根因): ctranslate2 包目录附带
# cudnn64_9.dll 9.10.2(裸头库无子库), 同进程先 import faster_whisper 会把它抢注进进程,
# torch 之后按名字拿 cudnn 拿到错版 → VLM 阶段 fail-fast。抢在一切 import 前 ctypes 加载并
# 持有 torch 自带版(9.1.0), Windows DLL 按 basename 去重, 先注者胜。必须持有引用防 FreeLibrary。
import ctypes as _ctypes
_TORCH_CUDNN = Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib" / "cudnn64_9.dll"
if _TORCH_CUDNN.exists():
    _CUDNN_HOLD = _ctypes.CDLL(str(_TORCH_CUDNN))

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/
ASSETS = SCRIPT_DIR.parent / "models"                 # 模型+字典仓库=scripts/models/(10/2 迁入 scripts/bilibili/ 后上溯一级)
MODEL_DIR = ASSETS / "Qwen2.5-VL-7B-Instruct"
STOCK_DICT = ASSETS / "stock_dict.json"
ENTITY_DICT = ASSETS / "entity_dict.json"


# ============================================================ ASR (原 transcribe.py)
def stage_asr(m4a: Path, out: Path, bvid: str, model_size="small"):
    """m4a -> raw.txt + tsv。faster-whisper CPU int8(原 transcribe.py 口径, 不占显存)"""
    raw_txt, tsv = out / f"{bvid}.raw.txt", out / f"{bvid}.tsv"
    if raw_txt.exists() and tsv.exists() and raw_txt.stat().st_size > 0:
        print(f"[asr] skip (exists): {raw_txt}")
        return
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内网络: 模型走 hf-mirror
    wav = os.path.join(tempfile.gettempdir(), f"process_video_{bvid}_16k.wav")
    subprocess.run(["ffmpeg", "-y", "-i", str(m4a), "-ar", "16000", "-ac", "1", "-f", "wav", wav],
                   check=True, capture_output=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        wav, language="zh", beam_size=5, vad_filter=True,
        initial_prompt="以下是A股股市复盘口播内容,涉及股票名称、板块、涨跌幅。")
    lines, segs = [], []
    for seg in segments:
        line = seg.text.strip()
        if line:
            lines.append(line)
            segs.append(seg)
        print(f"[{seg.start:7.1f}s] {line}", flush=True)
    del model  # 显式卸载, 与 7B 串行
    gc.collect()

    raw_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(tsv, "w", encoding="utf-8") as f:  # 时间戳边车: 口述↔画面对齐用
        for seg in segs:
            f.write(f"{seg.start:.2f}\t{seg.end:.2f}\t{seg.text.strip()}\n")
    print(f"[asr] saved: {raw_txt} + .tsv", file=sys.stderr)


# ============================================================ 纠错 (原 correct_names.py, 逻辑原样, 模块级代码收进函数)
# 校验1: 无声调全拼反查 (沐溪->沐曦)  校验2: 首字母反查兜底 (skhls->SK海力士, len>=3+唯一)
# 级别: L0 单字重组 / L1 单词→简称 / L2 两词→全名 / LE 实体表(SK海力士等非A股) / L3 首字母(1音节差异)
# 歧义不替换仅记录; 常见词(FREQ>=50)跳过+含罕字+BLOCK 表守卫
_CORRECT_READY = False


def _init_correct():
    global _CORRECT_READY, full_unique, short_unique, entity_unique, ini_unique
    global BLOCK, BLOCK_PY, FREQ, CHAR_FREQ, LATIN_ENT, short_index
    if _CORRECT_READY:
        return
    from pypinyin import pinyin, Style  # noqa: F401  (py/ini/syll 用到)
    import jieba
    dict_raw = json.load(open(STOCK_DICT, encoding="utf-8"))
    entities = json.load(open(ENTITY_DICT, encoding="utf-8"))

    full_index, short_index, entity_index = {}, {}, {}
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

    ini_all = {}  # 首字母索引: 全名+简称+实体一起, 只保留唯一映射
    for idx in (full_index, short_index, entity_index):
        for p, names in idx.items():
            for nm in names:
                ini_all.setdefault(ini(nm), set()).add(nm)
    ini_unique = {k: list(s)[0] for k, s in ini_all.items() if len(s) == 1}
    print(f"[correct] full_unique={len(full_unique)} short_unique={len(short_unique)} "
          f"entity_unique={len(entity_unique)} ini_unique={len(ini_unique)}")

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

    # 拉丁前缀实体锚点: SK -> [SK海力士] ... (实体匹配不依赖分词)
    LATIN_ENT = {}
    for _e in entities:
        _m = re.match(r"^([A-Za-z0-9]+)", _e)
        if _m:
            LATIN_ENT.setdefault(_m.group(1).lower(), []).append(_e)
    _CORRECT_READY = True


CHAR_RARE_TH = 30000
WORD_FREQ_TH = 50
CJK = r"[一-鿿]"
ALNUM_CJK = r"[A-Za-z0-9一-鿿]"


def py(text):
    from pypinyin import pinyin, Style
    return "".join(p[0] for p in pinyin(text, style=Style.NORMAL, errors="ignore")).lower()


def ini(text):
    from pypinyin import pinyin, Style
    return "".join(p[0][0] for p in pinyin(text, style=Style.NORMAL, errors="ignore") if p[0]).lower()


def syll(text):
    from pypinyin import pinyin, Style
    return [p[0].lower() for p in pinyin(text, style=Style.NORMAL, errors="ignore") if p[0]]


def norm_name(name):
    return re.sub(r"^[NC]\s*", "", name)


def is_common_word(w):
    if w in BLOCK or py(w) in BLOCK_PY:
        return True
    return FREQ.get(w, 0) >= WORD_FREQ_TH


def has_rare_char(w):
    return any(CHAR_FREQ[c] < CHAR_RARE_TH for c in w if re.match(CJK, c))


def entity_anchor_pass(line, log, tag):
    """字符串级实体锚定: 找到拉丁前缀(SK), 取其后 <=6 个汉字窗口, 与实体逐音节比较, <=1 音节不同即替换"""
    if not LATIN_ENT:
        return line
    out, pos = [], 0
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
    if sum(1 for a, b in zip(sw, sn) if a != b) <= 1:
        log.append(f"{tag}\t{word}\t->\t{name}\tL3")
        return name
    return None


def correct_line(line, log, tag):
    import jieba
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
        # LE: 相邻 <=3 词拼接命中实体表 (允许字母数字混合); n=1 处理整词被切成一个 token 的情况
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


def stage_correct(out: Path, bvid: str):
    """raw.txt -> txt(纠错后, 合成读它)。纠错记录落 <bvid>.correct.log(无改动不写)"""
    txt = out / f"{bvid}.txt"
    if txt.exists() and txt.stat().st_size > 0:
        print(f"[correct] skip (exists): {txt}")
        return
    _init_correct()
    raw = (out / f"{bvid}.raw.txt").read_text(encoding="utf-8").splitlines()
    log = []
    fixed = [correct_line(l, log, bvid) for l in raw]
    txt.write_text("\n".join(fixed) + "\n", encoding="utf-8")
    if log:
        (out / f"{bvid}.correct.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"[correct] saved: {txt} ({len(log)} 处改动)", file=sys.stderr)


# ============================================================ 视觉 (原 vision_extract.py --dense + aggregate_pages.py)
# Vision 2.0 prompt: 加持仓页/自选股类型 + 持仓明细 + B/S 点细化 (桃哥人格需要行为真值, ASR 只有叙事)
PROMPT = (
    "这是A股炒股软件(同花顺)的手机竖屏截图, 来自一位股民的复盘视频。"
    "请提取JSON(没有的字段填null): {"
    "\"股票名\":str(列表/持仓页填画面最核心的一只或null), \"代码\":str, \"最新价\":number, \"涨跌幅%\":number, "
    "\"页面类型\":\"分时|K线|盘口|自选股|持仓|成交|资讯|其他\", "
    "\"今开\":number, \"最高\":number, \"最低\":number, "
    "\"图上买卖标记\":\"描述分时/K线上B(买)S(卖)标记的位置与价位, 如'B点在8.13附近', 无则null\", "
    "\"持仓明细\":\"仅持仓页: [{名称,代码,持仓数量,成本价,现价,盈亏%}], 非持仓页null\", "
    "\"自选股清单\":\"仅自选股/列表页: 画面上全部股票名按序排列, 非列表页null\", "
    "\"其他关键信息\":\"如换手率/市值/板块/弹幕字幕中有价值的一句\""
    "}。只输出JSON, 不要多余文字。"
)


def frames_dir(out: Path, bvid: str) -> Path:
    return out / f"frames_{bvid}"  # 抽帧中间产物, 聚合后默认删除(--keep-frames 保留)


def vision_json(out: Path, bvid: str) -> Path:
    return out / f"{bvid}.vision.json"


def _save_vision(out: Path, bvid: str, key, data):
    p = vision_json(out, bvid)
    doc = json.loads(p.read_text("utf-8")) if p.exists() else {"bvid": bvid}
    doc[key] = data
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    print(f"[save] {p} ({key})")


def _extract_frames(mp4: Path, fdir: Path, thresh=0.08, interval=None, max_frames=150):
    """ffmpeg 场景检测(thresh放低: 手机滑动切屏场景分低) ∪ 固定网格, 超上限均匀抽稀"""
    fdir.mkdir(parents=True, exist_ok=True)
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
    dur = float(pr.stdout.strip())
    if interval is None:
        # 9/27 片长自适应(用户拍板放弃回测口径一致性, 追分辨率): 目标网格 ~120 点,
        # interval=clamp(dur/120, 1s, 3s) —— <2min 短视频 1s 一帧(BS点/切屏都是瞬时的),
        # 2-5min 在 1~2.5s 之间, >5min 钉 3s; max_frames 上限兜底 VLM 工时
        interval = max(1.0, min(3.0, dur / 120))
    interval = max(interval, dur / max_frames)   # 9/27 长视频自适应: 网格随片长拉粗, 等效于事后抽稀但不浪费点位
    r = subprocess.run(["ffmpeg", "-i", str(mp4), "-vf", f"select='gt(scene,{thresh})',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True)
    ts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    scene_pts = {round(t + 0.8, 1) for t in ts}          # +0.8s 等画面稳定
    grid_pts = {round(t, 1) for t in [0.5 + i * interval for i in range(int(dur / interval) + 1)]}
    points = sorted(scene_pts | grid_pts)
    if len(points) > max_frames:
        step = len(points) / max_frames
        points = [points[int(i * step)] for i in range(max_frames)]
    for f in fdir.glob("t*.png"):
        f.unlink()
    for t in points:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(mp4),
                        "-frames:v", "1", str(fdir / f"t{t}.png"), "-y"], check=True)
    print(f"[frames] {len(points)} frames -> {fdir}")


def _ocr_frames(fdir: Path):
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    result = {}
    for png in sorted(fdir.glob("t*.png"), key=lambda p: float(p.stem[1:])):
        lines, _ = ocr(str(png))
        result[png.stem] = [{"text": l[1], "score": round(float(l[2]), 3)} for l in (lines or [])]
        print(f"[ocr] {png.stem}: {len(result[png.stem])} lines")
    return result


def _vlm_frames(fdir: Path):
    """Qwen2.5-VL-7B bf16 逐帧理解; 跑完显式卸载(empty_cache), 与 whisper 串行不共驻"""
    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
    from qwen_vl_utils import process_vision_info
    if not MODEL_DIR.exists():
        sys.exit(f"model not found: {MODEL_DIR} (先跑 python scripts/process_video.py --download-model)")
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        str(MODEL_DIR), torch_dtype=torch.bfloat16, device_map="cuda")
    processor = AutoProcessor.from_pretrained(str(MODEL_DIR))
    result = {}
    for png in sorted(fdir.glob("t*.png"), key=lambda p: float(p.stem[1:])):
        msgs = [{"role": "user", "content": [
            {"type": "image", "image": str(png)},
            {"type": "text", "text": PROMPT}]}]
        text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        imgs, vids = process_vision_info(msgs)
        inputs = processor(text=[text], images=imgs, videos=vids,
                           padding=True, return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=512, do_sample=False)
        ans = processor.batch_decode(out[:, inputs.input_ids.shape[1]:],
                                     skip_special_tokens=True)[0]
        m = re.search(r"\{.*\}", ans, re.S)
        try:
            result[png.stem] = json.loads(m.group(0)) if m else {"raw": ans}
        except json.JSONDecodeError:
            result[png.stem] = {"raw": ans}
        print(f"[vlm] {png.stem}: {str(result[png.stem])[:80]}")
    del model, processor
    torch.cuda.empty_cache()
    gc.collect()
    return result


def stage_vision(mp4: Path, out: Path, bvid: str, keep_frames: bool):
    """mp4 -> vision.json(ocr+vlm 两段)。抽帧片长自适应口径(9/27 起: clamp(dur/120,1s,3s)网格∪场景切换, 150帧上限, 见 _extract_frames)"""
    doc = json.loads(vision_json(out, bvid).read_text("utf-8")) \
        if vision_json(out, bvid).exists() else {}
    if doc.get("vlm") and doc.get("ocr"):
        print(f"[vision] skip (exists): {vision_json(out, bvid)}")
        return
    fdir = frames_dir(out, bvid)
    _extract_frames(mp4, fdir)
    _save_vision(out, bvid, "ocr", _ocr_frames(fdir))
    _save_vision(out, bvid, "vlm", _vlm_frames(fdir))


# ---------- 聚合 (原 aggregate_pages.py): 逐帧 vlm/ocr -> pages 段(行为真值)
def ts_of(tag):
    m = re.search(r"([\d.]+)", tag)
    return float(m.group(1)) if m else 0.0


def norm_type(t):
    t = str(t or "其他")
    for k in ("分时", "K线", "盘口", "自选股", "持仓", "成交", "资讯"):
        if k in t:
            return k
    return "其他"


def build_pages(doc):
    """连续同票(或同列表页)帧 -> 页面段时间轴/注意力榜驻留秒/BS买卖点/持仓快照/自选股清单"""
    vlm = doc.get("vlm") or {}
    frames = sorted(vlm.items(), key=lambda kv: ts_of(kv[0]))
    segments, cur = [], None
    positions, watchlist, bs_marks = [], {}, []

    for tag, e in frames:
        t = ts_of(tag)
        if not isinstance(e, dict):
            continue
        ptype = norm_type(e.get("页面类型"))
        name = (e.get("股票名") or "").strip() or None
        key = name if (name and ptype in ("分时", "K线", "盘口")) else f"#{ptype}"
        if cur and cur["key"] == key:
            cur["t_end"] = t
            cur["frames"] += 1
            if e.get("最新价") is not None:
                cur["最新价"] = e.get("最新价")
                cur["涨跌幅%"] = e.get("涨跌幅%")
            if e.get("图上买卖标记"):
                cur["bs"].append((t, e["图上买卖标记"]))
        else:
            if cur:
                segments.append(cur)
            cur = {"key": key, "股票名": name, "页面类型": ptype,
                   "t_start": t, "t_end": t, "frames": 1,
                   "最新价": e.get("最新价"), "涨跌幅%": e.get("涨跌幅%"),
                   "bs": [(t, e["图上买卖标记"])] if e.get("图上买卖标记") else []}
        hd = e.get("持仓明细")
        if ptype == "持仓" and isinstance(hd, list) and hd:
            positions.append({"t": t, "明细": hd})
        wl = e.get("自选股清单")
        items = re.split(r"[,，、\s]+", wl) if isinstance(wl, str) and wl else \
            (wl if isinstance(wl, list) else [])
        for n in items:
            n = str(n).strip()
            if 2 <= len(n) <= 6:
                watchlist[n] = watchlist.get(n, 0) + 1
    if cur:
        segments.append(cur)

    for s in segments:  # 驻留秒 = 段内首尾差 + 3(采样间隔); 单帧段记 3s 下限
        s["驻留秒"] = max(3.0, round(s["t_end"] - s["t_start"] + 3, 1))
        for t, bs in s.pop("bs"):
            bs_marks.append({"t": t, "股票": s["股票名"], "页面": s["页面类型"], "描述": bs})

    attn = {}  # 注意力榜: 个股页按票聚合驻留
    for s in segments:
        if s["股票名"]:
            a = attn.setdefault(s["股票名"], {"驻留秒": 0, "页面": set(),
                                              "最新价": s["最新价"], "涨跌幅%": s["涨跌幅%"]})
            a["驻留秒"] += s["驻留秒"]
            a["页面"].add(s["页面类型"])
            if s["最新价"] is not None:
                a["最新价"] = s["最新价"]
                a["涨跌幅%"] = s["涨跌幅%"]
    attention = sorted(
        ({"股票": k, "驻留秒": v["驻留秒"], "页面": sorted(v["页面"]),
          "最新价": v["最新价"], "涨跌幅%": v["涨跌幅%"]} for k, v in attn.items()),
        key=lambda r: -r["驻留秒"])

    return {
        "页面段": [{k: v for k, v in s.items() if k != "key"} for s in segments],
        "注意力榜": attention,
        "BS买卖点": bs_marks,
        "持仓快照": max(positions, key=lambda p: len(p["明细"]), default=None),
        "自选股清单": [{"名称": n, "帧数": c} for n, c in
                     sorted(watchlist.items(), key=lambda kv: -kv[1])],
        "页面类型分布": {t: sum(1 for s in segments if s["页面类型"] == t)
                       for t in ("分时", "K线", "盘口", "自选股", "持仓", "成交", "资讯", "其他")},
    }


# ---------- 持仓高亮检测(像素级, 不用 VLM 零幻觉): 同花顺自选股 持仓股名=紫色, 普通=灰黑
_OCR = None


def _shared_ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def is_purple_name(img, box):
    """名字 bbox 内笔画像素: 紫=(R-G)+(B-G)>40 (实测紫~(128,88,128), 灰~(120,120,120))"""
    x0, x1 = int(min(p[0] for p in box)), int(max(p[0] for p in box))
    y0, y1 = int(min(p[1] for p in box)), int(max(p[1] for p in box))
    pur = tot = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = img.getpixel((x, y))
            if r > 200 and g > 200 and b > 200:
                continue
            tot += 1
            if (r - g) + (b - g) > 40:
                pur += 1
    return tot >= 30 and pur / tot > 0.3


UI_WORDS = {"全部", "编辑", "最新", "涨幅", "涨速", "资金", "新闻", "公告", "资产",
            "首页", "行情", "自选", "交易", "资讯", "同花顺", "自选编辑"}


def detect_held(fdir: Path, doc):
    """扫自选股/列表帧, 紫色名字投票 -> [{名称, 紫帧, 灰帧}](只报见过紫帧的)。帧已删则返回空"""
    vlm = doc.get("vlm") or {}
    tags = [t for t, e in vlm.items()
            if isinstance(e, dict) and re.search(r"自选股|列表", str(e.get("页面类型") or ""))]
    if not tags or not fdir.exists():
        return []
    from PIL import Image
    votes = {}
    for tag in sorted(tags, key=ts_of):
        png = fdir / f"{tag}.png"
        if not png.exists():
            continue
        lines, _ = _shared_ocr()(str(png))
        img = Image.open(png).convert("RGB")
        seen = set()
        for box, text, score in (lines or []):
            t = str(text).strip()
            if not (2 <= len(t) <= 6 and re.match(r"^[一-鿿A-Z]+$", t)):
                continue
            if t in UI_WORDS:
                continue
            x0 = min(p[0] for p in box)
            y0 = min(p[1] for p in box)
            if x0 > 120 or y0 < 150 or t in seen:
                continue
            seen.add(t)
            v = votes.setdefault(t, {"紫帧": 0, "灰帧": 0})
            v["紫帧" if is_purple_name(img, box) else "灰帧"] += 1
    return [{"名称": n, **v} for n, v in sorted(votes.items(), key=lambda kv: -kv[1]["紫帧"])
            if v["紫帧"] > 0]


def stage_aggregate(out: Path, bvid: str, keep_frames: bool):
    """vision.json 加 pages 段; 成功后删抽帧中间产物(--keep-frames 保留)"""
    p = vision_json(out, bvid)
    doc = json.loads(p.read_text("utf-8"))
    if doc.get("pages"):
        print(f"[aggregate] skip (pages exists): {p}")
        return
    pages = build_pages(doc)
    pages["持仓高亮"] = detect_held(frames_dir(out, bvid), doc)
    doc["pages"] = pages
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    held_names = " ".join(h["名称"] for h in pages["持仓高亮"]) or "无"
    print(f"[pages] {bvid}: 段{len(pages['页面段'])} 注意力{len(pages['注意力榜'])}票 "
          f"BS{len(pages['BS买卖点'])} 持仓{'有' if pages['持仓快照'] else '无'} "
          f"自选股{len(pages['自选股清单'])} 高亮持仓[{held_names}] 分布{pages['页面类型分布']}")
    if not keep_frames:
        shutil.rmtree(frames_dir(out, bvid), ignore_errors=True)


# ---------- 模型下载(一次性; 多源: modelscope优先, hf-mirror兜底)
def download_model():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download
        print("modelscope ok:", snapshot_download("Qwen/Qwen2.5-VL-7B-Instruct", local_dir=str(MODEL_DIR)))
        return
    except Exception as e:
        print(f"modelscope fail: {e} -> fallback hf-mirror", file=sys.stderr)
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    from huggingface_hub import snapshot_download as hf_dl
    print("hf-mirror ok:", hf_dl("Qwen/Qwen2.5-VL-7B-Instruct", local_dir=str(MODEL_DIR)))


ALL_STAGES = ("asr", "correct", "vision", "aggregate")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid")
    ap.add_argument("--mp4", help="画面流路径(vision 阶段需要)")
    ap.add_argument("--m4a", help="音轨路径(asr 阶段需要)")
    ap.add_argument("--out", help="结果目录(Java 传 results/bilibili/<作者mid>/<yyyy.MM.dd>)")
    ap.add_argument("--stage", default="all",
                    help="逗号分隔: asr,correct,vision,aggregate (默认 all)")
    ap.add_argument("--keep-frames", action="store_true", help="保留抽帧中间产物(调试用)")
    ap.add_argument("--download-model", action="store_true")
    args = ap.parse_args()
    if args.download_model:
        download_model()
        return
    if not args.bvid or not args.out:
        ap.error("need --bvid and --out")
    stages = ALL_STAGES if args.stage == "all" else tuple(s.strip() for s in args.stage.split(","))
    bad = set(stages) - set(ALL_STAGES)
    if bad:
        ap.error(f"unknown stage: {bad}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bvid = args.bvid
    if "asr" in stages:
        if not args.m4a or not Path(args.m4a).exists():
            sys.exit(f"m4a not found: {args.m4a}")
        stage_asr(Path(args.m4a), out, bvid)
    if "correct" in stages:
        stage_correct(out, bvid)
    if "vision" in stages:
        if not args.mp4 or not Path(args.mp4).exists():
            sys.exit(f"mp4 not found: {args.mp4}")
        stage_vision(Path(args.mp4), out, bvid, args.keep_frames)
    if "aggregate" in stages:
        stage_aggregate(out, bvid, args.keep_frames)

    # 终检: 所求阶段的产物必须全部就位, 缺一 exit 1(Java 侧按失败处理)
    missing = []
    if "asr" in stages and not (out / f"{bvid}.raw.txt").exists():
        missing.append("raw.txt")
    if "correct" in stages and not (out / f"{bvid}.txt").exists():
        missing.append("txt")
    if "vision" in stages and not vision_json(out, bvid).exists():
        missing.append("vision.json")
    if "aggregate" in stages:
        p = vision_json(out, bvid)
        if not (p.exists() and json.loads(p.read_text("utf-8")).get("pages")):
            missing.append("pages")
    if missing:
        sys.exit(f"FAIL: missing products {missing}")
    print(f"[done] {bvid} stages={','.join(stages)} -> {out}")


if __name__ == "__main__":
    main()
