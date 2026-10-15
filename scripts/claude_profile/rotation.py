# -*- coding: utf-8 -*-
"""rotation.py — 自动化 claude -p 的多 key 轮换(2026-10-11 用户: 3 套 key 防 Claude 5h 额度窗口卡死)

用法(驱动器/桥接/蒸馏共用): from rotation import settings_args, on_window_limit, current_profile, log_use
  cmd = [claude, "-p", ...] + settings_args() + [prompt]
  撞额度窗口 → on_window_limit(): True=已切下一套立即重试 / False=全部耗尽(调用方按原逻辑等 45min)
本机轮换顺序: scripts/claude_profile/rotation.txt(逗号或换行分隔配置名, # 注释; 本机专属不进 git; 缺=不轮换, 走默认 settings)
共享状态: .rotation_state.json(多进程共享"当前用哪套 + 各套耗尽时刻"; 耗尽 5h 后视为恢复)
配置文件: 调 <dev>/switch-claude-settings/cs.mjs file <配置>(切换工具不在本项目, 10/11 用户令放 dev 目录下; 默认=本项目上一级目录/switch-claude-settings,
  可用环境变量 CLAUDE_SWITCH_DIR 覆盖; 找不到=不轮换走默认 settings) 生成 ~/.claude-profiles/<配置>.json, 以 --settings 叠加(不改 settings.json, 10/9 立法)
"""
import json, os, subprocess, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
def _find_cs():
    """切换工具位置: 环境变量 CLAUDE_SWITCH_DIR > <dev>/dev-notes/others/mini-cc-switch(10/13 两工具合并) > 旧位置(兼容未 pull 的机器)"""
    dev = HERE.parents[2]
    cands = ([Path(os.environ["CLAUDE_SWITCH_DIR"])] if os.environ.get("CLAUDE_SWITCH_DIR") else []) + \
        [dev / "dev-notes" / "others" / "mini-cc-switch", dev / "switch-claude-settings",
         dev / "dev-notes" / "others" / "switch-claude-settings"]
    for c in cands:
        if (c / "cs.mjs").exists():
            return c / "cs.mjs"
    return cands[0] / "cs.mjs"


CS = _find_cs()
ROT_FILE, STATE, USE_LOG = HERE / "rotation.txt", HERE / ".rotation_state.json", HERE / "profile_log.csv"
# 10/15: rotation.txt 里写一行 follow-settings 就开启"跟随本机默认"(首选=用户 cs 切的那套; 撞额度窗口再按名单往后切)
COOLDOWN_S = 5 * 3600
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_files = {}


FOLLOW_SETTINGS = ROT_FILE.exists() and any(l.strip() == "follow-settings" for l in ROT_FILE.read_text(encoding="utf-8").splitlines())

def profiles():
    if not ROT_FILE.exists():
        return []
    raw = ROT_FILE.read_text(encoding="utf-8")
    return [p.strip() for line in raw.splitlines() if not line.strip().startswith("#") for p in line.split(",") if p.strip() and p.strip() != "follow-settings"]


def _state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"current": None, "exhausted": {}}


def _save(s):
    tmp = STATE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE)   # 原子替换, 并发写最多丢一次切换记录, 不会读到半截


def _alive(s, p):
    return time.time() - s["exhausted"].get(p, 0) > COOLDOWN_S


def _settings_profile():
    """10/15 用户令: 自动化 claude -p 跟随本机默认(~/.claude/settings.json 现用哪套, 用户用 cs 切换的那套)。
    只读: 调 mini-cc-switch 的 `cs current`(按 key 识别), 不读写 settings 本体; 识别不出=None(退回名单顺序)"""
    if _settings_cache.get("t", 0) > time.time() - 60:
        return _settings_cache.get("p")
    p = None
    if CS and CS.exists():
        try:
            r = subprocess.run(["node", str(CS), "current"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=20, creationflags=NOWIN)
            p = (r.stdout or "").strip().splitlines()[-1].strip() if r.stdout.strip() else None
        except Exception:  # noqa: BLE001
            p = None
    _settings_cache.update(t=time.time(), p=p)
    return p


_settings_cache = {}


def current_profile():
    ps = profiles()
    if not ps:
        return None
    s = _state()
    # 跟随本机默认: 名单里有它且没撞额度窗口 → 优先用它(撞了窗口照常按名单往后切)
    fp = _settings_profile() if FOLLOW_SETTINGS else None
    if fp in ps and _alive(s, fp):
        if s.get("current") != fp:
            s["current"] = fp
            _save(s)
        return fp
    if s.get("current") in ps and _alive(s, s["current"]):
        return s["current"]
    for p in ps:   # 当前不在名单或已耗尽 → 名单里第一个可用的(优先级=名单顺序)
        if _alive(s, p):
            if s.get("current") != p:
                s["current"] = p
                _save(s)
            return p
    return s.get("current") or ps[0]


_last_used = {"p": None}   # 本进程最近一次调用实际用的配置(on_window_limit 只能标它, 见下)


def settings_args():
    p = current_profile()
    _last_used["p"] = p
    if not p:
        return []
    if p not in _files:
        if not CS.exists():
            print(f"WARN 找不到切换工具 {CS}(走默认 settings, 不轮换)")
            return []
        r = subprocess.run(["node", str(CS), "file", p], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        if r.returncode != 0 or not r.stdout.strip():
            print(f"WARN 配置 {p} 生成失败(走默认 settings): {(r.stderr or r.stdout)[-150:]}")
            return []
        _files[p] = r.stdout.strip().splitlines()[-1]
    return ["--settings", _files[p]]


def on_window_limit():
    """当前配置撞额度窗口: 记耗尽并切到下一套可用的; 全部耗尽返回 False"""
    ps = profiles()
    if not ps:
        return False
    s = _state()
    # 10/12 修竞态: 原先标"共享状态里的 current", 15 链同秒撞 glm 限流时, 先切走的进程把 current 改成 gravitex,
    # 后面的进程就把根本没用过的 gravitex/kimi-code 也标成耗尽 → 4 套全灭整体睡 45min。现只标本进程实际用的那套;
    # 若该套已被别的进程标过(已切走), 不重复标, 直接用新的 current 重试
    used = _last_used["p"] or current_profile()
    if not _alive(s, used):
        cur = current_profile()
        return bool(cur) and _alive(s, cur)
    cur = used
    s["exhausted"][cur] = time.time()
    nxt = next((p for p in ps[ps.index(cur) + 1:] + ps[:ps.index(cur)] if _alive(s, p)), None) if cur in ps else None
    s["current"] = nxt or cur
    _save(s)
    if nxt:
        print(f"⚠ 额度窗口: {cur} 已耗尽(5h 内不再用), 切到 {nxt} 立即重试")
    return bool(nxt)


def log_use(tag):
    """每次调用记一笔 用了哪套配置(事后判断某天是否混用模型)"""
    new = not USE_LOG.exists()
    with USE_LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("time,profile,tag\n")
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{current_profile() or 'default'},{tag}\n")
