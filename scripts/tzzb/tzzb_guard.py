# -*- coding: utf-8 -*-
"""tzzb_guard.py — 同花顺(tzzb)"副线"抓取共用正式额度与熔断的 Python 侧工具(10/17 agent③ 建)

背景: fetch_tzzb.mjs 的额度/熔断/单实例锁都放在 <--root>/_guard/ 下; 候选抓取用 --root downloads/tzzb_cand 时
  会另起一套(自己的 2000 次额度、自己的 ban.json), 等于和正式账本各算各的——10/16 晚候选抓取一口气吃满自己的 2000 次,
  同一 IP 当天对同花顺实际发了 1615+2000 次。本模块让副线(候选抓取 screen_candidates.py / 月榜 rank_monthly.mjs 的 Python 包装)
  把正式 downloads/tzzb/_guard 当唯一真源:
  1) 熔断: 正式 ban.json 在冷却期 → 副线不发请求; 副线自己判定"真封"(浏览器代发仍 Nginx 403) → 写进正式 ban.json(带 source)
  2) 额度: 副线只能用 正式当日额度(2000+budget_extra) − 已用 − 预留给正式轮次的 reserve; 用完就停
  3) 计数: 副线发出的请求数加回正式 requests_<日>.json(读-加-写, 只在正式抓取没在跑时写)
  4) 互斥: 正式 fetch.lock 被活进程持有 → 等/放弃; 副线运行期间持有正式 fetch.lock(写本进程 pid), 正式轮次撞上会 exit 1(下一轮补)
  5) 时间窗: 09:00~15:10 不发(盘中 + 用户 10/17 令 15:10 后); 15~23 点每小时 :05~:30 让给正式轮次(Java :10 抓)
  6) 副线停到次日: side_stop_<日>.json(探测仍 403 → 当天副线全停; 正式轮次不看它)
纯标准库; 不发任何网络请求。自测: python scripts/tzzb/tzzb_guard.py --selftest
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "downloads" / "tzzb" / "_guard"
BAN_COOL_H = 6            # 同 fetch_tzzb.mjs BAN_COOL_H
BASE_BUDGET = 2000        # 同 fetch_tzzb.mjs DAY_BUDGET 基数
DEFAULT_RESERVE = 600     # 留给当天剩余正式轮次(增量一轮约 250 次; 15:10 后约 2~3 轮真正有新数据)
SIDE_NOT_BEFORE = datetime(2026, 10, 17, 15, 10)   # 10/16 夜疑被封, 用户/主会话令: 10/17 15:10 前副线不发任何同花顺请求


def _today(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d")


def _read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _parse_at(s):
    """ban.json 的 at 是 JS toISOString(UTC, 带 Z) → 本地 naive datetime"""
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def banned(guard=GUARD, now=None):
    """正式熔断: 冷却期内返回 dict(含 ageH), 否则 None"""
    b = _read_json(Path(guard) / "ban.json")
    if not b or not b.get("at"):
        return None
    try:
        age_h = ((now or datetime.now()) - _parse_at(b["at"])).total_seconds() / 3600
    except (ValueError, TypeError):
        return None
    return {**b, "ageH": round(age_h, 2)} if age_h < BAN_COOL_H else None


def side_stopped(guard=GUARD, now=None):
    """副线当天停(探测仍 403 时写); 正式轮次不看它"""
    return _read_json(Path(guard) / f"side_stop_{_today(now)}.json")


def write_side_stop(why, guard=GUARD, now=None):
    p = Path(guard) / f"side_stop_{_today(now)}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": (now or datetime.now()).isoformat(timespec="seconds"), "why": why}, ensure_ascii=False), encoding="utf-8")
    return p


def probe_ok_today(guard=GUARD, now=None):
    """今天副线探测是否已通过(rank_screen.py probe 成功时写 side_probe_<日>.json)"""
    j = _read_json(Path(guard) / f"side_probe_{_today(now)}.json")
    return bool(j and j.get("ok"))


def write_probe(ok, info="", guard=GUARD, now=None):
    p = Path(guard) / f"side_probe_{_today(now)}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": (now or datetime.now()).isoformat(timespec="seconds"), "ok": bool(ok), "info": str(info)[:200]}, ensure_ascii=False), encoding="utf-8")
    return p


def write_ban(info, source, guard=GUARD, req_today=None):
    """副线判定真封 → 写正式 ban.json(格式同 fetch_tzzb.mjs: at=UTC ISO); 已有更新的熔断就不覆盖"""
    p = Path(guard) / "ban.json"
    old = banned(guard)
    if old:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    p.write_text(json.dumps({"at": at, "ledger": source, "source": source, "info": str(info)[:300], "reqToday": req_today}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def day_budget(guard=GUARD, now=None):
    extra = _read_json(Path(guard) / f"budget_extra_{_today(now)}.json", {}) or {}
    try:
        e = max(0, int(float(extra.get("extra") or 0)))
    except (TypeError, ValueError):
        e = 0
    return BASE_BUDGET + e


def used_today(guard=GUARD, now=None):
    j = _read_json(Path(guard) / f"requests_{_today(now)}.json", {}) or {}
    try:
        return int(j.get("n") or 0)
    except (TypeError, ValueError):
        return 0


def remaining(reserve=DEFAULT_RESERVE, guard=GUARD, now=None):
    """副线可用 = 正式当日额度 − 已用 − reserve(不小于 0)"""
    return max(0, day_budget(guard, now) - used_today(guard, now) - reserve)


def add_requests(n, guard=GUARD, now=None):
    """副线请求数加回正式计数(读-加-写)。调用方须保证此刻持有正式 fetch.lock(正式进程不在跑, 否则会被它的内存计数覆盖)"""
    if n <= 0:
        return used_today(guard, now)
    p = Path(guard) / f"requests_{_today(now)}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    v = used_today(guard, now) + int(n)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"n": v}), encoding="utf-8")
    os.replace(tmp, p)
    return v


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_holder(guard=GUARD):
    """正式 fetch.lock 的活持有者 pid; 无锁/死锁返回 None"""
    try:
        pid = int((Path(guard) / "fetch.lock").read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def acquire_lock(guard=GUARD, wait_s=0, poll_s=30):
    """拿正式 fetch.lock(写本进程 pid, 格式同 fetch_tzzb.mjs); 被活进程占着就等最多 wait_s 秒; 拿不到返回 False"""
    p = Path(guard) / "fetch.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        h = lock_holder(guard)
        if h is None or h == os.getpid():
            p.write_text(str(os.getpid()), encoding="utf-8")
            return True
        if time.time() - t0 >= wait_s:
            return False
        time.sleep(poll_s)


def release_lock(guard=GUARD):
    p = Path(guard) / "fetch.lock"
    try:
        if int(p.read_text(encoding="utf-8").strip() or 0) == os.getpid():
            p.unlink()
    except (OSError, ValueError):
        pass


def window_ok(now=None):
    """(可发, 原因)。09:00~15:10 不发; 15~23 点每小时 :05~:30 让给正式轮次"""
    t = now or datetime.now()
    if t < SIDE_NOT_BEFORE:
        return False, f"{SIDE_NOT_BEFORE:%m-%d %H:%M} 前副线不发同花顺请求(10/16 夜疑被封)"
    hm = t.hour * 100 + t.minute
    if 900 <= hm < 1510 and os.environ.get("TZZB_ALLOW_INTRADAY") != t.strftime("%Y-%m-%d"):   # 10/22 13:28 用户特许当天盘中可请求: 环境变量 = 当天日期才放行, 只对本进程有效
        return False, "09:00~15:10 不发同花顺请求(盘中/用户令 15:10 后)"
    if 15 <= t.hour <= 23 and 5 <= t.minute < 30:
        return False, f"避让正式轮次(:{t.minute:02d} 在 :05~:30 窗口)"
    return True, ""


def minutes_until_blocked(now=None):
    """距下一个不可发窗口还有几分钟(用来判断"这个账本跑得完再开")"""
    t = now or datetime.now()
    for k in range(0, 24 * 60):
        ok, _ = window_ok(t + timedelta(minutes=k))
        if not ok:
            return k
    return 24 * 60


def preflight(reserve=DEFAULT_RESERVE, need=1, now=None, guard=GUARD):
    """副线发请求前总闸: 返回 (ok, 原因, 可用额度)"""
    b = banned(guard, now)
    if b:
        return False, f"正式熔断冷却中({b.get('at')}, 已 {b['ageH']}h/{BAN_COOL_H}h, {str(b.get('info'))[:80]})", 0
    s = side_stopped(guard, now)
    if s:
        return False, f"副线今日已停({s.get('why')})", 0
    ok, why = window_ok(now)
    if not ok:
        return False, why, 0
    rem = remaining(reserve, guard, now)
    if rem < need:
        return False, f"正式额度不足: 额度 {day_budget(guard, now)} 已用 {used_today(guard, now)} 预留 {reserve} → 副线可用 {rem} < 需要 {need}", rem
    h = lock_holder(guard)
    if h and h != os.getpid():
        return False, f"正式抓取在跑(fetch.lock pid {h})", rem
    return True, "", rem


def _selftest():
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="tzzb_guard_st_"))
    now = datetime(2026, 10, 17, 16, 40)
    # 额度: 无文件=2000; extra=600 → 2600; 已用 1615 → reserve 600 后剩 385
    assert day_budget(d, now) == 2000
    (d / "budget_extra_2026-10-17.json").write_text('{"extra":600}', encoding="utf-8")
    (d / "requests_2026-10-17.json").write_text('{"n":1615}', encoding="utf-8")
    assert day_budget(d, now) == 2600 and remaining(600, d, now) == 385
    assert add_requests(15, d, now) == 1630 and used_today(d, now) == 1630
    # 时间窗
    assert window_ok(datetime(2026, 10, 17, 14, 59))[0] is False
    assert window_ok(datetime(2026, 10, 17, 2, 0))[0] is False         # SIDE_NOT_BEFORE 之前
    assert window_ok(datetime(2026, 10, 17, 15, 10))[0] is False      # :05~:30 让正式
    assert window_ok(datetime(2026, 10, 17, 15, 31))[0] is True
    assert window_ok(datetime(2026, 10, 17, 23, 50))[0] is True
    assert window_ok(datetime(2026, 10, 18, 2, 10))[0] is True
    assert minutes_until_blocked(datetime(2026, 10, 17, 15, 31)) == 34
    # 熔断: 5h 前=冷却中; 7h 前=过期
    utc5 = datetime.fromtimestamp(datetime(2026, 10, 17, 11, 40).timestamp(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    (d / "ban.json").write_text(json.dumps({"at": utc5, "info": "t"}), encoding="utf-8")
    assert banned(d, now) and preflight(600, 1, now, d)[0] is False
    utc7 = datetime.fromtimestamp(datetime(2026, 10, 17, 9, 30).timestamp(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    (d / "ban.json").write_text(json.dumps({"at": utc7, "info": "t"}), encoding="utf-8")
    assert banned(d, now) is None
    # preflight: 额度够、窗口外、无锁 → ok
    ok, why, rem = preflight(600, 1, now, d)
    assert ok, why
    assert preflight(600, 10000, now, d)[0] is False
    # 副线停
    write_side_stop("probe 403", d, now)
    assert preflight(600, 1, now, d)[0] is False
    # 探测标记
    assert not probe_ok_today(d, now)
    write_probe(True, "t", d, now)
    assert probe_ok_today(d, now)
    # 锁: 写自己 pid → holder=自己; 死 pid → None
    assert acquire_lock(d) and lock_holder(d) == os.getpid()
    release_lock(d)
    assert not (d / "fetch.lock").exists()
    (d / "fetch.lock").write_text("99999999", encoding="utf-8")
    assert lock_holder(d) is None
    # write_ban 不覆盖冷却中的
    (d / "ban.json").unlink()
    write_ban("x", "selftest", d)
    first = (d / "ban.json").read_text(encoding="utf-8")
    write_ban("y", "selftest2", d)
    assert (d / "ban.json").read_text(encoding="utf-8") == first and banned(d)
    print("tzzb_guard selftest PASS")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--selftest" in sys.argv:
        _selftest()
    elif "--status" in sys.argv:
        ok, why, rem = preflight()
        print(json.dumps({"ok": ok, "why": why, "side_remaining": rem, "budget": day_budget(), "used": used_today(),
                          "ban": banned(), "side_stop": side_stopped(), "lock": lock_holder()}, ensure_ascii=False, default=str))
    else:
        print(__doc__)
