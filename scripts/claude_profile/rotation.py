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


# 10/18 自动记忆开关(开关名 CLAUDE_NO_AUTOMEMORY; 默认 0=现状记忆照常读+写):
#   Claude Code 官方环境变量 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 → 不读也不写项目记忆目录(MEMORY.md 索引 26KB 不再随每次调用进上下文;
#   链间不再串味/回放读不到"未来"笔记; 全局 ~/.claude/CLAUDE.md 与用户 rules 不受影响, 只关"自动记忆"一项, 不动 ~/.claude/ 下任何 settings)
#   作用范围: 决策链(run_chain) + 走 claude_call.call 的全部自动化 claude -p(蒸馏/check md 等); 其它直调 claude 的脚本若要生效, 从 rotation 导入 automemory_env() 合并进自己的 env
def automemory_env():
    """开=给 claude 子进程注入 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1。优先级: 环境变量 CLAUDE_NO_AUTOMEMORY(=0/=1) > chain_flags.txt 同名行(默认 0=关)"""
    v = os.environ.get("CLAUDE_NO_AUTOMEMORY")
    if v not in ("0", "1"):
        try:
            for line in (HERE / "chain_flags.txt").read_text(encoding="utf-8").splitlines():
                k, _, val = line.split("#")[0].partition("=")
                if k.strip() == "CLAUDE_NO_AUTOMEMORY":
                    v = val.strip()
                    break
        except OSError:
            pass
    return {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"} if v == "1" else {}


FOLLOW_SETTINGS = ROT_FILE.exists() and any(l.strip() == "follow-settings" for l in ROT_FILE.read_text(encoding="utf-8").splitlines())
# 10/17 晚用户定: rotation.txt 写一行 manual-switch = 不自动换模型——永远用你本机当前设置那套; 撞额度窗口时推微信提醒你手动切,
#   调用方原地等(每分钟看一次设置变没变, 你一切就继续; 最多等 45 分钟再按原逻辑顺延)
MANUAL_SWITCH = ROT_FILE.exists() and any(l.strip() == "manual-switch" for l in ROT_FILE.read_text(encoding="utf-8").splitlines())

def profiles():
    if not ROT_FILE.exists():
        return []
    raw = ROT_FILE.read_text(encoding="utf-8")
    return [p.strip() for line in raw.splitlines() if not line.strip().startswith("#") for p in line.split(",") if p.strip() and p.strip() not in ("follow-settings", "manual-switch")]


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
    # 10/17 晚: 环境变量 CLAUDE_PROFILE_PIN=<配置名> 钉死一套(沙盒 A/B 要求全程同一个模型, 不跟你中途切 settings; 撞窗口也不换, 由调用方等)
    pin = os.environ.get("CLAUDE_PROFILE_PIN")
    if pin and pin in ps:
        return pin
    if MANUAL_SWITCH:   # 手动切模式: 只认本机当前设置, 不看"耗尽"标记、不按名单往后切
        fp = _settings_profile()
        return fp if fp in ps else (_state().get("current") or ps[0])
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
    if MANUAL_SWITCH and not os.environ.get("CLAUDE_PROFILE_PIN"):
        used = _last_used["p"] or current_profile()
        s["exhausted"][used] = time.time()
        _save(s)
        _wechat(f"⚠ 自动化 claude -p 撞额度窗口: {used} 用完了, 请手动切换模型(cs set <配置>); 后台在等你切, 切了 1 分钟内自动继续")
        print(f"⚠ 额度窗口: {used} 撞窗口(手动切模式), 等你切设置...")
        for _ in range(45):
            time.sleep(60)
            _settings_cache.clear()
            if _settings_profile() not in (None, used):
                print(f"检测到已切到 {_settings_profile()}, 继续")
                return True
        return False
    if os.environ.get("CLAUDE_PROFILE_PIN") in ps:   # 钉死时不切别的模型: 返回 False = 调用方按"全部耗尽"顺延等窗口
        s["exhausted"][os.environ["CLAUDE_PROFILE_PIN"]] = time.time()
        _save(s)
        print(f"⚠ 额度窗口: 钉死的 {os.environ['CLAUDE_PROFILE_PIN']} 撞窗口, 不换模型, 等窗口恢复")
        return False
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


# ---------- 10/16 用户立法(TODO §2-19): API 400 自动切回 gravitex key ----------
# 任何 claude -p(决策链/蒸馏/写 md/早报…)遇 API 400: 同一请求重试 3 次; 3 次都 400 → 把 ~/.claude/settings.json 的
# env.ANTHROPIC_AUTH_TOKEN 切到 C:\Users\admin\dev\gravitex-api-key.txt(切前备份到 ~/.claude/settings.json.bak_400_<时间>;
# 已在用 gravitex 则只告警不切), 切完/告警都推微信(hermes send, 零 token, 1 小时内同类告警只发一次)。
# 交互式 Claude Code 会话不经过这里(只管本项目的 claude -p 包装层: claude_call.call / run_chain.call_claude)
import re as _re

API400_RE = _re.compile(r"API Error:?\s*400|\b400 Bad Request\b|HTTP 400\b|invalid_request_error|status(?:Code)?[\"' :=]+400\b", _re.I)
_GRAVITEX_KEY = Path(r"C:\Users\admin\dev\gravitex-api-key.txt")
_SETTINGS = Path.home() / ".claude" / "settings.json"
_HERMES = Path(r"C:\Users\admin\AppData\Local\hermes\hermes-agent\bin\hermes.exe")
_ALERT_STAMP = ROT_FILE.parent / "api400_last_alert.txt"


AUTO_SWITCH_400 = False   # 10/16 10:56 用户: 先别上线, 先查清 400 成因 → 整套(重试 3 次+切 key)默认关闭; 改 True 才生效


def is_api400(text):
    return bool(AUTO_SWITCH_400 and text and API400_RE.search(text))


def _wechat(msg):
    try:
        last = float(_ALERT_STAMP.read_text(encoding="utf-8").split()[0]) if _ALERT_STAMP.exists() else 0
    except (OSError, ValueError):
        last = 0
    if time.time() - last < 3600 and "已切换" not in msg:   # 只告警类 1 小时内只发一次; 真切换必发
        return
    try:
        try:   # 10/19 起统一出口 wx_send(配额退避 / 落账); wait=0: 这里在 claude -p 包装层里, 不能等, 限频就进 outbox
            import sys as _sys
            _sys.path.insert(0, str(HERE.parent / "hermes"))
            import wx_send
            wx_send.send(msg, src="rotation", wait=0, verbose=False)
        except Exception:   # noqa: BLE001
            if _HERMES.exists():
                subprocess.run([str(_HERMES), "send", "--to", "weixin", msg], capture_output=True, timeout=60, creationflags=NOWIN)
        _ALERT_STAMP.write_text(f"{time.time()} {msg[:80]}", encoding="utf-8")
    except Exception:   # noqa: BLE001  推送失败不影响主流程
        pass


def on_api400(tag=""):
    """连续 3 次 400 后调用。返回 True=已切到 gravitex(调用方应再重试一次), False=没切(已在用 gravitex / 切换失败)"""
    try:
        key = _GRAVITEX_KEY.read_text(encoding="utf-8").strip()
        s = json.loads(_SETTINGS.read_text(encoding="utf-8"))
        envd = s.setdefault("env", {})
        if envd.get("ANTHROPIC_AUTH_TOKEN", "").strip() == key:
            print(f"⚠ API 400 ×3({tag}), 但本机已在用 gravitex key——只告警不切")
            _wechat(f"【PC1 告警】claude -p 连续 3 次 API 400({tag}), 本机已在用 gravitex key, 未切换, 请查网关/请求")
            return False
        bak = _SETTINGS.with_name(f"settings.json.bak_400_{datetime.now():%Y%m%d_%H%M%S}")
        bak.write_text(_SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
        envd["ANTHROPIC_AUTH_TOKEN"] = key
        _SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        _settings_cache.clear(); _files.clear()   # 让跟随逻辑立刻读到新 key
        print(f"⚠ API 400 ×3({tag}) → 已把 settings.json 切到 gravitex key(备份 {bak.name})")
        _wechat(f"【PC1】claude -p 连续 3 次 API 400({tag}), 已自动切换到 gravitex key(原配置备份 {bak.name})")
        return True
    except Exception as e:   # noqa: BLE001
        print(f"⚠ API 400 自动切 key 失败: {e}")
        _wechat(f"【PC1 告警】claude -p 连续 3 次 API 400({tag}), 自动切 gravitex key 失败: {str(e)[:80]}")
        return False
