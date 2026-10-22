# -*- coding: utf-8 -*-
"""revival_check.py — 暂停中的导师 paper 链, 真人账本恢复更新时推微信提醒(只提醒, 不自动开; 10/18 用户定; 零 token)
另(10/18 成对): 还在跑的导师链, 账本连续 ≥10 个交易日没更新 → 推微信建议暂停(只建议不自动停)
判定: 某 tzzb 导师在 sys_job 里所有 paperChainHandler 任务都是暂停(status=1), 且他的账本最新净值日 ≥ 最近第 3 个交易日 → 提醒一次
去重: scripts/health/revival_state.json 记已提醒过的 (导师, 最新净值日), 同一次复活只提醒一次; 之后再停更再复活会再提醒
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/health/revival_check.py [--dry]
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name("revival_state.json")
HERMES = Path(r"C:\Users\admin\AppData\Local\hermes\hermes-agent\bin\hermes.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _wx(msg):
    """10/19 起推送统一走 scripts/hermes/wx_send.py(排版 + 微信配额退避 + 落账); 导入失败退回直接 hermes send"""
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "hermes"))
        import wx_send
        return wx_send.send(msg, src="revival_check", wait=300, verbose=False)
    except Exception:   # noqa: BLE001
        if HERMES.exists():
            subprocess.run([str(HERMES), "send", "--to", "weixin", msg], capture_output=True, timeout=60, creationflags=NOWIN)
        return "fallback"
STALE_TD = 10   # 10/18: 在跑的导师链, 账本连续 ≥10 个交易日没更新 → 建议暂停
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))


def recent_td(n=3):
    """最近第 n 个交易日(含今天若是交易日; 按工作日粗算, 节假日略宽松)"""
    d, k = dt.date.today(), 0
    while True:
        if d.weekday() < 5:
            k += 1
            if k >= n:
                return d
        d -= dt.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    try:   # 10/21 晚: 旧 paper 决策链按用户令整体停用, 新 paper(策略执行器 se_fleet)按在跑名单全体拉起, 不再看 sys_job 暂停状态 → 复活提醒只会误报"要不要恢复旧链", 跳过
        sys.path.insert(0, str(ROOT / "scripts" / "dfcf" / "paper"))
        from se_exec import flag
        if flag("SE_FLEET", "0") == "1":
            print("旧 paper 链 10/21 起整体停用, 新 paper 执行器按在跑名单全体运行; 复活检查跳过(不推微信)")
            print(json.dumps({"skipped": "SE_FLEET=1"}, ensure_ascii=False))
            return
    except Exception:   # noqa: BLE001
        pass
    import mentors as M
    import manual_backfill as mb
    cur = mb.db().cursor()
    cur.execute("select job_handler_param, status from sys_job where job_handler_name='paperChainHandler' and is_deleted=0")
    jobs = {}
    for p, s in cur.fetchall():
        sk = (p or "").split(":")[0]
        jobs.setdefault(sk, []).append((p, s))
    paused = [sk for sk, js in jobs.items() if js and all(s == 1 for _, s in js) and sk in M.ids("tzzb")]
    try:   # 10/18: 用户主动去掉不进 paper 的导师(scripts/tzzb/paper_excluded.json)不算"停更暂停", 不发复活提醒
        excl = set(json.loads((ROOT / "scripts" / "tzzb" / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded") or {})
    except (OSError, ValueError):
        excl = set()
    paused = [sk for sk in paused if sk not in excl or sk == "chong5000w"]
    cut = recent_td(3).strftime("%Y%m%d")
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    out = []
    for sk in paused:
        try:
            nav = str(json.loads((ROOT / "downloads" / "tzzb" / sk / "state.json").read_text(encoding="utf-8")).get("lastNavDate") or "")
        except (OSError, ValueError):
            continue
        if nav >= cut and state.get(sk) != nav:
            name = M.get(sk)["name"]
            msg = (f"导师复活提醒: {name}({sk}) 的同花顺账本恢复更新了(最新净值日 {nav[4:6]}-{nav[6:]}), "
                   f"他的 paper 链还暂停着({len(jobs[sk])} 个时段)。要不要恢复? 回复后主会话用应用接口开启。")
            out.append(msg)
            if not a.dry:
                try:
                    _wx(msg)
                    state[sk] = nav
                except Exception as e:   # noqa: BLE001
                    out.append(f"推送失败: {e}")
    # 10/18 用户定(与复活提醒成对): 还在跑的导师链, 账本连续 ≥ STALE_TD 个交易日没更新 → 推微信建议暂停(只建议不自动停; 同一段停更只提醒一次)
    import a_rules as AR
    today = dt.date.today().isoformat()
    for sk, js in jobs.items():
        if sk not in M.ids("tzzb") or not js or all(s == 1 for _, s in js):
            continue
        try:
            nav = str(json.loads((ROOT / "downloads" / "tzzb" / sk / "state.json").read_text(encoding="utf-8")).get("lastNavDate") or "")
        except (OSError, ValueError):
            continue
        if len(nav) != 8:
            continue
        lag = AR.count_trade_days(f"{nav[:4]}-{nav[4:6]}-{nav[6:]}", today) - 1
        key = f"stale:{sk}"
        if lag >= STALE_TD and state.get(key) != nav:
            name = M.get(sk)["name"]
            msg = (f"导师停更提醒: {name}({sk}) 的同花顺账本已连续 {lag} 个交易日没更新(最新净值日 {nav[4:6]}-{nav[6:]}), "
                   f"他的 paper 链还在跑({sum(1 for _, s in js if s != 1)} 个时段), 建议暂停。回复后主会话用应用接口暂停; 恢复更新时会再提醒。")
            out.append(msg)
            if not a.dry:
                try:
                    _wx(msg)
                    state[key] = nav
                except Exception as e:   # noqa: BLE001
                    out.append(f"推送失败: {e}")
    if not a.dry:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"暂停中的导师链: {paused or '无'}; 复活/停更提醒 {len(out)} 条")
    for m in out:
        print("  " + m)
    print("JSON:" + json.dumps({"paused": paused, "alerts": len(out)}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
