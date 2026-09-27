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
    out.sort(key=lambda v: v["pubdate"])  # 最旧优先: 回填按时间正序推进, 历史脉络连续
    return out


# ---------- 完成判据: results 产物是唯一事实 ----------
def scan_done():
    """扫 results/bilibili/<mid>/<yyyy.MM.dd>/ 下产物:
    asr_done = <bvid>.txt 存在且非空; full_done = asr_done 且 vision.json 含 pages 段"""
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
                if json.loads(vj.read_text(encoding="utf-8")).get("pages"):
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
    args = ap.parse_args()

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

    limit = args.max if args.max > 0 else len(todo)
    n_done = n_fail = 0
    for i, v in enumerate(todo[:limit]):
        bvid = v["bvid"]
        log(f"===== [{i+1}/{min(limit, len(todo))}] {bvid} | {date_dir(v['pubdate'])} | {str(v.get('title'))[:40]}")
        if not args.ignore_window:
            wait_window(holidays)
        if not args.asr_only:
            wait_gpu()  # asr-only 是 CPU 任务(见文件头说明), 不查 GPU 才能与 cron vision 并行
        ok, info, source = process_one(v, args.asr_only)
        mark(state, bvid, "done" if ok else "fail", None if ok else info, source)
        if ok:
            n_done += 1
            log(f"OK {bvid}")
        else:
            n_fail += 1
            log(f"FAIL {bvid}: {info} (第{state['bvids'][bvid]['retries']}次)")
        # 每条之间 5-15s 随机(防 B站风控; 健壮性铁律的请求抖动在任务粒度也保一份)
        if i < min(limit, len(todo)) - 1:
            time.sleep(5 + random.random() * 10)

    log(f"本轮结束: 成功={n_done} 失败={n_fail} (累计账本见 {STATE_FILE})")


if __name__ == "__main__":
    main()
