# -*- coding: utf-8 -*-
"""onboard_mentor.py — 新 tzzb 导师一条命令入库(10/18 用户定: 以后新增导师默认走这套"最厚做法"; 固化 hanxiao / meiyuelu 两次入库的实际步骤)

前提(人工做, 本脚本不做): ①登记表 scripts/tzzb/tzzb_ledgers.json 已加条目(ledger/name/user_key/key/kind=pos + type/display/book/short/circle/online)
  ②抓取已完成: node scripts/tzzb/fetch_tzzb.mjs --ledger <id> --full(同花顺请求只走它, 且避开每小时 :05~:30; 本脚本**不发同花顺请求**)
步骤(顺序=实际做法; 每步幂等, 完成记 results/onboard/<id>/state.json, 断点续跑=再跑同一命令; --redo 步名 强制重做某步):
  preflight   登记表/抓取产物检查
  db_sync     应用接口 POST /api/cb/tzzb/sync?ledger=<id> + 只读核对 tzzb_record 行数(不直接写库)
  skill_skel  skills/<id>-skill/ 骨架: SKILL.md / workflows/{sum,distill}.md / persona/{rules,cases}.md(已存在不覆盖)
  md          md 补「#### <name>」小节(order_tzzb_sections --all --write) + 硬数据层回填(gen_tzzb_md --all --write); 首次先打包备份 md/
  kline       补抓导师成交过、本地无日线归档的票(kline.mjs, 行情源, 非同花顺)
  mech        零 token 机械层: gen_tzzb_profile(→profile.md v1) / mentor_fingerprint / mentor_scope / gen_horizon / gen_tzzb_cases /
              backfill_fill_minutes(fills_rt) / order_inference / case_log / hold_mining / fee_profile
  paper       books/A-<id>.json(matcher --init, 只建缺的) + 时段按真人决策事件分布算 → slot_activity.json(合并写) + sys_job 建议;
              **--apply-jobs 才经 /api/quartz/add 真加**(已存在的 <id>:HHMM 不重复加)
  daily       链日 D 的产物: pools/<D>.json(合并写) / mentor_model --predict / mentor_cards / quality_daily
  chain_md    workflows/chain.md: 由模板导师 chain.md 改名 + 能力圈/推导链/取数三处按机械统计重写(已存在不覆盖, --redo chain_md 重写)
  focus       (给了 --focus 才做) 专题逐笔明细 results/onboard/<id>/focus_legs.md(零 token), 供后面花 token 的步骤专门挖
  distill     [token] distill_history.py 全历史蒸馏 → rules.md 仍是骨架时并入(rule_time_state --write + gen_rules_index)
  thicken1    [token] thicken.py 第一轮 → 并入(已并过不重复并)
  thicken2    [token] thicken.py --pass2 第二轮 → 并入
  profile_deep[token] profile.md 深度节(【选股逻辑】【买点】【卖点】【市况应对】【盘中节奏】【T法】+ 专题节) → 并入
  finalize    gen_rules_index / gen_profile_index(--skip-token 时 --no-llm) / rule_tags / persona_versions snapshot / sync_skills
  verify      mentors 自测 / run_chain --selftest / 驱动器能载入本导师 13 个模板且无模板导师残留 / ledger_limits 能读 / matcher --once --dry / 共享文件核对
共享文件一律合并写: 整文件重生成的(mentor_scope / horizon_days / fee_profile / model_out / mentor_cards)跑前记键、跑后核对, 丢了别人的键就把旧值并回去;
  pools/<D>.json 只把本导师条目并进现有文件; slot_activity.json 只改本导师键。
成本: 花 token 的步骤前查 scripts/lib/claude_cost.csv 里 tag 以 ":<id>" 结尾的累计, 超 --budget(默认 25 美元)就停。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/onboard_mentor.py --ledger <id> [--skip-token] [--dry] [--apply-jobs]
        [--date 2026-10-19] [--focus "银行股与ETF(尤其纳指ETF)" --focus-match "银行|ETF|LOF|基金"] [--redo 步名,步名] [--only 步名,步名] [--budget 25]
      --check-shared a,b   只核对共享文件里这些导师的条目都在
零弹窗: 子进程一律 CREATE_NO_WINDOW。不做 git。
"""
import argparse
import datetime as dt
import glob
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = ROOT / "scripts" / "tzzb"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(TZ))
import mentors as M  # noqa: E402

PY = str(ROOT / "scripts" / "venv" / "Scripts" / "python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
API = "http://localhost:8888"
TEMPLATE = "hanxiao"            # chain.md / profile 深度节的格式样板导师(10/18 入库时最新的一份)
TOKEN_STEPS = ("distill", "thicken1", "thicken2", "profile_deep")
STEPS = ("preflight", "db_sync", "skill_skel", "md", "kline", "mech", "paper", "daily", "chain_md", "focus",
         "distill", "thicken1", "thicken2", "profile_deep", "finalize", "verify")
SLOT_GRID = ["0915", "0927", "0945", "1000", "1030", "1100", "1300", "1400", "1455"]
SLOT_CRON = {"0915": "0 5 8 * * ?", "0927": "0 27 9 * * ?", "0945": "0 45 9 * * ?", "1000": "0 0 10 * * ?", "1030": "0 30 10 * * ?",
             "1100": "0 0 11 * * ?", "1300": "0 0 13 * * ?", "1400": "0 0 14 * * ?", "1455": "0 35 14 * * ?"}
SLOT_NAME = {"0915": "0915盘前全链", "0927": "0927竞价纠偏", "0945": "0945早盘", "1000": "1000早盘确认", "1030": "1030上午",
             "1100": "1100上午", "1300": "1300午后", "1400": "1400下午确认", "1455": "1455尾盘"}
SLOT_MIN_SHARE, SLOT_MAX = 0.12, 6   # 盘中时段窗口决策占比 <12% 的并入前一时段; 总数(含 0915)≤6
FUND_PREFIX = ("15", "16", "50", "51", "52", "56", "58")   # 场内基金(ETF/LOF)代码段


def today():
    return dt.date.today().isoformat()


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


class Ctx:
    def __init__(self, a):
        self.a, self.id = a, a.ledger
        self.E = M.get(a.ledger)
        self.name = self.E["name"]
        self.dl = ROOT / "downloads" / "tzzb" / self.id
        self.sk = ROOT / "skills" / f"{self.id}-skill"
        self.pd = self.sk / "persona"
        self.out = ROOT / "results" / "onboard" / self.id
        self.bak = ROOT / "scripts" / "temp" / "night_bak" / f"onboard_{self.id}"
        self.out.mkdir(parents=True, exist_ok=True)
        self.bak.mkdir(parents=True, exist_ok=True)
        self.sf = self.out / "state.json"
        self.st = json.loads(self.sf.read_text(encoding="utf-8")) if self.sf.exists() else {"done": {}}
        if a.focus:
            self.st["focus"], self.st["focus_match"] = a.focus, a.focus_match
        self.focus, self.focus_match = self.st.get("focus"), self.st.get("focus_match")
        self.D = a.date or self.st.get("D") or chain_day(self.E.get("online"))
        self.st["D"] = self.D

    def save(self):
        self.sf.write_text(json.dumps(self.st, ensure_ascii=False, indent=1), encoding="utf-8")

    def sh(self, cmd, step, timeout=3600, check=True):
        """子进程(零弹窗), 输出追加到 <bak>/<step>.log; 返回 (rc, 输出)"""
        log(f"  $ {' '.join(str(c) for c in cmd)[:200]}")
        r = subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=NOWIN)
        outp = (r.stdout or "") + (r.stderr or "")
        with open(self.bak / f"{step}.log", "a", encoding="utf-8") as f:
            f.write(f"\n===== {dt.datetime.now():%m-%d %H:%M:%S} {' '.join(str(c) for c in cmd)} rc={r.returncode}\n{outp}")
        if check and r.returncode != 0:
            raise RuntimeError(f"{cmd[1] if len(cmd) > 1 else cmd[0]} rc={r.returncode}: {outp[-400:]}")
        return r.returncode, outp

    def py(self, script, *args, step, timeout=3600, check=True):
        return self.sh([PY, "-X", "utf8", script, *args], step, timeout, check)


def chain_day(online):
    """链日 D = max(登记表 online, 今天之后的下一个交易日)"""
    import a_rules as AR
    d = dt.date.today() + dt.timedelta(days=1)
    while not AR._is_trade_day_fallback(d.isoformat()):
        d += dt.timedelta(days=1)
    return max(d.isoformat(), online or "")


# ---------------- 共享文件合并写 ----------------
def _jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else None


def guard_keys(path, sub=None):
    """整文件重生成前记录旧内容; 返回 restore() → 跑完后把丢失的键并回去(新值优先)"""
    path = ROOT / path
    old = _jload(path)

    def restore():
        new = _jload(path)
        if old is None or new is None:
            return []
        o, n = (old.get(sub, {}), new.get(sub, {})) if sub else (old, new)
        lost = [k for k in o if k not in n and not k.startswith("_")]
        if lost:
            for k in lost:
                n[k] = o[k]
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  [合并] {path.name} 并回被丢的键: {lost}")
        return lost
    return restore


SHARED = [("scripts/dfcf/paper/slot_activity.json", None), ("scripts/tzzb/mentor_scope.json", None),
          ("scripts/taoge-chain/horizon_days.json", None), ("scripts/tzzb/fee_profile.json", None)]


def check_shared(ids, D):
    dated = [(f"scripts/tzzb/pools/{D}.json", "mentors"), (f"scripts/tzzb/model_out/{D}.json", "mentors")]
    loose = [f"scripts/tzzb/mentor_cards/{D}.json", f"scripts/dfcf/paper/slot_profile/{D}.json", f"scripts/dfcf/paper/t_profile/{D}.json"]
    bad = []
    for p, sub in SHARED + dated:
        d = _jload(ROOT / p) or {}
        d = d.get(sub, {}) if sub else d
        for i in ids:
            ok = i in d
            bad += [] if ok else [f"{p}:{i}"]
            print(f"{'OK     ' if ok else 'MISSING'} {p} [{i}]")
    for p in loose:
        s = (ROOT / p).read_text(encoding="utf-8") if (ROOT / p).exists() else ""
        for i in ids:
            ok = f'"{i}"' in s
            bad += [] if ok else [f"{p}:{i}"]
            print(f"{'OK     ' if ok else 'MISSING'} {p} [{i}]")
    return bad


# ---------------- 原料 ----------------
def legs(c):
    L = {}
    for f in glob.glob(str(c.dl / "change_bs_*.json")):
        for x in (json.loads(Path(f).read_text(encoding="utf-8")).get("ex_data") or {}).get("change_list") or []:
            L[(x["trans_date"], x["stock_code"], x["buy_sell"], x["trans_count"], x["trans_price"])] = x
    return sorted(L.values(), key=lambda x: x["trans_date"])


def side(x):
    return "B" if str(x.get("buy_sell")) in ("1", "3", "7") else "S"


def cost_of(i):
    f = ROOT / "scripts" / "lib" / "claude_cost.csv"
    if not f.exists():
        return 0.0
    s = 0.0
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split(",")
        if len(p) > 11 and p[1].endswith(f":{i}"):
            try:
                s += float(p[11])
            except ValueError:
                pass
    return s


# ---------------- 步骤 ----------------
def s_preflight(c):
    E = c.E
    for k in ("type", "display", "book", "short", "circle", "online"):
        if not E.get(k):
            raise RuntimeError(f"登记表条目缺字段 {k}")
    if E.get("type") != "tzzb" or E.get("kind") == "neg":
        raise RuntimeError("只支持 type=tzzb 的正样本导师")
    st = _jload(c.dl / "state.json") or {}
    if not st.get("lastNavDate") or not list(c.dl.glob("change_bs_*.json")) or not (c.dl / "day_positions.json").exists():
        raise RuntimeError(f"抓取未完成: 先跑 node scripts/tzzb/fetch_tzzb.mjs --ledger {c.id} --full(本脚本不发同花顺请求)")
    log(f"  {c.name}: 抓取 {st.get('lastFetch')} lastNavDate={st['lastNavDate']} 腿 {st.get('bsLegs')}; 链日 D={c.D}")


def s_db_sync(c):
    req = urllib.request.Request(f"{API}/api/cb/tzzb/sync?ledger={c.id}", data=b"", method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))
    log(f"  sync: {r}")
    if str(r.get("code")) != "200":
        raise RuntimeError(f"sync 失败: {r}")
    import pymysql   # 只读核对
    con = pymysql.connect(host="localhost", user="root", password="root", charset="utf8mb4", database="investment_tool")
    try:
        cur = con.cursor()
        cur.execute("select count(*) from tzzb_record where ledger=%s", (c.id,))
        n = cur.fetchone()[0]
    finally:
        con.close()
    log(f"  tzzb_record 行数(只读): {n}")
    if not n:
        raise RuntimeError("库里 0 行")
    c.st["db_rows"] = n


def s_skill_skel(c):
    E, i, n = c.E, c.id, c.name
    (c.sk / "workflows").mkdir(parents=True, exist_ok=True)
    c.pd.mkdir(parents=True, exist_ok=True)
    files = {
        c.sk / "SKILL.md": f"""---
name: {i}-skill
description: {n}(同花顺投资账本 ledger={i}, {E.get('key')}/{E.get('user_key')})人格画像与决策规则——{E.get('style') or E.get('circle')}; {today()} 入库建档(onboard_mentor.py), persona 由机械层(指纹/统计)+历史蒸馏+两轮加厚+profile 深度节填充(不编造)。
---

# {i}-skill · {n}（{today()} 建档）

- ledger={i}, 视图={E.get('key')}/{E.get('user_key')}({E.get('match', '')})
- 风格定位: {E.get('style') or E.get('circle')}
- 结构(10/7 立法): SKILL.md 薄路由 + workflows/{{sum,distill,chain}}.md(sum/distill 走 tzzb-skill 通用流) + persona/
- 按任务读 workflows/ 对应文件, 不全文载
""",
        c.sk / "workflows" / "sum.md": f"""# {n} · sum 工作流(薄路由)

> 本 ledger 的合成走 **tzzb-skill 通用流**(硬数据层 gen_tzzb_md 零 token), 固定参数 `--ledger {i}`。
> 全文契约: `skills/tzzb-skill/workflows/sum.md`(10/7 结构立法: 不复制全文防双副本漂移)。
> 10/18 起 32B【推测】层已退役, 只回填硬数据层, 不生成推测。

```bash

# 硬数据层(机械)

node scripts/tzzb/gen_tzzb_md.mjs --ledger {i} --all --write
```
""",
        c.sk / "workflows" / "distill.md": f"""# {n} · distill 工作流(薄路由)

> 反向沉淀走 **tzzb-skill 通用流**(LLM 提取型), 固定 `--ledger {i}`; 产物进本 skill persona/。
> 全文契约: `skills/tzzb-skill/workflows/distill.md`。

```bash
scripts/venv/Scripts/python.exe -X utf8 scripts/tzzb/... # 经 tzzb-skill distill 流程, --ledger {i}
```
""",
        c.pd / "rules.md": f"""# {n} · 决策规则（五闸门版, {today()} 骨架）

> 立法: 每条必须带证据锚点, 样本≥2 才进; 现零条 = 如实(未蒸馏, 不编造)。
> 填充路径: md 硬数据层(gen_tzzb_md) → distill_history.py --ledger {i} 历史蒸馏 → thicken.py 两轮加厚(onboard_mentor.py 一条命令)。

## 五闸门（准入审查, 同 buchitudou0-skill 立法）

1. 欠定承认: ≥2 竞争假设并列 2. 证据链三环: 操作→当时市况→同类先例 3. 置信度三级: 统计事实/强推断/弱猜测
4. 可证伪条款: 必须机械可判 5. 反例优先

## 规则

(冷启动, 零条)
""",
        c.pd / "cases.md": f"# {n} cases（{today()} 建档）\n\n(冷启动; 叙事案例卡由 thicken.py 两轮加厚填充, 机械双尾区由 gen_tzzb_cases.py 重生成)\n",
    }
    for p, txt in files.items():
        if p.exists():
            log(f"  已存在不覆盖: {p.relative_to(ROOT)}")
        else:
            p.write_text(txt, encoding="utf-8")
            log(f"  建 {p.relative_to(ROOT)}")


def s_md(c):
    tgz = c.bak / "md_before.tgz"
    if not tgz.exists():
        with tarfile.open(tgz, "w:gz") as t:
            t.add(ROOT / "md", arcname="md")
        log(f"  md 备份 → {tgz.relative_to(ROOT)}")
    _, o = c.py("scripts/tzzb/order_tzzb_sections.py", "--all", "--write", step="md")
    log("  " + o.strip().splitlines()[-1])
    _, o = c.sh(["node", "scripts/tzzb/gen_tzzb_md.mjs", "--ledger", c.id, "--all", "--write"], "md")
    log("  " + o.strip().splitlines()[-1])
    if "无小节" in o:
        raise RuntimeError("gen_tzzb_md 仍有「无小节」: 检查 order_tzzb_sections 是否读到登记表")


def s_kline(c):
    codes = sorted({Path(f).name.split("_")[2] for f in glob.glob(str(c.dl / "change_bs_*_p1.json"))})
    miss = [x for x in codes if not (ROOT / "downloads" / "quotes" / "daily" / f"{x}.json").exists()]
    log(f"  成交票 {len(codes)} 只, 缺日线归档 {len(miss)} 只")
    for k in range(0, len(miss), 30):
        _, o = c.sh(["node", "scripts/quotes/kline.mjs", "--codes", ",".join(miss[k:k + 30])], "kline", timeout=900, check=False)
        log("  " + (o.strip().splitlines() or ["?"])[-1])


def profile_v1(c, R):
    T = R["总量"]
    last_leg = max((x["trans_date"][:10] for x in legs(c)), default="?")
    lnav = (_jload(c.dl / "state.json") or {}).get("lastNavDate", "")
    lnav = f"{lnav[:4]}-{lnav[4:6]}-{lnav[6:]}" if len(lnav) == 8 else lnav

    def b(k):
        x = R.get(k) or {}
        return (f"- 笔数 {x.get('笔数')} | 胜率 {x.get('胜率', '—')} | 平均盈利 {x.get('平均盈利%')}% | 平均亏损 {x.get('平均亏损%')}% | "
                f"中位持仓 {x.get('中位持仓')} | 最大单亏 {x.get('最大单亏%')}%")
    L = [f"# {c.name} profile（{today()} 机械画像 v1——gen_tzzb_profile.py --ledger {c.id} 产出(results/distill_history/{c.id}/profile_stats.txt); "
         f"行为解读见 rules.md; 指纹见 fingerprint.md; 【】节=深度蒸馏）", "",
         f"> 腿 {T['腿']} · RT {T['round_trip']} · 出手日 {T['出手日']} · 空仓日 {T['空仓日']} · 标的 {T['标的']}",
         f"> 市场分布: {T['市场分布']}", f"> 窗口 {R['窗口']} · generatedAt {R['generatedAt']}",
         f"> 风格初判(入库筛选, 非统计): {c.E.get('style') or c.E.get('circle')}"]
    if last_leg < lnav:
        L.append(f"> 数据缺口: 净值记录到 {lnav}, 成交流水最新到 {last_leg}(其后的成交腿账本未上传), 成交类统计截止 {last_leg}")
    L += ["", "## 日内", b("桶_日内"), "", "## 隔夜", b("桶_隔夜"), "", "## 多日", b("桶_多日"), "", "## 亏损应对"]
    sec = [("H1_亏损应对", None), ("H2_时刻", "时刻纪律"), ("H4_熟票池", "熟票池"), ("持仓维度", "持仓维度"), ("杂项", "杂项")]
    for k, title in sec:
        if title:
            L += ["", f"## {title}"]
        for kk, v in (R.get(k) or {}).items():
            L.append(f"- {kk}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v}")
    return "\n".join(L) + "\n"


def s_mech(c):
    i = c.id
    _, o = c.py("scripts/tzzb/gen_tzzb_profile.py", "--ledger", i, step="mech")
    R = json.loads(o[o.index("{"):o.rindex("}") + 1])
    pf = c.pd / "profile.md"
    if not pf.exists():
        pf.write_text(profile_v1(c, R), encoding="utf-8")
        log("  建 profile.md v1(机械画像)")
    c.py("scripts/tzzb/mentor_fingerprint.py", "--ledger", i, step="mech", timeout=1800)
    for p, script in (("scripts/tzzb/mentor_scope.json", "scripts/tzzb/mentor_scope.py"),
                      ("scripts/taoge-chain/horizon_days.json", "scripts/taoge-chain/gen_horizon.py"),
                      ("scripts/tzzb/fee_profile.json", "scripts/tzzb/fee_profile.py")):
        restore = guard_keys(p)
        c.py(script, step="mech", timeout=1800)
        restore()
    c.py("scripts/tzzb/backfill_fill_minutes.py", "--fetch", "--features", "--ledger", i, step="mech", timeout=3600)
    c.py("scripts/tzzb/gen_tzzb_cases.py", "--ledger", i, step="mech")
    c.py("scripts/tzzb/order_inference.py", "--mentors", "--ledger", i, step="mech", timeout=1800)
    c.py("scripts/tzzb/case_log.py", "--ledger", i, step="mech", timeout=1800)
    c.py("scripts/tzzb/hold_mining.py", "--ledger", i, step="mech", timeout=1800)
    for f in ("fingerprint.md", "cases_auto.jsonl", "fills_rt.jsonl", "orders_inferred.json", "case_log/index.md"):
        if not (c.pd / f).exists():
            raise RuntimeError(f"机械层缺产物 persona/{f}")


def slot_plan(c):
    ev = {}
    for x in legs(c):
        if x["trans_date"][11:19] == "00:00:00":   # 手录腿无时刻
            continue
        ev.setdefault((x["trans_date"][:10], x["stock_code"], side(x)), x["trans_date"][11:16].replace(":", ""))
    times = list(ev.values())

    def shares(grid):
        cnt = Counter()
        for hm in times:
            if hm < "0930":
                cnt["0915"] += 1
                continue
            s = grid[1]
            for g in grid[1:]:
                if hm >= g:
                    s = g
            cnt[s] += 1
        n = max(1, len(times))
        return {g: round(cnt[g] / n, 3) for g in grid}
    grid = list(SLOT_GRID)
    while True:
        sh = shares(grid)
        cand = [g for g in grid if g not in ("0915", "0927")]
        if not cand:
            break
        g = min(cand, key=lambda x: sh[x])
        if sh[g] < SLOT_MIN_SHARE or len(grid) > SLOT_MAX:
            grid.remove(g)
        else:
            break
    full = shares(SLOT_GRID)
    return grid, shares(grid), full, len(times)


def existing_jobs(i):
    import pymysql   # 只读
    con = pymysql.connect(host="localhost", user="root", password="root", charset="utf8mb4", database="investment_tool")
    try:
        cur = con.cursor()
        cur.execute("select id, job_handler_param, cron_expression, status from sys_job where is_deleted=0 "
                    "and job_handler_name='paperChainHandler' and job_handler_param like %s", (f"{i}:%",))
        return {r[1].split(":", 1)[1]: r for r in cur.fetchall()}
    finally:
        con.close()


def s_paper(c):
    i = c.id
    bk = ROOT / "scripts" / "dfcf" / "paper" / "books" / f"{c.E['book']}.json"
    if not bk.exists():
        c.sh(["node", "scripts/dfcf/paper/matcher.mjs", "--init"], "paper")
    b = _jload(bk)
    log(f"  账本 {bk.name}: cash={b.get('cash')} 持仓 {len(b.get('positions') or {})}")
    grid, sh, full, n = slot_plan(c)
    c.st["slots"], c.st["slot_shares"], c.st["slot_full"], c.st["slot_n"] = grid, sh, full, n
    log(f"  真人决策事件 n={n}, 细网格分布: {full}")
    log(f"  建议时段: {grid} 各窗口占比 {sh}")
    sa = ROOT / "scripts" / "dfcf" / "paper" / "slot_activity.json"
    d = _jload(sa) or {}
    d[i] = sh
    sa.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    have = existing_jobs(i)
    todo = [g for g in grid if g not in have]
    log(f"  sys_job 已有 {sorted(have)}; 待加 {todo}")
    if todo and not c.a.apply_jobs:
        log("  (未给 --apply-jobs: 只给建议, 不加定时任务)")
        c.st["jobs_pending"] = todo
        return
    for g in todo:
        body = {"jobName": f"paper链-{c.E['display']}-{SLOT_NAME[g]}", "jobGroup": "PAPER_GROUP", "jobHandlerName": "paperChainHandler",
                "jobHandlerParam": f"{i}:{g}", "retryCount": 0, "retryInterval": 0, "cronExpression": SLOT_CRON[g], "misfirePolicy": 1, "status": 0,
                "remark": f"{today()} onboard_mentor.py 新导师入库, 时段按真人成交时刻分布定(决策事件=日×票×方向首笔, n={n}); "
                          f"本时段窗口决策 {sh[g] * 100:.0f}%; {c.E.get('online')} 首日"}
        req = urllib.request.Request(f"{API}/api/quartz/add", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        log(f"  add {g}: {urllib.request.urlopen(req, timeout=30).read().decode('utf-8')}")
    c.st["jobs_pending"] = []
    c.st["jobs"] = {k: v[0] for k, v in existing_jobs(i).items()}


def s_daily(c):
    D, i = c.D, c.id
    pp = ROOT / "scripts" / "tzzb" / "pools" / f"{D}.json"
    old = _jload(pp)
    c.py("scripts/tzzb/mentor_fingerprint.py", "--pool", "--date", D, "--ledger", i, step="daily", timeout=1800)
    new = _jload(pp)
    if old and new and old is not new:
        if old.get("feature_day") != new.get("feature_day"):
            log(f"  WARN pools feature_day 不同 {old.get('feature_day')} vs {new.get('feature_day')}: 仍按条目合并")
        old.setdefault("mentors", {})[i] = new["mentors"][i]
        pp.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"  pools/{D}.json 合并: {len(old['mentors'])} 位")
    for p, args in ((f"scripts/tzzb/model_out/{D}.json", ("scripts/tzzb/mentor_model.py", "--predict", "--date", D)),):
        restore = guard_keys(p, "mentors")
        c.py(*args, step="daily", timeout=1800)
        restore()
    c.py("scripts/tzzb/mentor_cards.py", "--date", D, step="daily")
    c.py("scripts/dfcf/paper/quality_daily.py", "--date", D, step="daily", timeout=1800)
    _, o = c.py("scripts/dfcf/paper/ledger_limits.py", "--show", "--asof", D, step="daily", check=False)
    row = [l for l in o.splitlines() if l.startswith(f"| {i} ")]
    log("  账本约束: " + (row[0] if row else "(没读到, 查 ledger_limits)"))


# ---- chain.md ----
def _fp_stats(c):
    t = (c.pd / "fingerprint.md").read_text(encoding="utf-8")
    sec1 = t.split("## 一、", 1)[1].split("## 二、", 1)[0] if "## 一、" in t else ""
    plays = [(m.group(1), int(m.group(2))) for m in re.finditer(r"^\| (\S+) \| (\d+)% \| \d+ \|", sec1, re.M)]
    plays = sorted([p for p in plays if p[0] != "数据缺失"], key=lambda x: -x[1])
    g = lambda pat: (re.search(pat, t) or [None, None])[1]
    return {"plays": plays, "green": g(r"买价≤昨收\(绿盘买\): (\d+)%"), "limit": g(r"在涨停价成交\(打板\): (\d+)%"),
            "mcap": g(r"\| 流通市值\(亿\) \| ([\d.]+)")}


def circle_texts(c):
    S = (_jload(ROOT / "scripts" / "tzzb" / "mentor_scope.json") or {}).get(c.id) or {}
    F = _fp_stats(c)
    pct = lambda v: f"{float(v) * 100:.0f}%"
    board = "/".join(f"{k.replace('沪深主板', '主板')} {pct(v)}" for k, v in list((S.get("board") or {}).items())[:5])
    ind = [x[0] for x in (S.get("industry") or [])[:5]]
    con = [x[0] for x in (S.get("concept") or [])[:5]]
    tops, seen = [], set()
    for x in S.get("top") or []:
        if x["code"] not in seen:
            seen.add(x["code"])
            tops.append(x["name"])
    tops = tops[:6]
    plays = F["plays"][:4]
    play_s = "/".join(f"{p} {v}%" for p, v in plays) or "样本不足"
    bt = "/".join(f"{k} {pct(v)}" for k, v in (S.get("buy_time") or {}).items())
    green, limit = F["green"], F["limit"]
    style_buy = ("绿盘里低吸, 不打板不追涨" if green and int(green) >= 60 else
                 "封板/拉板确认后买" if limit and int(limit) >= 40 else "按本导师常见买点挂单(见 profile【买点】)")
    circle = (f"{c.name}={c.E.get('circle')}: {board}(按买腿), 行业={'/'.join(ind)}, 题材={'/'.join(con)}, 熟票({'/'.join(tops)}); "
              f"打法(新开仓)={play_s}; 涨停价买 {limit}%、绿盘里买 {green}%; 流通市值中位 {F['mcap']} 亿; 买入时段 {bt}; "
              f"收盘总仓中位 {pct(S.get('total_pos_med', 0))}、持股中位 {S.get('n_hold_med')} 只、最大单票中位 {pct(S.get('max_pos_med', 0))}; "
              f"持股中位 {S.get('hold_days_med')} 天(P75 {S.get('hold_days_p75')})(以上={today()} onboard_mentor.py 机械统计, 细节见 profile.md【】节)")
    p12 = "/".join(p for p, _ in plays[:2]) or "本导师主打法"
    path = (f"本链现有持仓先处置(按持股中位 {S.get('hold_days_med')} 天/P75 {S.get('hold_days_p75')} 天的节奏)→新开仓按本导师主打法({p12})"
            f"在能力圈行业({'/'.join(ind[:3])})里找→{style_buy}→仓位按本导师习惯(收盘总仓中位 {pct(S.get('total_pos_med', 0))}、持股中位 {S.get('n_hold_med')} 只)")
    src = (f"①本链现有持仓与本导师熟票({'/'.join(tops[:5])}类) → ②本导师指纹池(scripts/tzzb/pools/<日>.json)与 facts 里符合主打法({p12})的能力圈票")
    return circle, path, src


def s_chain_md(c):
    dst = c.sk / "workflows" / "chain.md"
    if dst.exists() and "chain_md" not in (c.a.redo or ""):
        log("  chain.md 已存在不覆盖(--redo chain_md 重写)")
        return
    tpl = ROOT / "skills" / f"{TEMPLATE}-skill" / "workflows" / "chain.md"
    tname = M.get(TEMPLATE)["name"]
    s = tpl.read_text(encoding="utf-8")
    circle, path, src = circle_texts(c)
    subs = [(r"(本导师能力圈\(10/15 按真实成交逆推: 板块分布/常买票/行业/时段/持仓天数\): ).*?(。市场主线不在能力圈内)", circle),
            (r"(选股方向组=必填推导链（本导师自己的路径（10/15 方案 A））：).*?(，每环带三件套)", path),
            (r"(方向组个股来源=).*?( → ③其他\(须注明理由\))", src),
            (r"(按本导师推导链（).*?(）每环一行短句)", path)]
    for pat, rep in subs:
        s, k = re.subn(pat, lambda m, r=rep: m.group(1) + r + m.group(2), s, flags=re.S)
        if not k:
            raise RuntimeError(f"chain.md 模板锚点没找到: {pat[:40]}")
    s = s.replace(tname, c.name).replace(f"{TEMPLATE}-skill", f"{c.id}-skill").replace(f"{TEMPLATE}_chain", f"{c.id}_chain")
    lines = s.split("\n")
    if TEMPLATE in "\n".join(lines[1:]) or tname in "\n".join(lines[1:]):
        raise RuntimeError("chain.md 仍有模板导师残留")
    lines[0] = (f"# chain.md — {c.name}({c.id}-skill) 决策链契约【{today()} onboard_mentor.py 由 {TEMPLATE}-skill/chain.md 生成"
                f"(源头=10/7 taoge 模板盖章); 能力圈/推导链/取数=机械统计; 模板漂移责任: 改 taoge 模板后须重盖章或手动同步】")
    s = "\n".join(lines)
    dst.write_text(s, encoding="utf-8")
    log(f"  chain.md 写好; 能力圈: {circle[:160]}…")


# ---- 专题 ----
def s_focus(c):
    if not c.focus:
        log("  未给 --focus, 跳过")
        return
    rx = re.compile(c.focus_match or c.focus)
    L = legs(c)
    pick = lambda x: bool(rx.search(f"{x['stock_code']} {x['stock_name']}")) or (
        "基金" in (c.focus_match or "") and x["stock_code"].startswith(FUND_PREFIX))
    codes = sorted({x["stock_code"] for x in L if pick(x)})
    dp = _jload(c.dl / "day_positions.json") or {}
    days = sorted(dp)
    names = {x["stock_code"]: x["stock_name"] for x in L}
    out = [f"# {c.name}({c.id}) 专题逐笔明细: {c.focus}", "",
           f"> onboard_mentor.py 机械生成({today()}, 零 token)。匹配 = 正则 `{c.focus_match}` 命中「代码 名称」"
           + ("或场内基金代码段 " + "/".join(FUND_PREFIX) if "基金" in (c.focus_match or "") else "") + f"; 共 {len(codes)} 只。",
           "> 持有段=day_positions 收盘持仓(仓位>0)连续出现的交易日; 当天买当天清的不算持有段; 做T日=同日同票既买又卖; 时段=成交时刻(手录 00:00:00 的不计时段)。", ""]
    summ = []
    for code in codes:
        lg = [x for x in L if x["stock_code"] == code]
        buys, sells = [x for x in lg if side(x) == "B"], [x for x in lg if side(x) == "S"]
        bd = defaultdict(set)
        for x in lg:
            bd[x["trans_date"][:10]].add(side(x))
        tdays = sorted(d for d, s in bd.items() if s == {"B", "S"})
        held = [d for d in days if any(p.get("code") == code and (p.get("position_percent") or 0) > 0 for p in (dp[d].get("list") or []))]
        segs, cur = [], []
        for d in days:
            if d in held:
                cur.append(d)
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        pos = [p.get("position_percent") or 0 for d in held for p in dp[d].get("list") or [] if p.get("code") == code and (p.get("position_percent") or 0) > 0]
        tb = lambda xs: dict(Counter(("竞价" if t < "09:30" else "开盘5分钟" if t < "09:35" else "早盘" if t < "10:30" else
                                      "上午" if t < "11:31" else "午后" if t < "14:30" else "尾盘")
                                     for t in (x["trans_date"][11:16] for x in xs) if t != "00:00"))
        seglen = sorted(len(s) for s in segs)
        summ.append(f"| {code} | {names.get(code)} | {len(buys)}/{len(sells)} | {lg[0]['trans_date'][:10]}~{lg[-1]['trans_date'][:10]} | "
                    f"{len(segs)} 段, 中位 {seglen[len(seglen) // 2] if seglen else '—'} 天, 最长 {seglen[-1] if seglen else '—'} 天 | "
                    f"{len(tdays)} | {(sorted(pos)[len(pos) // 2] * 100 if pos else 0):.1f}% / {(max(pos) * 100 if pos else 0):.1f}% |")
        out += [f"## {code} {names.get(code)}", "",
                f"- 买 {len(buys)} 腿 / 卖 {len(sells)} 腿; 买入时段 {tb(buys)}; 卖出时段 {tb(sells)}",
                f"- 持有段: " + "; ".join(f"{s[0]}~{s[-1]}({len(s)} 天)" for s in segs) if segs else "- 持有段: 收盘从未持有(或 day_positions 未覆盖)",
                f"- 做T日(同日既买又卖) {len(tdays)}: {', '.join(tdays[:30])}",
                f"- 持有期间单票仓位 中位/最大: {(sorted(pos)[len(pos) // 2] * 100 if pos else 0):.1f}% / {(max(pos) * 100 if pos else 0):.1f}%", "",
                "| 时间 | 方向 | 数量 | 价格 | 金额 |", "|---|---|---|---|---|"]
        out += [f"| {x['trans_date']} | {'买' if side(x) == 'B' else '卖'} | {x['trans_count']} | {x['trans_price']} | {x['trans_amount']} |" for x in lg]
        out.append("")
    head = ["## 汇总", "", "| 代码 | 名称 | 买/卖腿 | 首末成交 | 持有段 | 做T日 | 仓位中位/最大 |", "|---|---|---|---|---|---|---|"] + summ + [""]
    f = c.out / "focus_legs.md"
    f.write_text("\n".join(out[:5] + head + out[5:]), encoding="utf-8")
    c.st["focus_file"] = str(f.relative_to(ROOT)).replace("\\", "/")
    log(f"  专题 {len(codes)} 只 → {c.st['focus_file']}")


def focus_block(c):
    if not c.focus:
        return ""
    return (f"\n专题(用户指定, 必须专门覆盖): {c.focus}。机械逐笔明细见 {c.st.get('focus_file')}(每只的逐笔腿/持有段/做T日/时段/仓位)。"
            f"专题相关的规则标题末尾加「[专题]」、案例卡标题加「[专题]」; 写清买卖时点、持有天数、是否做T、仓位、对应市况(大盘/板块当时怎样), 样本小就写样本小, 禁编。\n")


def budget_ok(c):
    s = cost_of(c.id)
    if s >= c.a.budget:
        raise RuntimeError(f"累计花费 ${s:.2f} ≥ 预算 ${c.a.budget}, 停")
    log(f"  当前累计花费 ${s:.2f}")


# ---- 花 token 的步骤 ----
def s_distill(c):
    budget_ok(c)
    import distill_history as DH
    fb = focus_block(c).replace("{", "{{").replace("}", "}}")
    if fb:
        DH.PROMPT = DH.PROMPT.replace("现有规则: 逐条", fb + "现有规则: 逐条", 1)
    argv = sys.argv
    sys.argv = ["distill_history.py", "--ledger", c.id]
    try:
        DH.main()
    finally:
        sys.argv = argv
    out = ROOT / "results" / "distill_history" / c.id
    if not (out / "DONE").exists():
        raise RuntimeError(f"distill_history 未成功(看 {out}/claude_stdout.txt)")
    rf = c.pd / "rules.md"
    if "(冷启动, 零条)" in rf.read_text(encoding="utf-8"):
        shutil.copy2(rf, c.bak / "rules.skeleton.md")
        shutil.copy2(out / "rules.md", rf)
        c.py("scripts/md/rule_time_state.py", "--skill", c.id, "--write", step="distill")
        c.sh(["node", "scripts/md/gen_rules_index.mjs", "--skill", c.id], "distill")
        log("  蒸馏规则已并入 rules.md")
    else:
        log("  rules.md 已不是骨架, 不覆盖(已并过)")


def _thicken(c, pass2):
    budget_ok(c)
    import thicken as T
    fb = focus_block(c).replace("{", "{{").replace("}", "}}")
    key = "PROMPT2" if pass2 else "PROMPT"
    if fb and fb not in getattr(T, key):
        setattr(T, key, getattr(T, key).replace("\n要做:", fb + "\n要做:", 1))
    rc = T.run(c.id, False, pass2)
    if rc:
        raise RuntimeError(f"thicken{'2' if pass2 else '1'} 失败")
    marker = "## 逐日日卡第二轮新增" if pass2 else "## 历史全量挖掘新增"
    if marker in (c.pd / "rules.md").read_text(encoding="utf-8"):
        log("  已并过, 不重复并")
    else:
        T.merge(c.id, pass2)


def s_thicken1(c):
    _thicken(c, False)


def s_thicken2(c):
    _thicken(c, True)


DEEP_PROMPT = """任务: 给 tzzb 导师「{name}」(ledger={id}) 的人格画像 profile.md 写**深度蒸馏节**。元指令: 任务优先, 禁反问; 只读下列文件, 只写一个文件。

格式样板(只学格式和颗粒度, 禁借其内容/数字——防串扰铁律): skills/{tpl}-skill/persona/profile.md 里从 `## 【选股逻辑】` 起的各节。

证据(全部只读; 一切数字必须出自这些文件或你对它们的计数, 手写数字=违规):
- skills/{id}-skill/persona/profile.md(机械画像 v1)与 fingerprint.md(打法/选股/买点/卖出/市况-仓位/盘中节奏/规则/反例/池验证)
- skills/{id}-skill/persona/cases_auto.jsonl(逐买卖事件: play/side/pnl/hold_days/open_pct/zt_day/r_next 等字段)
- skills/{id}-skill/persona/fills_rt.jsonl(成交那一分钟的盘中状态: mins_from_open/vs_prev_close/pos_so_far/mom5/at_limit 等)
- skills/{id}-skill/persona/orders_inferred.json(挂单反推, 中性先验, 只信方向)
- skills/{id}-skill/persona/rules.md 与 rules_index.md(已蒸馏/加厚的规则, 引用时写编号)
- scripts/tzzb/model_out/reports/hold_mining_{id}.md(持仓处理手法: 情境→动作的条件分布 + 滚动验证)
- scripts/tzzb/mentor_scope.json 的 "{id}" 条; scripts/tzzb/model_out/{D}.json 的 mentors.{id}(L1/L2/L3/L4){focus_src}
需要分组计数时用 Grep 在 jsonl 里数(不要凭印象)。
结构提示(机械统计, 须核实): {struct}
写作要求:
- 六节, 每节标题 `## 【节名】（{md} 深度蒸馏）`: 【选股逻辑】【买点】【卖点】【市况应对】【盘中节奏】【T法】(同票同日先买后卖是否成立、是不是有底仓做T, 要写清; 不成立就写"不成立"并给数据){focus_sec}
- 每节 4~8 条要点 + 一条 **因(概率分布, 合计 100%, 含"其他/证据不足")**, 每个因写可证伪后果及是否已见; 节末一行 `- （{md} 深度蒸馏，依据: …）` 列出用到的文件/字段
- 样本小的地方标 n, 不够就写"样本小/欠定", 禁编; 数据缺口照实写(profile.md 头部"数据缺口"行等)
- 用中文大白话, 少用术语
输出: 只写 {out} (完整 markdown), 文件末行只写: PROFILE_DEEP_OK {id}
"""


def s_profile_deep(c):
    out = ROOT / "results" / "distill_history" / c.id / "profile_deep.md"
    ok = lambda: out.exists() and out.read_text(encoding="utf-8").strip().splitlines()[-1].strip() == f"PROFILE_DEEP_OK {c.id}"
    if not ok():
        budget_ok(c)
        from claude_call import call
        L = legs(c)
        top = Counter((x["stock_code"], x["stock_name"]) for x in L).most_common(3)
        share = top[0][1] / max(1, len(L)) if top else 0
        struct = (f"成交腿最多的 3 只: " + "、".join(f"{n}({k}) {v} 腿" for (k, n), v in top) + f"; 第一只占全部腿 {share * 100:.0f}%"
                  + ("——单票占比很高, 核心票与其他票要分开统计, 别让核心票淹没其余票" if share >= 0.3 else ""))
        md_ = f"{int(today()[5:7])}/{int(today()[8:10])}"
        fs, fsrc = "", ""
        if c.focus:
            fsrc = f"\n- 专题逐笔明细 {c.st.get('focus_file')}(用户指定专题: {c.focus})"
            fs = (f"\n- **第七节(用户指定专题)** `## 【专题: {c.focus}】（{md_} 深度蒸馏）`: 逐类(如银行股 / 各只 ETF)写 买卖时点(几点、相对昨收/开盘、在日内什么位置)、"
                  f"持有天数(持有段)、是否做T(同日买卖次数与价差)、仓位(单票占比)、对应市况(当时大盘/板块, 查 case_log 日卡或 md), 以及跟他其他票手法的异同; "
                  f"用户以后要用小资金照这个手法做T, 所以要写到能照着执行的颗粒度(挂价相对昨收几个点、分几笔、拿几天), 但样本小处必须标明")
        P = DEEP_PROMPT.format(name=c.name, id=c.id, tpl=TEMPLATE, D=c.D, struct=struct, md=md_, focus_src=fsrc, focus_sec=fs,
                               out=str(out).replace("\\", "/"))
        r = call(P, tag=f"tzzb-profile-deep:{c.id}", permission="acceptEdits", timeout=3600,
                 extra_args=["--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--strict-mcp-config", "--tools", "Read,Write,Grep,Glob"],
                 expect_files=[out])
        log(f"  profile_deep: ok={r.ok} cost=${r.cost_usd:.2f} errors={'|'.join(r.errors)[:200]}")
        if not ok():
            raise RuntimeError("profile_deep 未成功")
    pf = c.pd / "profile.md"
    s = pf.read_text(encoding="utf-8")
    if re.search(r"^## 【选股逻辑】", s, re.M):
        log("  profile.md 已有深度节, 不重复并")
        return
    shutil.copy2(pf, c.bak / "profile.v1.md")
    deep = "\n".join(out.read_text(encoding="utf-8").rstrip().splitlines()[:-1]).rstrip()
    pf.write_text(s.rstrip() + "\n\n" + deep + "\n", encoding="utf-8")
    log("  深度节已并入 profile.md")


def s_finalize(c):
    i = c.id
    c.sh(["node", "scripts/md/gen_rules_index.mjs", "--skill", i], "finalize")
    c.py("scripts/md/gen_profile_index.py", "--skill", i, *(["--no-llm"] if c.a.skip_token else []), step="finalize", timeout=1800)
    c.py("scripts/dfcf/paper/quality_daily.py", "--date", c.D, "--only", "rules", step="finalize")
    c.py("scripts/skills_ver/persona_versions.py", "snapshot", "--all", "--why", f"{today()} 新导师 {c.name} 入库(onboard_mentor.py)",
         step="finalize", timeout=1800)
    c.sh(["node", "scripts/sync_skills.mjs"], "finalize")
    log(f"  规则/案例: {count_rc(c)}")


def count_rc(c):
    r = (c.pd / "rules.md").read_text(encoding="utf-8")
    k = (c.pd / "cases.md").read_text(encoding="utf-8")
    return f"规则 {len(re.findall(r'^#{3,4} +R(\d+)\b', r, re.M))} 条 / 叙事案例 {len(re.findall(r'^### \[', k, re.M))} 张"


TPL_CHECK = r"""
import sys; sys.argv=['x']
import run_chain as R
R.apply_skill('{tpl}'); a=R.load_templates()
R.apply_skill('{id}'); b=R.load_templates()
leak=[k for k,v in b.items() if '{tname}' in v or '{tpl}-skill' in v or '{tpl}_chain' in v]
print('KEYS', sorted(a)==sorted(b), len(b), 'LEAK', leak, 'NAME', '{name}' in b.get('02',''))
sys.exit(0 if sorted(a)==sorted(b) and not leak and '{name}' in b.get('02','') else 1)
"""


def s_verify(c):
    i = c.id
    _, o = c.py("scripts/lib/mentors.py", "--selftest", step="verify")
    log("  " + o.strip().splitlines()[-1])
    _, o = c.py("scripts/taoge-chain/run_chain.py", "--selftest", step="verify", timeout=1800)
    if "SELFTEST PASS" not in o:
        raise RuntimeError("run_chain --selftest 未 PASS")
    log("  run_chain --selftest PASS")
    code = TPL_CHECK.format(tpl=TEMPLATE, id=i, tname=M.get(TEMPLATE)["name"], name=c.name)
    r = subprocess.run([PY, "-X", "utf8", "-c", code], cwd=ROOT / "scripts" / "taoge-chain", capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    log("  驱动器模板: " + ((r.stdout or "").strip().splitlines() or [r.stderr[-200:]])[-1])
    if r.returncode:
        raise RuntimeError("驱动器载入本导师模板失败")
    _, o = c.sh(["node", "scripts/dfcf/paper/matcher.mjs", "--once", "--dry"], "verify", timeout=300)
    log("  matcher --once --dry: " + (o.strip().splitlines() or ["ok"])[-1])
    bad = check_shared([i], c.D)
    if bad:
        raise RuntimeError(f"共享文件缺本导师条目: {bad}")
    if c.st.get("jobs_pending"):
        log(f"  注意: 定时任务未加 {c.st['jobs_pending']}(需 --apply-jobs)")


FUN = {s: globals()[f"s_{s}"] for s in STEPS}


def main():
    ap = argparse.ArgumentParser(description="新 tzzb 导师一条命令入库(最厚做法)")
    ap.add_argument("--ledger")
    ap.add_argument("--skip-token", action="store_true", help="跳过花 token 的 4 步(distill/thicken1/thicken2/profile_deep)")
    ap.add_argument("--dry", action="store_true", help="只打印计划(各步是否已完成/将做什么), 不执行")
    ap.add_argument("--apply-jobs", action="store_true", help="真经 /api/quartz/add 加定时任务(不给=只给建议)")
    ap.add_argument("--date", help="链日 D(缺省 = max(登记表 online, 下一交易日))")
    ap.add_argument("--focus", help="用户指定专题(如 '银行股与ETF(尤其纳指ETF)'), 进蒸馏/加厚/深度节 prompt + 机械明细")
    ap.add_argument("--focus-match", default=None, help="专题选票正则(匹配「代码 名称」); 含'基金'=另把场内基金代码段全算进来")
    ap.add_argument("--redo", default="", help="逗号分隔, 强制重做这些步")
    ap.add_argument("--only", default="", help="逗号分隔, 只做这些步")
    ap.add_argument("--budget", type=float, default=25.0)
    ap.add_argument("--check-shared", help="逗号分隔导师 id: 只核对共享文件里的条目")
    a = ap.parse_args()
    if a.check_shared:
        D = a.date or chain_day(None)
        sys.exit(1 if check_shared(a.check_shared.split(","), D) else 0)
    if not a.ledger:
        ap.error("--ledger 必填")
    c = Ctx(a)
    redo, only = set(filter(None, a.redo.split(","))), set(filter(None, a.only.split(",")))
    log(f"onboard {c.id}({c.name}) D={c.D} focus={c.focus or '-'} 已完成 {list(c.st['done'])}")
    for s in STEPS:
        if only and s not in only:
            continue
        if a.skip_token and s in TOKEN_STEPS:
            log(f"[{s}] 跳过(--skip-token)")
            continue
        if s in c.st["done"] and s not in redo and s not in ("preflight", "verify"):
            log(f"[{s}] 已完成 {c.st['done'][s]}, 跳过(--redo {s} 重做)")
            continue
        if a.dry:
            log(f"[{s}] 将执行" + (" [token]" if s in TOKEN_STEPS else ""))
            continue
        log(f"[{s}] 开始")
        t0 = time.time()
        try:
            FUN[s](c)
        except Exception as e:  # noqa: BLE001
            c.save()
            log(f"[{s}] 失败: {e} —— 修好后再跑同一命令从这步续")
            sys.exit(1)
        c.st["done"][s] = dt.datetime.now().isoformat(timespec="seconds")
        c.save()
        log(f"[{s}] 完成 {time.time() - t0:.0f}s")
    if not a.dry:
        log(f"全部完成: {count_rc(c)}; 时段 {c.st.get('slots')} {c.st.get('slot_shares')}; 本导师累计花费 ${cost_of(c.id):.2f}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
