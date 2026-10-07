# -*- coding: utf-8 -*-
"""llm_batch_tzzb.py — tzzb 六账本【推测】层批量初稿(2026-10-07 建, 第一梯队本地化落点②)

分工(用户 10/7 定): qwen3:32b 错峰跑推测层**初稿**(零 Claude token); 复核/定稿归日常链
tzzb-skill(sum) 的 Claude 会话。与已收官退役的 sweep_tzzb_spec.py(headless claude 5日/批)
同位替代: 云端批量 → 本地批量。

口径(全部沿用 gen_tzzb_md.mjs 立法, 禁另立):
  md 路径 = md/{年}S{季}/{日}.md; 小节 = #### <ledger name>(空白不敏感比对);
  推测层状态 = 小节内首个含【推测】行到小节末(内容即状态, 无账本文件);
  本脚本只在"硬数据在、【推测】缺"的小节追加: 空行 + 【推测】头 + "- "列表条目。

护栏:
  ①32B 与 VLM-7B 互斥(24G 卡装不下两份)——启动闸查 nvidia-smi, 显存占用>6G=VLM 在跑,
    推测初稿=错峰任务, 直接 exit 2 让路(--ignore-gpu 可强闯);
  ②初稿每条尾部程序化加 " (32B初稿)" 标记——复核时 grep 即得, 不冒充 Claude 产物;
  ③ollama 故障=该日跳过留账, 不写半截(内容即状态, 重跑幂等)。

用法(全自动脚本调用, 无需手动):
  scripts/venv/Scripts/python.exe scripts/tzzb/llm_batch_tzzb.py --dry          # 全账本干跑(只打印)
  scripts/venv/Scripts/python.exe scripts/tzzb/llm_batch_tzzb.py               # 全账本补缺
  scripts/venv/Scripts/python.exe scripts/tzzb/llm_batch_tzzb.py --ledger liuyiqing --from 2026-09-01 --to 2026-09-30
开关: --local-first(缺省开, 本地优先; 接口占位) / --model qwen3:32b / --limit N / --ignore-gpu
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/tzzb/
ROOT = SCRIPT_DIR.parent.parent                       # 仓库根
sys.path.insert(0, str(ROOT / "scripts" / "models"))
from local_llm import chat, LocalLLMError  # noqa: E402

DRAFT_MARK = "(32B初稿)"
GPU_FREE_TH_MB = 6000  # 已用超此数=VLM/他模型在跑, 让路


def gpu_busy() -> bool:
    """外部占用(总用量-ollama 自驻留)>6G = VLM-7B 等在跑。ollama 冒烟后驻留的 14B/bge 不算忙
    (32B 加载时 ollama 会自动逐出它们腾位)。查不到=放行(保守, ollama 自己会报 OOM)。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        used = int(r.stdout.strip().splitlines()[0])
    except Exception:
        return False
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as w:
            held = sum(int(m.get("size_vram", 0)) // 1024 // 1024
                       for m in json.loads(w.read().decode("utf-8")).get("models", []))
    except Exception:
        held = 0
    return (used - held) > GPU_FREE_TH_MB


def md_path(day: str) -> Path:
    y, m = int(day[:4]), int(day[5:7])
    return ROOT / "md" / f"{y}S{(m + 2) // 3}" / f"{day}.md"


def canon(s: str) -> str:
    return re.sub(r"^#+\s*", "", s).replace(" ", "").lower()


def extract_section(lines: list, heading_canon: str):
    """返回 (start, end, sec_lines): #### 节边界(到下一个 ###/#### 前)。找不到=None。"""
    start = None
    for i, l in enumerate(lines):
        if l.startswith("####") and canon(l) == heading_canon:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("###") or lines[j].startswith("## "):
            end = j
            break
    return start, end, lines[start:end]


SYSTEM = (
    "你是投资账本行为分析师。输入是某账本某日的硬数据小节(净值行/交易腿/汇总, 全部是事实), "
    "你的任务是写【推测】层: 对该账本当日行为的动机、风格、风控做行为推断。"
    "硬性契约: ①只输出 markdown 列表条目, 每条以 '- ' 开头, 2-5 条 ②每条只推断不复述硬数据 "
    "(硬数据读者自己看得见) ③每条句末必须带 '(锚点: ...)' 指明依据哪行硬数据(时间戳/价格/数量/汇总计数) "
    "④禁预测未来行情, 只做当日行为归因 ⑤无操作日就推断其不动的原因与持仓结构含义 "
    "⑥拿不准的推测要显式写'存疑'。只输出条目本身, 不要任何前言后语。"
)


def draft_one(model: str, hard_lines: list, ledger: str) -> list:
    extra = ("\n注意: 该账本疑似程序化交易, 涉及分批等差/时间切片特征的条目句末加 '(程序化嫌疑)'。"
             if ledger == "lianghuaxiaohao" else "")
    out = chat(model, "\n".join(hard_lines), system=SYSTEM + extra, timeout=900, temperature=0.3)
    bullets = []
    for l in out.splitlines():
        l = l.strip().lstrip("-").strip()
        if not l or l.startswith("```"):
            continue
        if not (l.endswith(")") or l.endswith("）")):
            continue  # 锚点契约不过=整条拒收(半/全角括号都认)
        bullets.append(l)
    return bullets[:5]


def main():
    ap = argparse.ArgumentParser(description="tzzb 推测层本地批量初稿(qwen3:32b, 零云端 token)")
    ap.add_argument("--ledger", default="all", help="账本 id 或 all(缺省)")
    ap.add_argument("--from-date", dest="frm", default="", help="YYYY-MM-DD(含)")
    ap.add_argument("--to-date", dest="to", default="", help="YYYY-MM-DD(含)")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 天(0=不限)")
    ap.add_argument("--dry", action="store_true", help="只打印不写 md")
    ap.add_argument("--model", default="qwen3:32b")
    ap.add_argument("--local-first", action="store_true", default=True,
                    help="本地模型优先(缺省即开; 接口占位——本脚本本就无云端路径, 云端定稿走日常链)")
    ap.add_argument("--ignore-gpu", action="store_true", help="跳过显存错峰闸(强闯)")
    args = ap.parse_args()

    ledgers = json.loads((SCRIPT_DIR / "tzzb_ledgers.json").read_text(encoding="utf-8"))
    # 负样本闸(10/7 用户立法): kind=neg 无 md 层 → 不产推测初稿, 省本地算力
    if args.ledger != "all":
        ledgers = [l for l in ledgers if l["ledger"] == args.ledger]
        if not ledgers:
            sys.exit(f"未知 ledger: {args.ledger}")
        if ledgers[0].get("kind") == "neg":
            sys.exit(f"{args.ledger} 是负样本(kind=neg), 无 md 推测层(10/7 立法)")
    else:
        _neg = [l["ledger"] for l in ledgers if l.get("kind") == "neg"]
        if _neg:
            ledgers = [l for l in ledgers if l.get("kind") != "neg"]
            print(f"[gate] 负样本跳过(不产推测层): {','.join(_neg)}", file=sys.stderr)

    if not args.ignore_gpu and gpu_busy():
        sys.exit("exit 2: 显存占用>6G(VLM-7B 在跑?), 32B 错峰任务让路; 稍后再试或 --ignore-gpu")

    tally = {"draft": 0, "skip_has": 0, "skip_nav": 0, "skip_err": 0}
    for L in ledgers:
        nav_file = ROOT / "downloads" / "tzzb" / L["ledger"] / "nav_daily.json"
        if not nav_file.exists():
            print(f"[{L['ledger']}] 无 nav_daily.json(先 fetch_tzzb), 跳过", file=sys.stderr)
            continue
        days = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in
                (x["date"] for x in json.loads(nav_file.read_text(encoding="utf-8"))["ex_data"]["index_list"])]
        days = [d for d in days if (not args.frm or d >= args.frm) and (not args.to or d <= args.to)]
        for day in sorted(days):
            if args.limit and tally["draft"] >= args.limit:
                break
            mp = md_path(day)
            if not mp.exists():
                tally["skip_nav"] += 1
                continue
            lines = mp.read_text(encoding="utf-8").splitlines()
            sec = extract_section(lines, canon("#### " + L["name"]))
            if sec is None:
                tally["skip_nav"] += 1
                continue
            _, _, sec_lines = sec
            if any("【推测】" in l for l in sec_lines):
                tally["skip_has"] += 1
                continue
            hard = [l for l in sec_lines if l.strip()]
            if not any(l.startswith("净值") for l in hard):
                tally["skip_nav"] += 1
                continue
            try:
                bullets = draft_one(args.model, hard, L["ledger"])
            except LocalLLMError as e:
                print(f"[{L['ledger']} {day}] 本地模型故障: {e}", file=sys.stderr)
                tally["skip_err"] += 1
                continue
            if not bullets:
                tally["skip_err"] += 1
                print(f"[{L['ledger']} {day}] 初稿 0 条过契约, 留账", file=sys.stderr)
                continue
            marked = [f"- {b} {DRAFT_MARK}" if not b.endswith(DRAFT_MARK) else f"- {b}" for b in bullets]
            print(f"[{L['ledger']} {day}] 初稿 {len(marked)} 条:")
            for b in marked:
                print("  " + b)
            tally["draft"] += 1
            if args.dry:
                continue
            # 挂载: 小节末(去尾空行)追加 空行+【推测】头+条目(与 gen_tzzb_md 的保留语义兼容)
            # 10/7 晚修: 追加块尾部补空行, 否则推测条目直接撞下一节标题(31 文件格式事故)
            s, e, _ = sec
            while e > s and not lines[e - 1].strip():
                e -= 1
            tail = [""] if e < len(lines) and re.match(r'^#{1,4} ', lines[e]) else []
            lines[e:e] = ["", "【推测】"] + marked + tail
            mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:  # 批完立即卸载 32B(keep_alive 驻留 5min 会卡后续 VLM/14B 任务, 10/7)
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:11434/api/generate",
                               data=json.dumps({"model": args.model, "keep_alive": 0}).encode(), timeout=10)
    except Exception:
        pass
    print(f"总账: {json.dumps(tally, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
