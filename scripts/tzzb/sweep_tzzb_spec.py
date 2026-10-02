# sweep_tzzb_spec.py — 不吃土豆0 历史日【推测】层批量补写(2026-10-02)
# 口径: 只对"有成交的日"跑 headless claude 补推测层; 5 日一批省 API(144 日 → ~29 次调用)
# 状态: 小节已有【推测】行=跳过; 批后逐日内容复检记账——内容即状态, 无 state 文件, 重跑安全
# 刹车: scripts/backfill_taoge/PAUSE 存在即停(与 backfill 守护共用同一个开关)
# 用法: venv python scripts/tzzb/sweep_tzzb_spec.py [--limit N(批数)]  # 10/2 首轮回填已全量收官(144/144)
import json, random, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # investment-tool/(10/2 迁入 scripts/tzzb/)
PAUSE = ROOT / "scripts" / "backfill_taoge" / "PAUSE"  # 与 backfill 守护共用开关(10/2 归位)
LEDGER_DIR = ROOT / "downloads" / "tzzb" / "bchitudou0"
LOG = ROOT / "scripts" / "backfill_taoge" / "tzzb_spec_sweep.log"
BATCH = 5
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def md_of(day):
    y, m = day.split("-")[:2]
    return ROOT / "stocks" / f"{y}S{(int(m) + 2) // 3}" / f"{day}.md"

def has_spec(day):
    md = md_of(day)
    if not md.exists():
        return None  # 无 md, 跳过
    content = md.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"#### 不吃土豆\s*0\n(.*?)(?=\n#{2,4} |\Z)", content, re.S)
    if not m:
        return None
    return "【推测】" in m.group(1)

# ---- 有成交的日(倒序, 新的先补) ----
days = set()
for f in LEDGER_DIR.glob("change_bs_*.json"):
    for t in json.load(open(f, encoding="utf-8"))["ex_data"]["change_list"]:
        d = (t.get("trans_date") or "")[:10]
        if d:
            days.add(d)
todo = [d for d in sorted(days, reverse=True) if has_spec(d) is False]
log(f"候选有成交日 {len(days)}, 待补 {len(todo)}")

done = failed = 0
for bi in range(0, len(todo), BATCH):
    if PAUSE.exists():
        log("PAUSE 检出, 收工")
        break
    if LIMIT and bi // BATCH >= LIMIT:
        break
    batch = todo[bi:bi + BATCH]
    day_list = "、".join(batch)
    files = "、".join(str(md_of(d)) for d in batch)
    prompt = (f"调用 /tzzb-sum 的推测层规则(§3), 给以下 {len(batch)} 个交易日的 md 小节补【推测】思维逆推层: {day_list}。"
              f"每个日期对应文件: {files}(一一对应), 目标小节都是 #### 不吃土豆 0。"
              f"素材: 各小节现有硬数据 + downloads/tzzb/bchitudou0/change_bs_*.json 中 trans_date 为当日的腿原始字段"
              f"(prePositionPercent/aftPositionPercent/totalCost 等); 可对照同 md 收评/涨停分析节的当日热点(仅作背景)。"
              f"严格约束: 只准在各小节末尾追加【推测】行, 已有硬数据一行一字不许动; 每条【推测】必须带数据锚点; "
              f"推不出就少写, 不硬凑; 每日 1~4 条为宜。"
              f"全部写完后 stdout 末行打印 SPEC_BATCH_OK。")
    log(f"run[spec] 批{bi // BATCH + 1}: {day_list}")
    try:
        r = subprocess.run(["cmd", "/c", "claude", "-p", "--dangerously-skip-permissions", prompt],
                           timeout=900, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        ok = r.returncode == 0 and "SPEC_BATCH_OK" in (r.stdout or "")
        if not ok:
            err = (r.stderr or "").strip().replace("\n", " ")[:150]
            log(f"批{bi // BATCH + 1} 调用异常: exit={r.returncode} err={err}")
    except subprocess.TimeoutExpired:
        log(f"批{bi // BATCH + 1} 超时 >900s killed")
    # 内容复检(内容即状态): 不信赖哨兵, 小节里真出现【推测】才算成
    for d in batch:
        if has_spec(d):
            done += 1
            log(f"spec 完成 {d}")
        else:
            failed += 1
            log(f"spec 未成 {d} (下轮再来)")
    time.sleep(random.uniform(2, 5))
log(f"本轮结束: 补写={done} 未成={failed} (待补候选 {len(todo)})")
