# -*- coding: utf-8 -*-
"""daily_health.py — 采集/爬虫健康巡检(零 token, 10/14 建)
起因: 10/14 同花顺封 IP 6 小时、分钟线采集连续 2 天失败, 都没人主动报——用户问了才查。
巡检项(只读):
  ① 定时任务: 近 24h 每个 handler 失败次数/最近一次失败原文; 同一 handler 连续失败 ≥2 次 = 红
  ② 数据新鲜度: 各数据源"应有的最新交易日"vs 实际落盘日(cls 早报/电报 md、tzzb 各账本 lastNavDate、
     龙虎榜、涨停池、行情库日线/分钟线/竞价、B站三 UP results、盯盘 live)
  ③ 熔断/封禁标记: downloads/tzzb/_guard/ban.json 等; 当日请求计数
  ④ 应用日志: logs/inv-admin-error.log 近 24h 的 WARN/ERROR 条数与前 5 条
输出: scripts/health/reports/<日>.md(全文) + stdout 摘要(红/黄/绿); 出口 0=全绿 1=有黄 2=有红
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/health/daily_health.py [--date yyyy-MM-dd]
"""
import argparse, datetime as dt, glob, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backfill_bilibili"))
OUT = Path(__file__).resolve().parent / "reports"


def md_exists(d):
    return (ROOT / "md" / f"{d.year}S{(d.month + 2) // 3}" / f"{d.isoformat()}.md").exists()


def last_trading_day(d, include_today=True):
    x = d if include_today else d - dt.timedelta(days=1)
    for _ in range(15):
        if md_exists(x):
            return x
        x -= dt.timedelta(days=1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date)
    now = dt.datetime.now()
    td = last_trading_day(today)                                  # 今天是交易日=今天
    after_close = now.hour >= 16 or today < dt.date.today()
    expect = td if (td == today and after_close) else last_trading_day(today, include_today=False) if td == today else td
    rows, red, yellow = [], 0, 0

    def add(level, item, detail):
        nonlocal red, yellow
        red += level == "红"; yellow += level == "黄"
        rows.append((level, item, detail))

    # ① 定时任务
    try:
        import manual_backfill as mb
        cur = mb.db().cursor()
        cur.execute("select job_handler_name, status, create_time, left(job_message,200) from sys_job_log "
                    "where create_time >= now() - interval 24 hour order by id")
        by = {}
        def healed(h, s, m):
            """10/15: 15:35 收盘采集的分时段每天都"无当日逐笔"失败(通达信收盘后一段时间不给当日逐笔), 16:40 对账补采会补上;
            DONE_kline_minute 已在 = 已自愈, 不算失败(否则每天一红, 把真问题淹没)"""
            mm = re.search(r"market 入库 (\d{4}-\d\d-\d\d).*分时段失败", m or "")
            return s == 1 and h == "marketDailyHandler" and mm and (ROOT / "downloads" / "market" / mm.group(1) / "DONE_kline_minute").exists()
        for h, s, t, m in cur.fetchall():
            if healed(h, s, m):
                continue
            by.setdefault(h, []).append((s, t, m))
        for h, xs in sorted(by.items()):
            fails = [x for x in xs if x[0] == 1]
            if not fails:
                continue
            streak = 0
            for s, _, _ in reversed(xs):
                if s != 1:
                    break
                streak += 1
            lv = "红" if streak >= 2 else "黄"
            add(lv, f"任务 {h}", f"24h 失败 {len(fails)}/{len(xs)} 次, 末尾连续失败 {streak} 次; 最近: {fails[-1][1]:%m-%d %H:%M} {fails[-1][2]}")
        cur.execute("select job_name, job_handler_param from sys_job where status=0")
        active = cur.fetchall()
        # 10/15 A5 复发哨兵: 10/14 0915 链 15 条只记了 1 条日志(线程卡死不报错, 上面的"失败次数"看不到)——
        # 交易日 09:20 后比对 启用中的 0915 任务数 vs 今日 paperChainHandler 0915 日志数, 少了=红
        if md_exists(today) and (today < dt.date.today() or now.hour * 100 + now.minute >= 920):
            cur.execute("select count(*) from sys_job where status=0 and job_handler_name='paperChainHandler' and job_handler_param like '%0915%'")
            want = cur.fetchone()[0]
            # 10/15: 以当日应用日志里 0915 实际启动数为准(白天新启用的任务当天 0915 没轮到, 按"启用数"比会误报); 日志缺=退回启用数
            for lf in (ROOT / "logs" / "inv-admin.log", ROOT / "logs" / f"inv-admin.{today.isoformat()}.0.log"):
                if lf.exists():
                    st = {m for m in re.findall(rf"^{today.isoformat()} .*\[paper-trace\] (\S+):0915 start", lf.read_text(encoding="utf-8", errors="replace"), re.M)}
                    if st:
                        want = len(st)
                        break
            cur.execute("select count(*) from sys_job_log where job_handler_name='paperChainHandler' and job_handler_param like '%%0915%%' "
                        "and date(create_time)=%s", (today.isoformat(),))
            got = cur.fetchone()[0]
            if got < want:
                add("红", "0915 链调度日志缺记录", f"启用 {want} 条, 今日只记 {got} 条(A5 复发? 看 logs/inv-admin.log 的 [paper-trace] 与 jstack)")
            else:
                rows.append(("绿", "0915 链调度日志", f"{got}/{want} 条"))
    except Exception as e:  # noqa: BLE001
        add("红", "数据库", f"查 sys_job_log 失败: {e}")
        active = []

    # ② 数据新鲜度
    def fresh(item, got, want, how):
        if got is None:
            add("红", item, f"没有数据({how})")
        elif want and got < want:
            add("红" if (want - got).days >= 2 else "黄", item, f"最新 {got} < 应有 {want}({how})")
        else:
            rows.append(("绿", item, f"最新 {got}"))
    exp = expect
    # tzzb 各账本
    for f in sorted(glob.glob(str(ROOT / "downloads" / "tzzb" / "*" / "state.json"))):
        led = Path(f).parent.name
        try:
            s = json.loads(Path(f).read_text(encoding="utf-8"))
            nav = dt.datetime.strptime(s["lastNavDate"], "%Y%m%d").date() if s.get("lastNavDate") else None
        except Exception:  # noqa: BLE001
            nav = None
        if nav and exp and (exp - nav).days > 30:   # 10/15: 长期停更(冲5000w 07/06 起)=已知, 每天不该一红; 复活检查在 19:43 自愈例程
            add("黄", f"tzzb {led}", f"长期停更(最新 {nav}), 已知; 恢复更新会自动变绿")
            continue
        # 10/16 晚自愈: 今天抓取成功但同花顺 upload_time(导师本人最后一次上传)停在 lastNavDate 当天=本人没上传, 不是采集故障 → 黄
        try:
            up = json.loads((Path(f).parent / "nav_daily.json").read_text(encoding="utf-8"))["ex_data"]["upload_time"]
            up_d = dt.datetime.fromtimestamp(int(up) / 1000).date()
            fetched_today = dt.datetime.fromisoformat(s["lastFetch"].replace("Z", "+00:00")).astimezone().date() == today
        except Exception:  # noqa: BLE001
            up_d, fetched_today = None, False
        if nav and exp and nav < exp and fetched_today and up_d and up_d <= nav:
            add("黄", f"tzzb {led}", f"导师本人最后上传 {up_d}(净值停在 {nav}), 今日抓取正常=本人未更新; 停满 3 天 fetch_tzzb 会自动找其他比赛视图")
            continue
        fresh(f"tzzb {led}", nav, exp if after_close or td != today else None, "lastNavDate; 晚到账本 23:10 前为黄属正常")
    ban = ROOT / "downloads" / "tzzb" / "_guard" / "ban.json"
    if ban.exists():
        add("红", "tzzb 熔断", "同花顺封 IP 中: " + ban.read_text(encoding="utf-8")[:200].replace("\n", " "))
    # 统一请求层(10/15, scripts/lib/req_guard): 熔断中=红; 当日计数 ≥80% 预算=黄; 其余失败计数进详情
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        from req_guard import guard_status
        gs = guard_status()
        for b in gs["bans"]:
            if b.get("active"):
                add("红", f"请求层熔断 {b.get('id')}", f"{b.get('kind')} {b.get('info', '')[:120]}; {b.get('at', '')[:16]} 起至 {b.get('until', '')[:16]}(UTC)")
            else:
                add("黄", f"请求层熔断已过期 {b.get('id')}", f"冷却已过, 下次请求即探测; 原因 {b.get('info', '')[:100]}")
        for c in sorted(gs["counters"], key=lambda x: x.get("id", "")):
            n, bud = c.get("n", 0), c.get("budget") or 0
            fails = ", ".join(f"{k}={v}" for k, v in (c.get("fail") or {}).items())
            if bud and n >= 0.8 * bud:
                add("黄", f"请求层预算 {c.get('id')}", f"今日 {n}/{bud} 次(≥80%){'; 失败 ' + fails if fails else ''}")
            else:
                rows.append(("绿", f"请求层 {c.get('id')}", f"今日 {n}/{bud} 次, 成功 {c.get('ok', 0)}{'; 失败 ' + fails if fails else ''}"))
    except Exception as e:  # noqa: BLE001
        add("黄", "请求层巡检", f"读 downloads/_guard 失败: {e}")
    tz_cnt = ROOT / "downloads" / "tzzb" / "_guard" / f"requests_{dt.date.today().isoformat()}.json"
    if tz_cnt.exists():
        try:
            n = json.loads(tz_cnt.read_text(encoding="utf-8")).get("n", 0)
            add("黄", "tzzb 请求预算", f"今日 {n}/2000 次(≥80%)") if n >= 1600 else rows.append(("绿", "tzzb 请求计数", f"今日 {n}/2000 次"))
        except Exception:  # noqa: BLE001
            pass
    # 行情库
    mk =ROOT / "downloads" / "market" / (exp.isoformat() if exp else "")
    for flag in ("DONE_kline_day", "DONE_kline_minute", "DONE_auction_open", "DONE_auction_close", "DONE_security"):
        if exp and not (mk / flag).exists():
            add("红", f"行情库 {flag}", f"{exp} 缺 {flag}")
    # 10/16 晚: DONE 在不等于数据全(10/16 通达信只连上深市逐笔, 关注集 779 只缺 358 只仍写了 DONE) → 看 manifest 缺失率
    try:
        km = json.loads((mk / "manifest.json").read_text(encoding="utf-8"))["stages"]["kline_minute"]
        if km.get("symbols") and km.get("missingCount", 0) > max(20, km["symbols"] * 0.05):
            add("红", "行情库 分钟线缺失", f"{exp} 关注集 {km['symbols']} 只缺 {km['missingCount']} 只(平时个位数); 修法: collect_minute.py --date {exp} --force 后 runOnce 任务 133 重新入库")
    except Exception:  # noqa: BLE001
        pass
    # 10/17 健壮性 M19(agent③): 几条零网络补充线——都是"写了 DONE 但不完整/收尾失败没人知道"类
    try:
        if exp:
            for pf in sorted(mk.glob("PARTIAL_*")):
                add("黄", f"行情库 {pf.name}", f"{exp} 覆盖不足: {pf.read_text(encoding='utf-8')[:160]}")
            fm = json.loads((mk / "manifest.json").read_text(encoding="utf-8")).get("factor") or {}
            if fm.get("candidates", 0) > 300 or fm.get("expired"):
                add("黄", "行情库 除权因子", f"{exp} 候选 {fm.get('candidates')} 只 / 超期 {len(fm.get('expired') or [])} 只(候选爆量=快照断档, 见 refresh_factors)")
        lf = ROOT / "scripts" / "md" / "logs" / f"check_md_{(exp or today).isoformat()}.log"
        if lf.exists():
            ends = re.findall(r"===== 本轮结束: (\{.*\}) =====", lf.read_text(encoding="utf-8", errors="replace"))
            if ends:
                tf = json.loads(ends[-1]).get("tail_failed") or []
                if tf:
                    add("黄", "check md 收尾步骤失败", f"最近一轮: {', '.join(tf)}(详见 {lf.name})")
        ss = ROOT / "downloads" / "tzzb" / "_guard" / f"side_stop_{dt.date.today().isoformat()}.json"
        if ss.exists():
            add("黄", "tzzb 副线(候选/月榜)今日已停", ss.read_text(encoding="utf-8")[:160])
    except Exception as e:  # noqa: BLE001
        add("黄", "补充巡检(M19)", f"读取失败: {e}")
    # 龙虎榜 / 涨停池 / 早报
    def latest_dir(p, fmt):
        ds = []
        for x in Path(p).glob("*"):
            try:
                ds.append(dt.datetime.strptime(x.name, fmt).date())
            except ValueError:
                pass
        return max(ds) if ds else None
    fresh("龙虎榜", latest_dir(ROOT / "downloads" / "lhb", "%Y.%m.%d"), exp if now.hour >= 19 or today < dt.date.today() else None, "东财 17~18 点出齐")
    fresh("财联社涨停池", latest_dir(ROOT / "downloads" / "cls_pool", "%Y-%m-%d"), exp, "check md ztpool 步")
    fresh("财联社早报", latest_dir(ROOT / "downloads" / "cls_zaobao", "%Y-%m-%d"), td, "07:00~09:15 自动")
    # B站
    for up, mid in (("桃哥", "625315686"), ("天哥", "1372241958"), ("卢本圆", "550494308")):
        d = latest_dir(ROOT / "results" / "bilibili" / mid, "%Y.%m.%d")
        rows.append(("绿" if d and td and (td - d).days <= 3 else "黄", f"B站 {up}", f"最新视频产物 {d}(UP 不一定每天发)"))
    # 10/15 A14 监控: claude -p 当日用量(零 token, 明细 scripts/health/reports/claude_usage_<日>.md); 超线会话 >20 个=黄
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "lib" / "claude_usage_report.py"), "--date", today.isoformat()],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=0x08000000)
        uj = json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])
        (add if uj["red"] > 20 else lambda lv, it, de: rows.append(("绿", it, de)))(
            "黄", "claude -p 用量", f"会话 {uj['sessions']} 个 官方价 ${uj['cost']}, 超线会话 {uj['red']} 个(见 {Path(uj['report']).name})")
    except Exception as e:  # noqa: BLE001
        add("黄", "claude -p 用量", f"统计失败: {e}")
    # ④ 应用日志
    ef = ROOT / "logs" / "inv-admin-error.log"
    if ef.exists():
        lines = [l for l in ef.read_text(encoding="utf-8", errors="replace").splitlines() if re.match(r"\d{4}-\d\d-\d\d", l)]
        recent = [l for l in lines if l[:19] >= (now - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")]
        errs = [l for l in recent if " ERROR " in l and not (
            "分时段失败(日线已入库)" in l and (ROOT / "downloads" / "market" / (re.findall(r"\d{4}-\d\d-\d\d", l)[-1]) / "DONE_kline_minute").exists())]
        if errs:
            add("红", "应用 ERROR 日志", f"24h {len(errs)} 条; 首条: {errs[0][:160]}")
        elif recent:
            add("黄", "应用 WARN 日志", f"24h {len(recent)} 条; 首条: {recent[0][:160]}")
    else:
        add("黄", "应用日志文件", "logs/inv-admin-error.log 不存在(应用没按 logback-spring.xml 重启?)")

    OUT.mkdir(exist_ok=True)
    order = {"红": 0, "黄": 1, "绿": 2}
    rows.sort(key=lambda r: order[r[0]])
    md = [f"# 采集健康巡检 {now:%Y-%m-%d %H:%M}(应有最新交易日 {exp})", "", f"红 {red} / 黄 {yellow} / 绿 {len(rows) - red - yellow}", "",
          "| 级别 | 项 | 详情 |", "|---|---|---|"] + [f"| {lv} | {it} | {de.replace('|', '/')} |" for lv, it, de in rows]
    (OUT / f"{today.isoformat()}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    for lv, it, de in rows:
        if lv != "绿":
            print(f"[{lv}] {it}: {de}")
    print(f"JSON:{json.dumps({'red': red, 'yellow': yellow, 'report': str(OUT / (today.isoformat() + '.md'))}, ensure_ascii=False)}")
    return 2 if red else 1 if yellow else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
