# 桃哥 B站视频历史回填(2026-09-27 新建; 只新增文件, 不动在跑系统)
# 业务: 把 2025-01-07 以来的桃哥历史视频(格式化 stocks md 的起点)批量补齐成结果产物
#       (txt 纠错逐字稿 + vision.json 页面行为真值), 供后续 Claude 批量会话回写 stocks md。
# 数据流: backfill_taoge/index.json(待办源) - results 扫描(已完成) = 待办
#         → 逐条: 时间窗守卫 → GPU 守卫 → node 下载 → process_video.py 全阶段 → state 记账
# 判真: results 产物是唯一事实(<bvid>.txt 存在 且 vision.json 含 pages 段 = 完成);
#       state.json 只是加速账本(记 fail 次数防无限重试 + 原料来源 复用/新下), 崩溃重跑以扫描为准。
# 队列优先级(2026-09-27 用户拍板): stocks/ 已写 ### 桃哥 小节的 229 个日期对应的视频排最前(语料价值最高)。
# 原料复用(2026-09-27 用户拍板): 下载前先查 scripts/plan-a/downloads/{,audio,video} 残留的老 m4a/mp4/json,
#       存在则硬链(失败退复制)到约定路径, 跳过重新下载, 只在缺料时才调 fetch_bilibili_taoge.mjs。
# 与 cron 的冲突规避(本机单卡 4090 24G, 单视频 vision 吃 ~15.4G):
#   1) 时间窗: 工作日 00:30-18:00 / 周末节假日 02:00-10:00 才干活, 其余时间睡觉
#      (cron 在 15:30-23:30 整点半跑增量; 窗口刻意避开晚间高优先级增量 + 白天用户看盘时段)
#   2) GPU 守卫: 每条视频开跑前查 nvidia-smi 显存 >6000MiB 即睡 5 分钟重查, 直到空闲
#   --asr-only 快速通道: 只下载+asr,correct(whisper CPU int8 不占显存, 见 process_video.py stage_asr),
#      故跳过 GPU 守卫, 可与 cron 的 vision 并行——这正是它的设计目的(用户要补全历史逐字稿语料)。
# 用法(scripts/venv/Scripts/python.exe, cwd 任意):
#   python scripts/backfill_taoge.py --dry-run          # 只打印待办清单和估计时长
#   python scripts/backfill_taoge.py                    # 长期挂机: 窗口内工作, 窗口外睡觉
#   python scripts/backfill_taoge.py --max 5            # 本次最多处理 5 条(调试)
#   python scripts/backfill_taoge.py --asr-only         # 快速通道: 只要逐字稿
#   python scripts/backfill_taoge.py --bvid BVxxxx --ignore-window   # 指定单条/跳过时间窗(调试)
import argparse
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/
ROOT = SCRIPT_DIR.parent                              # 项目根
MID = "625315686"
INDEX_NEW = SCRIPT_DIR / "backfill_taoge" / "index.json"
INDEX_OLD = SCRIPT_DIR / "plan-a" / "downloads" / "index.json"  # merge 兜底(只读)
STATE_FILE = SCRIPT_DIR / "backfill_taoge" / "state.json"
LOG_FILE = SCRIPT_DIR / "backfill_taoge" / "backfill.log"
RESULTS = ROOT / "results" / "bilibili" / MID
DOWNLOADS = ROOT / "downloads" / "bilibili" / MID
FETCH_JS = SCRIPT_DIR / "fetch_bilibili_taoge.mjs"
PROCESS_PY = SCRIPT_DIR / "process_video.py"
VENV_PY = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
HOLIDAY_DIR = ROOT / "inv-common" / "src" / "main" / "resources" / "holiday"
# 老原料复用源(2026-09-27 用户拍板): plan-a 老管线残留的 m4a/mp4/json, 下前先查这里, 省一轮 B站请求
# 实测(9/27): audio/ 下 261 个 m4a, video/ 下 58 个 mp4, 根目录散置 6 个 m4a+json
REUSE_DIRS = [SCRIPT_DIR / "plan-a" / "downloads",
              SCRIPT_DIR / "plan-a" / "downloads" / "audio",
              SCRIPT_DIR / "plan-a" / "downloads" / "downloads"]
REUSE_MP4_DIR = SCRIPT_DIR / "plan-a" / "downloads" / "video"  # mp4 集中在这, 也并入通用扫描
# 优先级源(2026-09-27 用户拍板): stocks/ 下已写 ### 桃哥 小节的 229 个日期, md 已有但 results 原料全缺,
# 语料价值最高, 对应视频排待办最前
STOCKS_PRIORITY_GLOBS = ["2025S3", "2025S4", "2026S1", "2026S2", "2026S3"]

CUTOFF = dt.datetime(2025, 1, 7).timestamp()  # 格式化 stocks md 从 2025-01-07 开始, 之前的不回填
GPU_BUSY_MIB = 6000      # 单视频 vision 吃 ~15.4G, 卡上已有 >6G 必然是 cron/别的任务, 撞上去双杀
GPU_POLL_SEC = 300       # GPU 忙时睡 5 分钟重查
MAX_RETRY = 3            # 同一 bvid 失败 3 次沉底不再试(人工看沉底清单)
PROC_TIMEOUT = 3600      # 单视频 60min 超时强杀(正常 15-20min, 长视频留 3 倍余量)
EST_MIN_FULL = 18        # dry-run 估时: 全阶段单条 ~18min
EST_MIN_ASR = 3          # asr-only 单条 ~3min(CPU whisper small)

# results→md 自动合成(2026-09-27 用户拍板"跑完某一天的 results 就调用自己去总结写回 md"):
# 单条产物落地后, headless claude -p 按 /taoge-sum 整小节覆盖写 stocks md。
# 口径锚点(2026-09-29 用户修订): 格式/口径永远以 skills/taoge-sum/SKILL.md 最新版 +
# 最新一期已合成 md 的小节为准(总结方式更新最先体现在最新日期), 脚本不硬编码模板日期;
# headless claude 每次重新读 SKILL.md, 故口径更新零脚本改动。
# 跳过规则: 最新一期已合成 md(格式样板本身, latest_synth_date() 动态判定, 永不覆盖)。
#   (2026-09-18 原手工精修稿已于 9/27 用户指令覆盖, 备份 md_backup_2026-09-18_before.md, 现按普通日期处理;
#    2026-09-24 原定稿样板自 9/29 锚点改版后不再特保, 同样可被重合成)
#   (replay 窗口 2026-06-29~09-24 冻结令 9/27 深夜解除, 世界线已封存; 注意——窗口内 md 改写为
#    新格式后 #### 解读 小节消失, 未来重跑 A 组需 planner 适配新格式)
STOCKS = ROOT / "stocks"
MD_NEW_MARKER = "**持仓逆向"     # 新格式标记 v2(9/28 起): taoge-sum 加持仓逆向工程 bullet; 幂等守卫用,
                                # skill 口径更新后的全量重跑走 --md-force 无视该守卫(9/29 用户立法); distill 就绪闸同标
MD_TIMEOUT = 900         # headless 合成单条上限 15min(读 txt+vision.json+写 md)


# ---------- 日志: stdout + backfill.log 双写 ----------
def log(msg: str):
    line = f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # 日志写失败不致命


def sleep_interruptible(sec: float):
    """长睡切成 30s 小段, Ctrl-C 能及时响应(挂机脚本, 手动干预是常态)"""
    end = time.time() + sec
    while time.time() < end:
        time.sleep(min(30, end - time.time()))


# ---------- 节假日: fetch_holidays_cn.py 产物 {date: isOffDay}; 找不到只按周末判断 ----------
def load_holidays():
    off = {}
    if HOLIDAY_DIR.exists():
        for p in HOLIDAY_DIR.glob("*.json"):
            try:
                off.update(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as e:
                log(f"节假日文件读取失败 {p.name}: {e} (忽略该文件)")
    if not off:
        log("未找到节假日 json (inv-common/.../holiday/), 降级为只按周末判断")
    return off


def is_off_day(d: dt.date, holidays: dict) -> bool:
    """holiday-cn 的 isOffDay 已含调班(周末上班=false 也有记录), 查不到才退化为周末判断"""
    key = d.isoformat()
    if key in holidays:
        return bool(holidays[key])
    return d.weekday() >= 5


def in_window(now: dt.datetime, holidays: dict) -> bool:
    """工作日 00:30-18:00; 周末/节假日 02:00-10:00 (避开 cron 晚间增量 + 用户白天看盘)"""
    t = now.time()
    if is_off_day(now.date(), holidays):
        return dt.time(2, 0) <= t < dt.time(10, 0)
    return dt.time(0, 30) <= t < dt.time(18, 0)


def wait_window(holidays: dict):
    """睡到下一个窗口起点; 已在内则直接返回"""
    while True:
        now = dt.datetime.now()
        if in_window(now, holidays):
            return
        # 计算下一个窗口起点: 今天剩余窗口 + 未来 8 天逐天试(调班日窗口类型以当天为准)
        candidates = []
        for delta in range(0, 8):
            d = now.date() + dt.timedelta(days=delta)
            start = dt.time(2, 0) if is_off_day(d, holidays) else dt.time(0, 30)
            ts = dt.datetime.combine(d, start)
            if ts > now:
                candidates.append(ts)
        nxt = min(candidates)
        log(f"不在时间窗, 睡到 {nxt.strftime('%Y-%m-%d %H:%M')} ({'休' if is_off_day(nxt.date(), holidays) else '工'})")
        sleep_interruptible((nxt - now).total_seconds())


# ---------- GPU 守卫: >6000MiB = 有任务在用卡, 睡 5 分钟重查 ----------
def gpu_used_mib():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return int(r.stdout.strip().splitlines()[0].strip())
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        log(f"nvidia-smi 查询失败: {e} (按空闲处理, 谨慎起见不阻塞)")
    return 0  # 查询失败按空闲: nvidia-smi 挂了通常卡也没活; 且 process_video 自身会暴露冲突


def wait_gpu():
    while True:
        used = gpu_used_mib()
        if used <= GPU_BUSY_MIB:
            log(f"GPU 空闲 ({used}MiB), 开跑")
            return
        log(f"GPU 忙 ({used}MiB > {GPU_BUSY_MIB}MiB), 睡 {GPU_POLL_SEC}s 重查")
        sleep_interruptible(GPU_POLL_SEC)


# ---------- 索引: 新 index.json 为主, 旧 plan-a index merge 兜底 ----------
def load_index():
    videos = {}
    if INDEX_NEW.exists():
        arr = json.loads(INDEX_NEW.read_text(encoding="utf-8"))
        for v in arr:
            videos[v["bvid"]] = v
        log(f"索引: {INDEX_NEW.name} {len(arr)} 条")
    else:
        log(f"未找到 {INDEX_NEW} (先跑 node scripts/backfill_taoge_index.mjs 刷新索引)")
    if INDEX_OLD.exists():
        old = json.loads(INDEX_OLD.read_text(encoding="utf-8"))
        added = 0
        for bvid, v in old.items():
            if bvid not in videos:
                videos[bvid] = {"bvid": bvid, "title": v.get("title"),
                                "pubdate": v.get("pubdate"), "cid": None,
                                "duration": v.get("duration")}
                added += 1
        log(f"merge 旧索引兜底: +{added} 条 (合计 {len(videos)})")
    if not videos:
        sys.exit("索引为空: 先跑 node scripts/backfill_taoge_index.mjs")
    out = [v for v in videos.values() if v.get("pubdate") and v["pubdate"] >= CUTOFF]
    out.sort(key=lambda v: v["pubdate"], reverse=True)  # 最新优先(9/28 用户定): 新 skill 口径的总结/沉淀先覆盖近期, 临时能用上; 远月慢慢补
    return out


# ---------- 完成判据: results 产物是唯一事实 ----------
def scan_done():
    """扫 results/bilibili/<mid>/<yyyy.MM.dd>/ 下产物:
    asr_done = <bvid>.txt 存在且非空; full_done = asr_done 且 vision.json 含 ocr(或老格式 pages)段"""
    asr_done, full_done = set(), set()
    if not RESULTS.exists():
        return asr_done, full_done
    for txt in RESULTS.glob("*/*.txt"):
        stem = txt.name[:-4]  # 去 .txt; 注意排除 .raw.txt/.correct.log 靠 glob 模式天然做不到, 下面过滤
        if txt.name.endswith((".raw.txt", ".correct.log")) or not stem.startswith("BV"):
            continue
        if txt.stat().st_size == 0:
            continue
        asr_done.add(stem)
        vj = txt.with_name(f"{stem}.vision.json")
        if vj.exists():
            try:
                d = json.loads(vj.read_text(encoding="utf-8"))
                if d.get("ocr") or d.get("pages"):  # 2026-09-27 实测现行键=ocr, pages 为老格式兜底
                    full_done.add(stem)
            except (OSError, json.JSONDecodeError):
                pass  # 半个文件=未完成, 重跑补
    return asr_done, full_done


# ---------- 优先级: stocks/ 下已写 ### 桃哥 小节的日期, 对应视频排待办最前 ----------
def load_priority_dates():
    """grep -l '### 桃哥' stocks/{S3..}/*.md 的日期集合(从文件名抠, 比逐个读文件内容快)"""
    dates = set()
    stocks = ROOT / "stocks"
    for sub in STOCKS_PRIORITY_GLOBS:
        d = stocks / sub
        if not d.exists():
            continue
        for md in d.glob("*.md"):
            try:
                if "### 桃哥" in md.read_text(encoding="utf-8", errors="ignore"):
                    dates.add(dt.date.fromisoformat(md.stem))
            except (OSError, ValueError):
                continue
    if not dates:
        log("stocks 优先级清单为空(未找到 ### 桃哥 小节), 全部按时间正序")
    return dates


# ---------- 老原料复用: plan-a/downloads 残留的 m4a/mp4/json, 硬链(失败退复制)到约定路径 ----------
def reuse_raw(bvid: str, dl_dir: Path):
    """返回复用到的扩展名集合。硬链优先(同盘零拷贝), 跨盘/失败退 shutil.copy2"""
    reused = set()
    search_dirs = REUSE_DIRS + [REUSE_MP4_DIR]
    for ext in ("m4a", "mp4", "json"):
        dst = dl_dir / f"{bvid}.{ext}"
        if dst.exists() and dst.stat().st_size > 0:
            continue
        for src_dir in search_dirs:
            src = src_dir / f"{bvid}.{ext}"
            if src.exists() and src.stat().st_size > 0:
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
                reused.add(ext)
                break
    return reused


# ---------- state 账本(加速用; 真值在 results) ----------
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log("state.json 损坏, 重置(不影响判真)")
    return {"bvids": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(STATE_FILE)  # 原子替换, 防挂机中断写半个 json


def mark(state, bvid, status, err=None, source=None):
    e = state["bvids"].setdefault(bvid, {"retries": 0})
    e["status"] = status
    e["ts"] = dt.datetime.now().isoformat(timespec="seconds")
    if source:
        e["source"] = source  # 复用/新下/复用+新下: 原料来源记账(2026-09-27 用户要求)
    if status == "fail":
        e["retries"] = e.get("retries", 0) + 1
        if err:
            e["last_error"] = str(err)[:300]
    elif status == "done":
        e["retries"] = 0
        e.pop("last_error", None)
    save_state(state)


# ---------- 单条处理: 下载(node) → 处理(venv python) ----------
def date_dir(pubdate):
    return dt.datetime.fromtimestamp(pubdate).strftime("%Y.%m.%d")  # 本地时区, 与目录约定一致


def run_cmd(cmd, timeout, tag):
    log(f"run[{tag}]: {' '.join(str(c) for c in cmd)}")
    try:
        r = subprocess.run(cmd, timeout=timeout, cwd=str(ROOT))
        return r.returncode == 0, f"exit={r.returncode}"
    except subprocess.TimeoutExpired:
        # subprocess.run 超时会 kill 子进程; ffmpeg 孙进程可能短暂残留, 下一轮 GPU 守卫会拦住冲突
        return False, f"timeout>{timeout}s killed"
    except OSError as e:
        return False, f"oserror: {e}"


# ---------- results→md 自动合成: 单条产物落地后 headless claude -p 调 /taoge-sum ----------
def md_path_for(pub_date: str) -> Path:
    """stocks/<year>S<quarter>/<yyyy-MM-dd>.md; quarter=(月-1)//3+1"""
    y, m, _ = pub_date.split("-")
    return STOCKS / f"{y}S{(int(m) - 1) // 3 + 1}" / f"{pub_date}.md"


_LATEST_SYNTH = {"date": None, "checked": False}


def latest_synth_date():
    """最新一期已合成 md(含 ### 桃哥 小节)的日期 = 格式样板, 永不覆盖(锚点动态化, 2026-09-29 用户定)"""
    if _LATEST_SYNTH["checked"]:
        return _LATEST_SYNTH["date"]
    _LATEST_SYNTH["checked"] = True
    cands = []
    for md in STOCKS.glob("*/*.md"):
        try:
            dt.date.fromisoformat(md.stem)
        except ValueError:
            continue
        cands.append(md)
    for md in sorted(cands, key=lambda p: p.stem, reverse=True):
        try:
            if "### 桃哥" in md.read_text(encoding="utf-8", errors="ignore"):
                _LATEST_SYNTH["date"] = md.stem
                return md.stem
        except OSError:
            continue
    return None


def maybe_write_md(v, asr_only, sweep=False, force=False):
    """跑完某一天的 results 就调用 claude 自己总结写回 md(2026-09-27 用户拍板)。
    sweep=True 时带幂等守卫(已是新格式跳过); force=True 无视守卫强制重合成(skill 口径更新后用)。
    失败一律只 log 不阻断回填。"""
    if asr_only:
        return  # 快速通道只有逐字稿, 态2 合成等 vision 补齐后再说(vision 完成的那轮会触发)
    pub_date = dt.datetime.fromtimestamp(v["pubdate"]).strftime("%Y-%m-%d")
    latest = latest_synth_date()
    if latest and pub_date == latest:
        log(f"md 合成跳过 {pub_date}: 最新一期已合成 md(格式样板本身, 不动)")
        return
    md = md_path_for(pub_date)
    if not md.exists():
        log(f"md 合成跳过 {pub_date}: {md} 不存在(非交易日/未预建, 挂载归口不在本脚本)")
        return
    if sweep and not force:
        try:
            if MD_NEW_MARKER in md.read_text(encoding="utf-8", errors="ignore"):
                log(f"md 合成跳过 {pub_date}: 已是新格式(幂等守卫; 口径更新后重跑请加 --md-force)")
                return
        except OSError:
            return
    prompt = (f"调用 /taoge-sum 合成 {pub_date} 的桃哥视频产物进 stocks md。"
              f"该日期是历史回填日期(results 产物齐但 pendingSummary 无此行), 走批量改写分支: "
              f"原料 results/bilibili/{MID}/{date_dir(v['pubdate'])}/ 的 txt+vision.json, "
              f"口径与格式以 skills/taoge-sum/SKILL.md 最新版为准(锚点=最新一期有桃哥总结的 md 的小节格式), "
              f"整小节覆盖 {md} 的 ### 桃哥 小节——覆盖前先读旧小节交叉对比(2026-09-29 用户定): "
              f"旧小节里人工补充/纠错且 results 无法复现的信息保留并入新小节并标注来源, 其余以新合成为准; "
              f"不 curl markSummarized。")
    # --dangerously-skip-permissions: hermes 实测教训(其 MEMORY.md 9/27)——headless claude -p
    # 做文件写入会被权限审批卡死到超时; 只跑在本机仓库内、prompt 固定, 风险可控
    ok, info = run_cmd(["cmd", "/c", "claude", "-p", "--dangerously-skip-permissions", prompt], MD_TIMEOUT, "md")
    if ok:
        log(f"md 合成完成 {pub_date}")
    else:
        log(f"md 合成失败 {pub_date}: {info} (不阻断回填, 批量会话兜底)")


# ---------- md→taoge-skill 人格沉淀: 串行链第三环(2026-09-28 用户拍板) ----------
# 单 agent 串行: results→md→distill 逐日咬合; 账本幂等断点续跑; 无候选池(全量回顾自行核销); 误判一等公民
DISTILL_STATE = SCRIPT_DIR / "distill_state.json"  # {"done": ["YYYY-MM-DD", ...]}
DISTILL_TIMEOUT = 900
DISTILL_OP_LOCK = SCRIPT_DIR / "distill_op.lock"  # 单次 distill 互斥(main 内联与 sweep 旁路会并发, 9/28)
PAUSE_FILE = SCRIPT_DIR / "PAUSE"  # 存在即全链暂停(2026-09-28 用户定: 随叫随停, 说"暂停"建文件/"继续"删文件)
def ensure_single_instance(mode: str = "main"):
    """pid 锁+tasklist 活体验证: 同模式已有活实例则本实例退出; 死锁自动清。
    锁按模式分(main/md-sweep/distill-sweep)——distill-sweep 是架构内的并发旁路(看门狗发起),
    不得被 main 锁误杀(9/28 初版单锁误杀 distill-sweep 的教训); 同模式双开才是事故。"""
    lock = SCRIPT_DIR / f"backfill_instance_{mode}.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid = -1
        alive = False
        if pid > 0:
            try:
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=15)
                alive = str(pid) in r.stdout
            except (OSError, subprocess.TimeoutExpired):
                alive = True  # 证据不足保守退出
        if alive:
            print(f"{mode} 已有实例在跑(pid={pid}), 本实例退出", flush=True)
            sys.exit(0)
        lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    import atexit
    atexit.register(lambda: lock.unlink(missing_ok=True))


def wait_pause():
    """暂停闸: PAUSE 文件在就原地待命, 每 5min 报一次还活着"""
    n = 0
    while PAUSE_FILE.exists():
        if n % 10 == 0:
            log("已暂停(PAUSE 文件在), 待命中... (删 scripts/PAUSE 即继续)")
        n += 1
        time.sleep(30)


def day_full(pub_date: str) -> bool:
    """该日 results 目录每个 txt 都有 vision(ocr/pages) → 产物齐才可沉淀。
    不齐就等剩余视频(2026-09-28: 防半天多视频只沉淀到部分原料)"""
    d = RESULTS / pub_date.replace("-", ".")
    if not d.is_dir():
        return False
    txts = [f for f in d.glob("BV*.txt")
            if not f.name.endswith((".raw.txt", ".correct.log")) and f.stat().st_size > 0]
    if not txts:
        return False
    for t in txts:
        vj = t.with_name(t.name[:-4] + ".vision.json")
        try:
            j = json.loads(vj.read_text(encoding="utf-8"))
            if not (j.get("ocr") or j.get("pages")):
                return False
        except (OSError, json.JSONDecodeError):
            return False
    return True


def load_distilled() -> set:
    try:
        return set(json.loads(DISTILL_STATE.read_text(encoding="utf-8")).get("done", []))
    except (OSError, json.JSONDecodeError):
        return set()


def save_distilled(s: set):
    DISTILL_STATE.write_text(json.dumps({"done": sorted(s)}, ensure_ascii=False, indent=1), encoding="utf-8")


def maybe_distill(pub_date: str, distilled: set) -> bool:
    """md 新格式+当日产物齐 → headless claude 调 /taoge-distill 沉淀进 skills/taoge-skill/persona/。
    幂等账本; 仅当 stdout 末行哨兵 DISTILL_OK 才记账; 失败只 log 不阻断。返回 True=本日已沉淀(含此前已记)。"""
    if pub_date in distilled:
        return True
    md = md_path_for(pub_date)
    try:
        if not md.exists() or MD_NEW_MARKER not in md.read_text(encoding="utf-8", errors="ignore"):
            return False  # md 未就绪(旧格式/不存在), 等 md 钩子/清扫先跑
    except OSError:
        return False
    if not day_full(pub_date):
        log(f"distill 跳过 {pub_date}: 当日产物未齐(等剩余视频)")
        return False
    if DISTILL_OP_LOCK.exists():
        log(f"distill 跳过 {pub_date}: 另一 distill 在进行中(main 与 sweep 互斥锁, 下轮再来)")
        return False
    prompt = (f"调用 /taoge-distill 沉淀 {pub_date}。"
              f"原料: {md} 的 ### 桃哥 小节(信息截止={pub_date}, 禁用晚于该日的知识与文件)。"
              f"按 SKILL 流程先核销 rules.md 的 [待验证] 规则, 再从本日小节提取新规则/案例/语言指纹进 "
              f"skills/taoge-skill/persona/(rules.md/cases.md/profile.md/language.md), 全带证据锚点。"
              f"无货可沉淀也是正常结果。stdout 末行必须打印 DISTILL_OK {pub_date}。")
    # capture_output: 哨兵记账需要 stdout; 与 md 钩子同因带 --dangerously-skip-permissions
    log(f"run[distill]: {pub_date}")
    DISTILL_OP_LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        r = subprocess.run(["cmd", "/c", "claude", "-p", "--dangerously-skip-permissions", prompt],
                           timeout=DISTILL_TIMEOUT, cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (r.stdout or "").strip().splitlines()
        if r.returncode == 0 and tail and tail[-1].strip() == f"DISTILL_OK {pub_date}":
            distilled.add(pub_date)
            save_distilled(distilled)
            log(f"distill 完成 {pub_date}")
            return True
        err_snip = (r.stderr or "").strip().replace("\n", " ")[:200]  # 9/28: 03:18 批量 exit=1 无 stderr 可查的教训
        log(f"distill 失败 {pub_date}: exit={r.returncode} 哨兵缺失 err={err_snip} (不阻断, --distill-sweep 兜底)")
    except subprocess.TimeoutExpired:
        log(f"distill 超时 {pub_date}: >{DISTILL_TIMEOUT}s killed")
    except OSError as e:
        log(f"distill oserror {pub_date}: {e}")
    finally:
        DISTILL_OP_LOCK.unlink(missing_ok=True)
    return False


def process_one(v, asr_only):
    """返回 (ok, info, source)。source: 复用/新下/复用+新下(state 记账用)"""
    bvid, pub = v["bvid"], v["pubdate"]
    d = date_dir(pub)
    dl_dir = DOWNLOADS / d
    out_dir = RESULTS / d
    dl_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 先查老原料(2026-09-27 用户拍板): plan-a/downloads 残留的 m4a/mp4 直接硬链, 存在就跳过重新下载
    reused = reuse_raw(bvid, dl_dir)
    if reused:
        log(f"复用老原料 {bvid}: {sorted(reused)}")

    # 下载: 幂等(产物在则跳过), mp4 即使 asr-only 也下——反正以后要跑 vision, 一次下齐省一轮风控暴露
    # 但复用已齐(m4a+mp4 都在)时完全不调 node, 零 B站请求
    mp4, m4a = dl_dir / f"{bvid}.mp4", dl_dir / f"{bvid}.m4a"
    need_m4a = not (m4a.exists() and m4a.stat().st_size > 0)
    need_mp4 = not (mp4.exists() and mp4.stat().st_size > 0)
    downloaded = False
    if need_m4a or need_mp4:
        ok, info = run_cmd(["node", str(FETCH_JS), "--bvid", bvid, "--out", str(dl_dir)], 1800, "download")
        if not ok:
            return False, f"download fail: {info}", "新下"
        downloaded = True
    if not m4a.exists():
        return False, "m4a missing after download", "新下"
    if not asr_only and not mp4.exists():
        return False, "mp4 missing after download", "新下"
    source = ("复用+新下" if downloaded else "复用") if reused else "新下"

    stages = "asr,correct" if asr_only else "all"
    cmd = [str(VENV_PY), str(PROCESS_PY), "--bvid", bvid,
           "--mp4", str(mp4), "--m4a", str(m4a),
           "--out", str(out_dir), "--stage", stages]
    ok, info = run_cmd(cmd, PROC_TIMEOUT, "process")
    if not ok:
        return False, f"process fail: {info}", source
    return True, "ok", source


def main():
    ap = argparse.ArgumentParser(description="桃哥 B站视频历史回填")
    ap.add_argument("--dry-run", action="store_true", help="只打印待办和估时, 不执行")
    ap.add_argument("--max", type=int, default=0, help="本次最多处理 N 条(0=不限)")
    ap.add_argument("--asr-only", action="store_true", help="只下载+asr,correct(不占 GPU 的快速通道)")
    ap.add_argument("--bvid", help="只处理指定 bvid(调试)")
    ap.add_argument("--ignore-window", action="store_true", help="跳过时间窗守卫(调试用, 挂机勿用)")
    ap.add_argument("--md-sweep", action="store_true",
                    help="只为已完成产物补写 md(不处理视频): 钩子只在本次 OK 时触发, "
                         "钩子诞生前完成的+崩溃后被补齐的天数会漏写, 用本开关扫一轮(9/27 设计盲区补救)")
    ap.add_argument("--md-force", action="store_true",
                    help="md-sweep 用: 无视'已是新格式'幂等守卫强制重合成"
                         "(skill 口径更新后的全量重跑, 2026-09-29 用户立法)")
    ap.add_argument("--md-months", default="",
                    help="md-sweep 用: 只处理这些月份, 逗号分隔如 2026-09,2026-08"
                         "(索引本身倒序, 叠加后=先 9 月后 8 月, 2026-09-29 用户定)")
    ap.add_argument("--md-max-minutes", type=int, default=0,
                    help="md-sweep 用: 批跑时间预算, 到点停手并打印已完成/剩余清单"
                         "(0=不限; 2h 批跑节奏 2026-09-29 用户定)")
    ap.add_argument("--ignore-pause", action="store_true",
                    help="md-sweep 用: PAUSE 全局暂停期间的特许批跑"
                         "(仅限用户显式排期的任务, PAUSE 文件本身不动, 2026-09-29 起)")
    ap.add_argument("--distill-sweep", action="store_true",
                    help="只为已就绪天数补沉淀 taoge-skill(不处理视频/不写 md): "
                         "md 新格式+当日产物齐+账本未记 才触发(9/28 串行链第三环)")
    args = ap.parse_args()
    mode = "distill-sweep" if args.distill_sweep else ("md-sweep" if args.md_sweep else "main")
    ensure_single_instance(mode)  # 9/28 立法: 同模式单实例; distill-sweep 与 main 允许并发(架构内旁路)

    holidays = load_holidays()
    videos = load_index()
    asr_done, full_done = scan_done()
    done_set = asr_done if args.asr_only else full_done
    priority_dates = load_priority_dates()

    if args.bvid:
        videos = [v for v in videos if v["bvid"] == args.bvid]
        if not videos:
            sys.exit(f"{args.bvid} 不在 2025-01-07 后的索引里")

    state = load_state()
    todo, sunk = [], []
    for v in videos:
        b = v["bvid"]
        if b in done_set:
            continue
        retries = state["bvids"].get(b, {}).get("retries", 0)
        if retries >= MAX_RETRY:
            sunk.append(v)
        else:
            todo.append(v)

    # 优先级排序(2026-09-27 用户拍板): stocks md 已写 ### 桃哥 小节的日期对应的视频排最前,
    # 其余保持时间正序; 稳定排序, 优先级组内仍按 pubdate 升序
    n_pri = sum(1 for v in todo if dt.datetime.fromtimestamp(v["pubdate"]).date() in priority_dates)
    todo.sort(key=lambda v: 0 if dt.datetime.fromtimestamp(v["pubdate"]).date() in priority_dates else 1)

    mode = "asr-only" if args.asr_only else "全阶段"
    log(f"模式={mode} | 索引(2025-01-07后)={len(videos)} 已完成={len([v for v in videos if v['bvid'] in done_set])} "
        f"待办={len(todo)} (其中 stocks 优先 {n_pri}) 沉底(失败>={MAX_RETRY}次)={len(sunk)}")
    est = len(todo) * (EST_MIN_ASR if args.asr_only else EST_MIN_FULL)
    log(f"估计时长 ≈ {est}min ≈ {est/60:.1f}h")

    if sunk:
        log("沉底清单(不再自动重试, 人工核查):")
        for v in sunk:
            log(f"  {v['bvid']} | {date_dir(v['pubdate'])} | {str(v.get('title'))[:40]} | "
                f"{state['bvids'][v['bvid']].get('last_error', '')}")

    if args.dry_run:
        for v in todo[:50]:
            pri = dt.datetime.fromtimestamp(v["pubdate"]).date() in priority_dates
            log(f"  待办{'[优先]' if pri else '      '} {v['bvid']} | {date_dir(v['pubdate'])} | "
                f"{v.get('duration')}s | {str(v.get('title'))[:40]}")
        if len(todo) > 50:
            log(f"  ... 其余 {len(todo)-50} 条略")
        return

    if args.md_sweep:
        # 只补写/重写已完成天数的 md, 不碰视频处理(results 齐备=scan_done 判真, 天然不重做视频→results)
        # 范围枚举以 results 目录为唯一事实, 不走 index.json——cron/DB 管线进来的新视频不在回填索引里
        # (2026-09-29 教训: 9/28、9/29 的视频 index.json 漏收, 按索引枚举会漏天); yyyy.MM.dd 字典序=时间序
        months = {m.strip() for m in args.md_months.split(",") if m.strip()} or None
        budget = args.md_max_minutes * 60 if args.md_max_minutes > 0 else 0
        scope = []
        for d in sorted((p for p in RESULTS.glob("*") if p.is_dir()),
                        key=lambda p: p.name, reverse=True):
            try:
                pd = dt.datetime.strptime(d.name, "%Y.%m.%d").strftime("%Y-%m-%d")
            except ValueError:
                continue
            if months and pd[:7] not in months:
                continue
            bvids = [f.name[:-4] for f in d.glob("BV*.txt")
                     if not f.name.endswith(".raw.txt") and f.stat().st_size > 0]
            if not any(b in full_done for b in bvids):
                continue  # 当天没有任何一条产物齐(txt+vision), 不合成
            scope.append(({"pubdate": dt.datetime.strptime(d.name, "%Y.%m.%d").timestamp()}, pd))
        log(f"md 清扫范围: {len(scope)} 天 (月份过滤={args.md_months or '无'}, "
            f"force={args.md_force}, 时间预算={args.md_max_minutes or '不限'}min, "
            f"ignore_pause={args.ignore_pause})")
        t0 = time.time()
        done = []
        for v, pd in scope:
            if budget and time.time() - t0 > budget:
                log(f"md 清扫时间预算 {args.md_max_minutes}min 用尽, 停手")
                break
            if not args.ignore_pause:
                wait_pause()
            maybe_write_md(v, False, sweep=True, force=args.md_force)
            done.append(pd)
        remaining = [pd for _, pd in scope[len(done):]]
        log(f"md 补写清扫结束: 范围 {len(scope)} 天, 本轮处理 {len(done)} 天, 剩余 {len(remaining)} 天")
        if done:
            log(f"已完成清单: {', '.join(done)}")
        if remaining:
            log(f"剩余清单(等用户再启动): {', '.join(remaining)}")
        return

    if args.distill_sweep:
        distilled = load_distilled()
        before = len(distilled)
        dates = sorted({dt.datetime.fromtimestamp(v["pubdate"]).strftime("%Y-%m-%d") for v in videos}, reverse=True)
        for d in dates:
            wait_pause()
            maybe_distill(d, distilled)
        log(f"distill 清扫结束: 检查 {len(dates)} 天, 本轮新沉淀 {len(distilled)-before}, 账本累计 {len(distilled)}")
        return

    limit = args.max if args.max > 0 else len(todo)
    distilled = load_distilled()  # 串行链第三环账本(钩子用; 清扫走上面的独立分支)
    n_done = n_fail = 0
    for i, v in enumerate(todo[:limit]):
        bvid = v["bvid"]
        log(f"===== [{i+1}/{min(limit, len(todo))}] {bvid} | {date_dir(v['pubdate'])} | {str(v.get('title'))[:40]}")
        wait_pause()  # 随叫随停(9/28 用户定): 视频粒度暂停, 在跑的子进程跑完当前条即停
        if not args.ignore_window:
            wait_window(holidays)
        if not args.asr_only:
            wait_gpu()  # asr-only 是 CPU 任务(见文件头说明), 不查 GPU 才能与 cron vision 并行
        ok, info, source = process_one(v, args.asr_only)
        mark(state, bvid, "done" if ok else "fail", None if ok else info, source)
        if ok:
            n_done += 1
            log(f"OK {bvid}")
            maybe_write_md(v, args.asr_only)
            # 串行链第三环: md 就绪且当日产物齐则沉淀(9/28 用户拍板; 不齐则留给 --distill-sweep 兜底)
            maybe_distill(dt.datetime.fromtimestamp(v["pubdate"]).strftime("%Y-%m-%d"), distilled)
        else:
            n_fail += 1
            log(f"FAIL {bvid}: {info} (第{state['bvids'][bvid]['retries']}次)")
        # 每条之间 5-15s 随机(防 B站风控; 健壮性铁律的请求抖动在任务粒度也保一份)
        if i < min(limit, len(todo)) - 1:
            time.sleep(5 + random.random() * 10)

    log(f"本轮结束: 成功={n_done} 失败={n_fail} (累计账本见 {STATE_FILE})")


if __name__ == "__main__":
    main()
