# -*- coding: utf-8 -*-
"""persona_versions.py — 导师画像(persona/)当"模型权重"管: 版本化 + 每版评估 + 可回滚(零 token; 2026-10-16 晚建, TODO 二B-11)

为什么: 每天蒸馏改写 skills/<skill>-skill/persona/ 下的文本(=导师的"权重"), 但没人量"这次改完拟人度变好还是变差"
        ——等于训练没有验证集。git 归用户手工提交, 所以本脚本自己存快照(不碰 git)。
子命令:
  snapshot --skill X | --all [--why ...]   persona 内容哈希与上一版不同才存新版 skills_versions/<skill>/v<NNN>_<YYYYMMDD-HHMM>/
  log      --skill X                         列版本
  metrics  [--since D] [--until D]           拟人度(mimicry 每日结果)+收益(books nav) 按"当日生效的画像版本"分段统计
  check    [--apply]                         最近两版 vs 再前一段, 拟人度显著变差 → 建议回滚到哪一版; --apply 且
                                             params.yaml persona_rollback.auto=true 才真回滚(默认 false=只告警)
  rollback --skill X --to vNNN [--dry] [--include-data] [--keep-extra] [--no-sync]
                                             先给当前版存快照, 再把指定版文件拷回 persona/, 再 node scripts/sync_skills.mjs
  prune    --skill X | --all [--keep 30] [--dry]  体积闸: 只留基线+最近 N 版+回滚涉及版本的内容, 其余只留哈希/diff
  export   --skill X --v vNNN --out DIR      把某版完整还原到任意目录(看/比对用, 不动 persona)
  selftest                                   全部在临时目录里测(含 rollback), 不碰真实 persona
存储(详见 docs/research/persona_versions_20261016.md):
  skills_versions/<skill>/index.json                  版本表(版本号/时刻/生效时刻/哈希/变更文件/变更行数/why/代码指纹) + 回滚事件
  skills_versions/<skill>/objects/<sha256>.gz         内容寻址存储(gzip, 同内容只存一份 → 未改的文件跨版本零成本)
  skills_versions/<skill>/v<NNN>_<时刻>/manifest.json 该版每个文件的 sha256/字节/行数/mtime/类别 + 代码指纹明细
  skills_versions/<skill>/v<NNN>_<时刻>/diff.patch    相对上一版的 unified diff(仅"权重"文本; 数据文件只记 +/− 行数)
  skills_versions/_metrics/metrics_<止>.json/.md, check_<止>.json/.md
文件两类: 权重(*.md / *.json 等, 链或蒸馏会读进 prompt / 检索) 决定版本哈希; 数据(cases_auto.jsonl / fills_rt.jsonl / 其他 *.jsonl,
  账本机械抽取、每晚整文件重算) 只随版本一起存档, 单独变化不升版本, 回滚默认不动(--include-data 才还原)。
版本归属(D 日结果算哪一版): ①results/<skill>_chain/live-D/run_meta.jsonl 里 0915 那次运行记下的 rules/profile/cases/language
  sha12 与某版完全一致 → 就是那版(最准); ②有 run_meta 但对不上任何快照 → 伪版本 "~<哈希8位>"(真实存在过但没快照, 不可回滚);
  ③没有 run_meta → D 日 08:00 前生效的最新版; 都没有 → v000(基线前未版本化)。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py <子命令> ...
硬约束: 不调 claude -p / 不写数据库 / 不做 git; 子进程 CREATE_NO_WINDOW; 只写 skills_versions/ 与(rollback 时)skills/<skill>-skill/persona/。
"""
import argparse
import collections
import contextlib
import datetime as dt
import difflib
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
START = "2026-10-08"            # paper 实盘重新开户日(mimicry_score.py / real_vs_chain.mjs 同口径)
CUTOFF = "08:00"                # D 日结果归属 D 日 08:00 前最新生效的版本(0915 链 08:15 开跑)
DATA_NAMES = {"cases_auto.jsonl", "fills_rt.jsonl"}
SKIP_RE = re.compile(r"(\.bak|\.tmp|\.lock|~$|\.pyc$|__pycache__)", re.I)
RUN_META_FILES = ("rules.md", "profile.md", "cases.md", "language.md")   # run_taoge_chain.record_rules_version 记的四个
DIFF_MAX_BYTES, DIFF_MAX_LINES = 1_600_000, 3000
# 同 mimicry_score.py MAIN / METRICS(每层一个主指标; err 类 lift=基线误差−链误差)
MAIN = [("L1_交易", "acc"), ("L2_方向", "acc"), ("L3_持仓Jaccard", "sim"), ("L4_总仓误差", "err")]
CHAIN_CODE = ["scripts/taoge-chain/run_taoge_chain.py", "skills/{s}-skill/workflows/chain.md", "skills/{s}-skill/SKILL.md",
              "scripts/dfcf/paper/params.yaml"]
DISTILL_CODE = ["skills/{s}-skill/workflows/distill.md", "scripts/tzzb/distill_daily.py", "scripts/tzzb/llm_batch_tzzb.py",
                "scripts/tzzb/mentor_fingerprint.py", "scripts/backfill_bilibili/backfill_bilibili.py",
                "scripts/md/gen_profile_index.py", "scripts/md/gen_rules_index.mjs", "scripts/md/check_md_daily.py"]
DEFAULT_CFG = {   # params.yaml 顶层 persona_rollback: 下同名键覆盖(文件里没有这一节=全用默认)
    "auto": False,             # 真回滚开关; false=check 只告警(默认)
    "baseline": "ctrl",        # 主口径: ctrl=对照链(同模板同 facts、persona 空)差分, 代码改动两边同时受影响被差掉; persist=延续基线
    "delta": 0.10,             # 最近两版各自的综合 lift 都比参照段低 ≥ delta 才算"变差"
    "min_eval_days": 2,        # 参照段 < 此天数 → 不判
    "min_ref_days": 5,         # 参照段 ≥ 此天数 且 最近段 ≥ min_recent_days 且 bootstrap 显著, 才升级为"建议回滚"
    "min_recent_days": 4,
    "max_ref_segments": 3,     # 参照段最多往回并几个版本凑天数
    "cooldown_days": 7,        # 同一 skill 两次回滚至少隔几天(自然日)
    "boot_n": 2000, "seed": 20261016,
}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Paths:
    def __init__(self, root=ROOT, vroot=None):
        self.root = Path(root)
        self.skills = self.root / "skills"
        self.vroot = Path(vroot) if vroot else self.root / "skills_versions"
        self.paper = self.root / "scripts" / "dfcf" / "paper"
        self.results = self.root / "results"
        self.tzzb = self.root / "downloads" / "tzzb"

    def persona(self, s):
        return self.skills / f"{s}-skill" / "persona"

    def sdir(self, s):
        return self.vroot / s


# ---------------- 基础 ----------------
def now_s():
    return dt.datetime.now().isoformat(timespec="seconds")


def sha256b(b):
    return hashlib.sha256(b).hexdigest()


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_atomic(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    b = data if isinstance(data, bytes) else data.encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(b)
    os.replace(tmp, p)


def dump(p, obj):
    write_atomic(p, json.dumps(obj, ensure_ascii=False, indent=1))


@contextlib.contextmanager
def vlock(P, stale_s=600):
    """skills_versions/.lock: snapshot / rollback 互斥(check md 与手工同时跑时防撕裂)"""
    P.vroot.mkdir(parents=True, exist_ok=True)
    lk = P.vroot / ".lock"
    for _ in range(60):
        try:
            fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {now_s()}".encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - lk.stat().st_mtime > stale_s:
                lk.unlink(missing_ok=True)
                continue
            time.sleep(1)
    else:
        sys.exit(f"锁被占用 >60s: {lk}(确认无其他 persona_versions 进程后手工删)")
    try:
        yield
    finally:
        lk.unlink(missing_ok=True)


def is_data(rel):
    return Path(rel).name in DATA_NAMES or rel.endswith(".jsonl")


def all_skills(P):
    out = []
    for d in sorted(P.skills.glob("*-skill")):
        pd = d / "persona"
        if pd.is_dir() and any(f.is_file() for f in pd.rglob("*")):
            out.append(d.name[:-len("-skill")])
    return out


def scan(pdir):
    files = {}
    if not pdir.is_dir():
        return files
    for f in sorted(pdir.rglob("*")):
        rel = f.relative_to(pdir).as_posix()
        if not f.is_file() or SKIP_RE.search(rel):
            continue
        b = f.read_bytes()
        files[rel] = {"sha256": sha256b(b), "bytes": len(b), "lines": b.count(b"\n") + (1 if b and not b.endswith(b"\n") else 0),
                      "mtime": dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                      "cls": "data" if is_data(rel) else "weight"}
    return files


def combo_hash(files, cls):
    s = "\n".join(f"{r}\t{m['sha256']}" for r, m in sorted(files.items()) if m["cls"] == cls)
    return sha256b(s.encode("utf-8"))


def code_fp(P, s):
    def grp(lst):
        det = {}
        for t in lst:
            rel = t.format(s=s)
            f = P.root / rel
            det[rel] = sha256b(f.read_bytes())[:12] if f.is_file() else None
        return det, sha256b(json.dumps(det, sort_keys=True).encode())[:12]
    cd, ch = grp(CHAIN_CODE)
    dd, dh = grp(DISTILL_CODE)
    return {"chain": ch, "distill": dh, "chain_files": cd, "distill_files": dd}


# ---------------- 存储 ----------------
def obj_path(P, s, sha):
    return P.sdir(s) / "objects" / f"{sha}.gz"


def put_obj(P, s, b):
    sha = sha256b(b)
    p = obj_path(P, s, sha)
    if not p.exists():
        write_atomic(p, gzip.compress(b, 6))
    return sha


def get_obj(P, s, sha):
    op = obj_path(P, s, sha)
    if not op.exists():
        raise SystemExit(f"{s}: 对象 {sha[:12]} 不存在(该版已被 prune 只留哈希, 或存储被手工删过), 不能还原")
    b = gzip.decompress(op.read_bytes())
    if sha256b(b) != sha:
        raise ValueError(f"对象损坏: {s}/{sha}")
    return b


def load_index(P, s):
    return load_json(P.sdir(s) / "index.json") or {"skill": s, "versions": [], "events": []}


def find_version(idx, v):
    v = str(v)
    for e in idx["versions"]:
        if e["id"] == v or e["id"].split("_")[0] == v or (v.isdigit() and e["v"] == int(v)):
            return e
    return None


def manifest(P, s, e):
    return load_json(P.sdir(s) / e["id"] / "manifest.json")


def line_delta(a, b):
    ca = collections.Counter(a.splitlines())
    cb = collections.Counter(b.splitlines())
    return sum((cb - ca).values()), sum((ca - cb).values())


def snapshot(P, s, why="manual", now=None, extra=None, force_data=False):
    """persona 权重哈希与上一版相同 → 返回 None(force_data=True 时数据文件变了也存, 供 rollback --include-data 前保存); 否则存新版"""
    pdir = P.persona(s)
    files = scan(pdir)
    if not files:
        return None
    idx = load_index(P, s)
    ph, dh = combo_hash(files, "weight"), combo_hash(files, "data")
    last = idx["versions"][-1] if idx["versions"] else None
    if last and last["persona_hash"] == ph and not (force_data and last["data_hash"] != dh):
        return None
    now = now or dt.datetime.now()
    for rel in files:
        put_obj(P, s, (pdir / rel).read_bytes())
    pm = (manifest(P, s, last) or {}).get("files", {}) if last else {}
    w_now = {r for r, m in files.items() if m["cls"] == "weight"}
    w_old = {r for r, m in pm.items() if m["cls"] == "weight"}
    added, removed = sorted(w_now - w_old), sorted(w_old - w_now)
    modified = sorted(r for r in w_now & w_old if files[r]["sha256"] != pm[r]["sha256"])
    data_changed = sorted(r for r, m in files.items() if m["cls"] == "data" and (r not in pm or pm[r]["sha256"] != m["sha256"]))
    vnum = (last["v"] + 1) if last else 1
    vid = f"v{vnum:03d}_{now:%Y%m%d-%H%M}"
    vdir = P.sdir(s) / vid
    plus = minus = 0
    patch = []
    for r in added + modified + removed:
        old = get_obj(P, s, pm[r]["sha256"]).decode("utf-8", "replace") if r in pm else ""
        new = (pdir / r).read_bytes().decode("utf-8", "replace") if r in files else ""
        a, m_ = line_delta(old, new)
        plus, minus = plus + a, minus + m_
        if last and not r.endswith(".vec.json") and max(len(old), len(new)) <= DIFF_MAX_BYTES:
            d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"{last['id']}/{r}", f"{vid}/{r}", lineterm="", n=2))
            if len(d) > DIFF_MAX_LINES:
                d = d[:DIFF_MAX_LINES] + [f"... (截断, 共 {len(d)} 行; 全文用 export 取)"]
            patch += d
        elif last:
            patch.append(f"=== {r}: 体积大/向量索引, 不出 diff(+{a}/-{m_} 行; 全文用 export 取)")
    # 生效时刻 = 变更文件最晚 mtime(内容最晚何时成形), 不早于上一版快照时刻, 不晚于本次快照
    mt = [files[r]["mtime"] for r in added + modified]
    eff = max(mt) if mt else now.isoformat(timespec="seconds")
    if last:
        eff = max(eff, last["ts"])
    eff = min(eff, now.isoformat(timespec="seconds"))
    code = code_fp(P, s)
    e = {"v": vnum, "id": vid, "ts": now.isoformat(timespec="seconds"), "effective_from": eff, "persona_hash": ph, "data_hash": dh,
         "parent": last["id"] if last else None, "changed": {"added": added, "modified": modified, "removed": removed},
         "data_changed": data_changed, "lines": {"added": plus, "removed": minus},
         "bytes_weight": sum(m["bytes"] for m in files.values() if m["cls"] == "weight"),
         "why": why, "code": {"chain": code["chain"], "distill": code["distill"]}} | (extra or {})
    dump(vdir / "manifest.json", {"skill": s, "version": e, "files": files, "code": code})
    if patch:
        write_atomic(vdir / "diff.patch", "\n".join(patch) + "\n")
    idx["versions"].append(e)
    dump(P.sdir(s) / "index.json", idx)
    return e


def restore_into(P, s, e, dest, include_data=True, keep_extra=True, dry=False):
    """把版本 e 的文件写进 dest(rollback: dest=persona/; export: 任意目录)。返回动作清单"""
    files = manifest(P, s, e)["files"]
    want = {r: m for r, m in files.items() if include_data or m["cls"] == "weight"}
    cur = scan(dest)
    acts = []
    for r, m in want.items():
        if r in cur and cur[r]["sha256"] == m["sha256"]:
            continue
        acts.append(("写回" if r in cur else "新建", r))
        if not dry:
            write_atomic(dest / r, get_obj(P, s, m["sha256"]))   # 新写入 → mtime=现在(生效时刻正确)
    if not keep_extra:
        for r, m in cur.items():
            if r not in want and (include_data or m["cls"] == "weight"):
                acts.append(("删除(已在回滚前快照里)", r))
                if not dry:
                    (dest / r).unlink()
    return acts


def run_sync(P):
    r = subprocess.run(["node", "scripts/sync_skills.mjs"], cwd=P.root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout or "")[-400:] + (r.stderr or "")[-400:]


def rollback(P, s, to, why="manual", include_data=False, keep_extra=False, sync=True, dry=False, sync_fn=None):
    idx = load_index(P, s)
    e = find_version(idx, to)
    if not e:
        raise SystemExit(f"{s}: 没有版本 {to}(用 log --skill {s} 看)")
    m = manifest(P, s, e)
    for r, fm in m["files"].items():          # 先验对象完整, 再动 persona
        if include_data or fm["cls"] == "weight":
            get_obj(P, s, fm["sha256"])
    if dry:
        return {"dry": True, "to": e["id"], "actions": restore_into(P, s, e, P.persona(s), include_data, keep_extra, dry=True)}
    pre = snapshot(P, s, why=f"rollback 前自动保存(→{e['id']})", force_data=include_data)
    cur_v = (pre or load_index(P, s)["versions"][-1])["id"]
    acts = restore_into(P, s, e, P.persona(s), include_data, keep_extra)
    post = snapshot(P, s, why=f"rollback→{e['id']}: {why}", extra={"rollback_of": e["id"]})
    idx = load_index(P, s)
    ev = {"ts": now_s(), "type": "rollback", "from": cur_v, "to": e["id"], "new_version": post["id"] if post else None,
          "why": why, "include_data": include_data, "actions": len(acts)}
    sres = None
    if sync:
        rc, out = (sync_fn or run_sync)(P)
        sres = {"rc": rc, "tail": out[-300:]}
        ev["sync_rc"] = rc
    idx["events"].append(ev)
    dump(P.sdir(s) / "index.json", idx)
    return {"to": e["id"], "from": cur_v, "new_version": ev["new_version"], "actions": acts, "sync": sres}


def prune(P, s, keep=30, dry=False):
    """体积闸: 只保留 v001(基线) + 最近 keep 个版本 + 回滚事件涉及的版本的文件内容; 其余版本只留 manifest/diff(哈希+行数), 不可再回滚"""
    idx = load_index(P, s)
    vs = idx["versions"]
    pin = {vs[0]["id"]} if vs else set()
    pin |= {e["id"] for e in vs[-keep:]} if keep > 0 else set()
    pin |= {x for ev in idx["events"] for x in (ev.get("from"), ev.get("to"), ev.get("new_version")) if x}
    need = set()
    for e in vs:
        if e["id"] in pin:
            need |= {m["sha256"] for m in (manifest(P, s, e) or {}).get("files", {}).values()}
    od = P.sdir(s) / "objects"
    drop = [f for f in od.glob("*.gz") if f.stem not in need] if od.is_dir() else []
    freed = sum(f.stat().st_size for f in drop)
    if not dry:
        for f in drop:
            f.unlink()
        for e in vs:
            if e["id"] not in pin and not e.get("pruned"):
                fs = (manifest(P, s, e) or {}).get("files", {})
                if any(m["sha256"] not in need for m in fs.values()):
                    e["pruned"] = now_s()
        dump(P.sdir(s) / "index.json", idx)
    return {"skill": s, "objects_dropped": len(drop), "bytes_freed": freed, "kept_versions": sorted(pin)}


# ---------------- 评估: 版本归属 ----------------
def run_meta_day(P, s, d):
    """D 日 live 运行里最早(0915)一次记下的 persona sha12; 同日多次不同 → mixed"""
    f = P.results / f"{s}_chain" / f"live-{d.replace('-', '')}" / "run_meta.jsonl"
    if not f.exists():
        return None
    recs = []
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not r.get("dry") and not r.get("asof") and str(r.get("ts", "")).startswith(d):
            recs.append(r)
    if not recs:
        return None
    recs.sort(key=lambda r: r["ts"])
    sig = lambda r: {k: v.get("sha12") for k, v in (r.get("persona") or {}).items()}  # noqa: E731
    first = recs[0]
    code = sha256b(json.dumps([first.get("chain_md_sha12"), first.get("flags")], sort_keys=True).encode())[:8]
    return {"ts": first["ts"], "sha": sig(first), "mixed": len({json.dumps(sig(r), sort_keys=True) for r in recs}) > 1, "code": code}


def attribute(P, s, idx, d, cache):
    """→ (标签, 归属方式, 可回滚, 代码指纹)"""
    rm = run_meta_day(P, s, d)
    vs = idx["versions"]
    if rm and rm["sha"]:
        hits = []
        for e in vs:
            fs = cache.setdefault(e["id"], (manifest(P, s, e) or {}).get("files", {}))
            ok = all((fs.get(n) or {}).get("sha256", "")[:12] == rm["sha"].get(n) if n in rm["sha"] else n not in fs
                     for n in RUN_META_FILES)
            if ok:
                hits.append(e)
        if hits:
            good = [e for e in hits if e["effective_from"] <= rm["ts"]]
            e = good[-1] if good else hits[0]   # 时刻自洽的取最新; 都不自洽(快照晚于运行)取最早命中
            return e["id"].split("_")[0], "run_meta 哈希" + ("·同日画像有变" if rm["mixed"] else ""), True, rm["code"]
        h = sha256b(json.dumps(rm["sha"], sort_keys=True).encode())[:8]
        return f"~{h}", "run_meta 哈希·未快照" + ("·同日画像有变" if rm["mixed"] else ""), False, rm["code"]
    cut = f"{d}T{CUTOFF}:00"
    prior = [e for e in vs if e["effective_from"] < cut]
    if prior:
        return prior[-1]["id"].split("_")[0], f"时刻(D 日 {CUTOFF} 前最新)", True, None
    return "v000", "基线前·未版本化", False, None


# ---------------- 评估: 数据 ----------------
def chains(P):
    """UP/导师/对照链 → [(source, skill)]; 10/17 二B-4 改读导师登记表(原解析 accounts.mjs 文本); P 参数保留作调用口兼容"""
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import mentors
    return [(e["book"], e["id"]) for e in mentors.all()]


def load_mimicry(P):
    """(source, 日) → scores{chain, persist, ctrl}; 同一天多份(单日/累计/重算)取 generated_at 最新"""
    best = {}
    for f in sorted((P.paper / "mimicry").glob("*.json")):
        j = load_json(f) or {}
        g = j.get("generated_at", "")
        for b, p in (j.get("pairs") or {}).items():
            for r in p.get("daily") or []:
                k = (b, r["date"])
                if k not in best or g >= best[k][0]:
                    best[k] = (g, r.get("scores") or {})
    return {k: v[1] for k, v in best.items()}


def lift(sc, base, m, kind):
    c, b = (sc.get("chain") or {}).get(m), (sc.get(base) or {}).get(m)
    if c is None or b is None:
        return None
    return (b - c) if kind == "err" else (c - b)


def book_nav(P, b):
    j = load_json(P.paper / "books" / f"{b}.json") or {}
    return {n["date"]: float(n["nav"]) for n in j.get("nav") or [] if n.get("nav") is not None}


def real_nav(P, ledger):
    j = load_json(P.tzzb / ledger / "nav_daily.json") or {}
    il = ((j.get("ex_data") or {}).get("index_list")) or []
    if isinstance(il, str):
        try:
            import ast
            il = ast.literal_eval(il)
        except (ValueError, SyntaxError):
            il = []
    out = {}
    for x in il:
        try:
            ds = str(x["date"])
            out[f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"] = float(x["index"])
        except (KeyError, ValueError, TypeError):
            pass
    return out


def day_ret(nav, d):
    ks = sorted(k for k in nav if k < d)
    return nav[d] / nav[ks[-1]] - 1 if d in nav and ks and nav[ks[-1]] else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def compound(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    v = 1.0
    for x in xs:
        v *= 1 + x
    return v - 1


def metrics(P, since=START, until=None):
    until = until or dt.date.today().isoformat()
    mim = load_mimicry(P)
    ctrl_nav = book_nav(P, "A-control")
    out = {"generated_at": now_s(), "since": since, "until": until, "cutoff": CUTOFF, "skills": {}}
    for b, s in chains(P):
        if not P.persona(s).parent.is_dir():
            continue
        idx = load_index(P, s)
        nav = book_nav(P, b)
        rnav = real_nav(P, s) if b != "A-control" else {}
        days = sorted({d for d in nav if since <= d <= until} | {d for (bb, d) in mim if bb == b and since <= d <= until})
        cache, rows = {}, []
        for d in days:
            lab, how, rb, code = attribute(P, s, idx, d, cache)
            sc = mim.get((b, d))
            r = {"date": d, "v": lab, "how": how, "rollbackable": rb, "code": code, "lifts": {}, "comp": {}}
            if sc:
                for base in ("ctrl", "persist"):
                    ls = {m: lift(sc, base, m, k) for m, k in MAIN}
                    r["lifts"][base] = ls
                    r["comp"][base] = mean(ls.values())
            r["ret"] = day_ret(nav, d)
            r["ret_ctrl"] = day_ret(ctrl_nav, d) if b != "A-control" else None
            r["ret_real"] = day_ret(rnav, d) if rnav else None
            rows.append(r)
        segs, order = {}, []
        for r in rows:
            if r["v"] not in segs:
                segs[r["v"]] = []
                order.append(r["v"])
            segs[r["v"]].append(r)
        seg_out = []
        for lab in order:
            rs = segs[lab]
            sg = {"v": lab, "how": rs[0]["how"], "rollbackable": rs[0]["rollbackable"], "first": rs[0]["date"], "last": rs[-1]["date"],
                  "days": len(rs), "codes": sorted({r["code"] for r in rs if r["code"]}), "lift": {}, "comp": {}}
            e = find_version(idx, lab) if rs[0]["rollbackable"] else None
            if e:
                sg["version"] = {"id": e["id"], "why": e["why"], "lines": e["lines"], "changed": e["changed"], "code": e["code"]}
            for base in ("ctrl", "persist"):
                sg["lift"][base] = {m: {"n": sum(1 for r in rs if (r["lifts"].get(base) or {}).get(m) is not None),
                                        "mean": mean([(r["lifts"].get(base) or {}).get(m) for r in rs])} for m, _ in MAIN}
                cv = [r["comp"].get(base) for r in rs if r["comp"].get(base) is not None]
                sg["comp"][base] = {"n": len(cv), "mean": mean(cv)}
            sg["ret"] = {"chain": compound([r["ret"] for r in rs]), "ctrl": compound([r["ret_ctrl"] for r in rs if r["ret"] is not None]),
                         "real": compound([r["ret_real"] for r in rs if r["ret"] is not None]),
                         "n": sum(1 for r in rs if r["ret"] is not None)}
            c, k = sg["ret"]["chain"], sg["ret"]["ctrl"]
            sg["ret"]["excess_vs_ctrl"] = (c - k) if c is not None and k is not None else None
            seg_out.append(sg)
        out["skills"][s] = {"source": b, "n_versions": len(idx["versions"]), "segments": seg_out, "days": rows}
    return out


def pct(x, nd=1):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def num(x):
    return "—" if x is None else f"{x:+.2f}"


def metrics_md(res):
    L = [f"# 画像版本分段评估 {res['since']} ~ {res['until']}", "",
         f"> 生成 {res['generated_at']}(零 token, 只读) | 版本归属: run_meta 哈希 > D 日 {res['cutoff']} 前最新版 | "
         "lift 口径同 mimicry_score.py(>0=比基线更像; 误差类=基线误差−链误差); 综合=四层主指标 lift 均值",
         "> 对照=A-control(同模板同 facts、persona 空; 代码/模板改动两边同时受影响, 差分后更能归因到画像); 延续=导师真人昨天原样",
         "> ~xxxxxxxx=run_meta 里出现过但没快照的画像态(不可回滚); v000=基线前未版本化; 收益=段内逐日复利(书 nav)", ""]
    for s, x in res["skills"].items():
        if not x["segments"]:
            continue
        L += [f"## {s}({x['source']}, 已存版本 {x['n_versions']})", "",
              "| 画像版 | 归属 | 区间 | 天 | L1交易 对照/延续 | L2方向 | L3持仓J | L4总仓误差 | 综合 对照/延续(n) | 链收益 | 对照收益 | 真人收益 | 代码指纹 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for g in x["segments"]:
            cells = []
            for m, _ in MAIN:
                cells.append(f"{num(g['lift']['ctrl'][m]['mean'])}/{num(g['lift']['persist'][m]['mean'])}")
            cc, cp = g["comp"]["ctrl"], g["comp"]["persist"]
            L.append(f"| {g['v']} | {g['how']} | {g['first'][5:]}~{g['last'][5:]} | {g['days']} | " + " | ".join(cells) +
                     f" | {num(cc['mean'])}({cc['n']}) / {num(cp['mean'])}({cp['n']}) | {pct(g['ret']['chain'], 2)} | {pct(g['ret']['ctrl'], 2)} | "
                     f"{pct(g['ret']['real'], 2)} | {len(g['codes'])} |")
        L.append("")
    L += ["## 读法与局限", "",
          "- 现在(10/16)每段多为 1 天, 任何一段的数都不能当结论; check 只在参照段 ≥5 天、最近段 ≥4 天且 bootstrap 显著时才给\"建议回滚\"。",
          "- 代码指纹=run_meta 的 chain_md_sha12+开关(flags) 哈希; 一段内 >1 或相邻段不同 = 画像与代码同期改动, 归因存疑。", ""]
    return "\n".join(L)


# ---------------- check ----------------
def load_cfg(P):
    cfg = dict(DEFAULT_CFG)
    try:
        import yaml
        y = yaml.safe_load((P.paper / "params.yaml").read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (y.get("persona_rollback") or {}).items() if k in DEFAULT_CFG})
        cfg["_src"] = "params.yaml persona_rollback" if y.get("persona_rollback") else "默认(params.yaml 无 persona_rollback 节)"
    except Exception as ex:  # noqa: BLE001  yaml 缺失/解析失败 → 默认(auto=false 安全侧)
        cfg["_src"] = f"默认(params.yaml 读取失败: {ex.__class__.__name__})"
    return cfg


def boot_diff(a, b, n, seed):
    rnd = random.Random(seed)
    ds = sorted(mean([rnd.choice(a) for _ in a]) - mean([rnd.choice(b) for _ in b]) for _ in range(n))
    return ds[int(0.025 * n)], ds[int(0.975 * n) - 1]


def judge(sk, cfg):
    """sk = metrics()['skills'][s] → 判定 dict"""
    def vals(base):
        segs = []
        for g in sk["segments"]:
            v = [r["comp"][base] for r in sk["days"] if r["v"] == g["v"] and r["comp"].get(base) is not None]
            if v:
                segs.append((g, v))
        return segs
    base = cfg["baseline"]
    segs = vals(base)
    note = []
    if base == "ctrl" and (len(segs) < 3 or sum(len(v) for _, v in segs[:-2]) < cfg["min_eval_days"]):
        alt = vals("persist")
        if len(alt) >= 3 and sum(len(v) for _, v in alt[:-2]) >= cfg["min_eval_days"]:
            segs, base = alt, "persist"
            note.append("对照链样本不够, 退用延续基线(代码改动无法差分, 只告警)")
    out = {"baseline": base, "level": "不判", "note": note, "recent": [], "ref": [], "target": None}
    if len(segs) < 3:
        out["note"].append(f"有拟人度数据的版本段 {len(segs)} < 3(最近两版+参照)")
        return out
    recent, rest = segs[-2:], segs[:-2]
    ref = []
    for g, v in reversed(rest):
        ref.append((g, v))
        if sum(len(x) for _, x in ref) >= cfg["min_ref_days"] or len(ref) >= cfg["max_ref_segments"]:
            break
    rv = [x for _, v in ref for x in v]
    nv = [x for _, v in recent for x in v]
    rm = mean(rv)
    out["ref"] = [{"v": g["v"], "n": len(v), "mean": mean(v)} for g, v in ref]
    out["recent"] = [{"v": g["v"], "n": len(v), "mean": mean(v), "vs_ref": mean(v) - rm} for g, v in recent]
    out["ref_mean"], out["recent_mean"] = rm, mean(nv)
    if len(rv) < cfg["min_eval_days"]:
        out["note"].append(f"参照段仅 {len(rv)} 天 < {cfg['min_eval_days']}")
        return out
    worse = [x["vs_ref"] <= -cfg["delta"] for x in out["recent"]]
    lo, hi = boot_diff(nv, rv, cfg["boot_n"], cfg["seed"]) if len(nv) > 1 and len(rv) > 1 else (None, None)
    out["diff_ci"] = [lo, hi]
    codes_ref = {c for g, _ in ref for c in g["codes"]}
    codes_new = {c for g, _ in recent for c in g["codes"]}
    code_changed = bool(codes_ref and codes_new and codes_ref != codes_new)
    if code_changed:
        out["note"].append("参照段与最近段代码指纹不同(驱动器/模板/开关同期改过)")
    if not all(worse):
        out["level"] = "观察" if any(worse) else "正常"
        return out
    sig = hi is not None and hi < 0
    enough = len(rv) >= cfg["min_ref_days"] and len(nv) >= cfg["min_recent_days"]
    if sig and enough and not (code_changed and base == "persist"):
        out["level"] = "建议回滚"
    else:
        out["level"] = "告警"
        out["note"].append("最近两版都比参照低 ≥{:.2f}, 但{}".format(cfg["delta"], "样本不足" if not enough else
                                                              "差异不显著" if not sig else "延续基线下代码同期改动, 不能归因画像"))
    tgt = next((g["v"] for g, _ in ref if g["rollbackable"]), None)   # 参照段里最近一个有快照的版本
    out["target"] = tgt
    if not tgt:
        out["note"].append("参照段都是未快照的画像态(~xxx/v000), 没有可回滚目标")
        if out["level"] == "建议回滚":
            out["level"] = "告警"
    return out


def check(P, res, cfg, apply=False):
    out = {"generated_at": now_s(), "cfg": cfg, "skills": {}, "actions": []}
    for s, sk in res["skills"].items():
        j = judge(sk, cfg)
        out["skills"][s] = j
        if apply and cfg["auto"] and j["level"] == "建议回滚" and j["target"]:
            evs = [e for e in load_index(P, s)["events"] if e.get("type") == "rollback"]
            if evs and (dt.datetime.now() - dt.datetime.fromisoformat(evs[-1]["ts"])).days < cfg["cooldown_days"]:
                out["actions"].append({"skill": s, "skip": f"冷却期内(上次回滚 {evs[-1]['ts']})"})
                continue
            with vlock(P):
                r = rollback(P, s, j["target"], why=f"check 自动回滚: 综合 lift {j['recent_mean']:+.2f} vs 参照 {j['ref_mean']:+.2f}")
            out["actions"].append({"skill": s, "rollback": {k: v for k, v in r.items() if k != "actions"}})
    return out


def check_md(c):
    L = [f"# 画像版本 check {c['generated_at']}", "",
         f"> 开关: auto={c['cfg']['auto']}(来源 {c['cfg']['_src']}); 主口径 baseline={c['cfg']['baseline']}; delta={c['cfg']['delta']}; "
         f"建议回滚门槛: 参照 ≥{c['cfg']['min_ref_days']} 天 + 最近两版 ≥{c['cfg']['min_recent_days']} 天 + bootstrap 95% 上界<0", "",
         "| skill | 判定 | 口径 | 参照段(天/综合) | 最近两版(天/综合/比参照) | 差 95% | 回滚目标 | 说明 |", "|---|---|---|---|---|---|---|---|"]
    for s, j in c["skills"].items():
        ref = ", ".join(f"{x['v']}({x['n']}/{num(x['mean'])})" for x in j["ref"]) or "—"
        rec = ", ".join(f"{x['v']}({x['n']}/{num(x['mean'])}/{num(x['vs_ref'])})" for x in j["recent"]) or "—"
        ci = j.get("diff_ci") or [None, None]
        L.append(f"| {s} | {j['level']} | {j['baseline']} | {ref} | {rec} | [{num(ci[0])}, {num(ci[1])}] | {j['target'] or '—'} | {'; '.join(j['note']) or ''} |")
    L += ["", "动作: " + (json.dumps(c["actions"], ensure_ascii=False) if c["actions"] else "无(auto=false 或无'建议回滚')"), ""]
    return "\n".join(L)


# ---------------- selftest ----------------
def selftest():
    fails = []

    def ck(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
    tmp = Path(tempfile.mkdtemp(prefix="pv_selftest_"))
    try:
        P = Paths(tmp, tmp / "skills_versions")
        pd = P.persona("foo")
        pd.mkdir(parents=True)
        (pd / "rules.md").write_text("# R\nA1 买\n", encoding="utf-8", newline="\n")
        (pd / "profile.md").write_text("画像 v1\n", encoding="utf-8", newline="\n")
        (pd / "cases_auto.jsonl").write_text('{"a":1}\n', encoding="utf-8", newline="\n")
        t0 = dt.datetime(2026, 10, 12, 22, 0)
        e1 = snapshot(P, "foo", "基线", now=t0)
        ck("基线 v001", e1 and e1["id"] == "v001_20261012-2200" and e1["parent"] is None)
        ck("无变化不升版", snapshot(P, "foo", now=t0) is None)
        (pd / "cases_auto.jsonl").write_text('{"a":1}\n{"a":2}\n', encoding="utf-8", newline="\n")
        ck("只改数据文件不升版", snapshot(P, "foo", now=t0) is None)
        (pd / "rules.md").write_text("# R\nA1 买\nA2 卖\n", encoding="utf-8", newline="\n")
        (pd / "fingerprint.md").write_text("fp\n", encoding="utf-8", newline="\n")
        e2 = snapshot(P, "foo", "蒸馏", now=dt.datetime(2026, 10, 13, 23, 0))
        ck("v002 变更文件/行数", e2 and e2["changed"]["modified"] == ["rules.md"] and e2["changed"]["added"] == ["fingerprint.md"]
           and e2["lines"] == {"added": 2, "removed": 0} and e2["data_changed"] == ["cases_auto.jsonl"])
        ck("diff.patch 存在", (P.sdir("foo") / e2["id"] / "diff.patch").read_text(encoding="utf-8").count("+A2 卖") == 1)
        ck("对象去重(未改的 profile 只 1 份)", len(list((P.sdir("foo") / "objects").glob("*.gz"))) == 6)
        # export
        ex = tmp / "exp"
        restore_into(P, "foo", find_version(load_index(P, "foo"), "v001"), ex)
        ck("export v001", (ex / "rules.md").read_text(encoding="utf-8") == "# R\nA1 买\n" and not (ex / "fingerprint.md").exists())
        # rollback(假 sync)
        (pd / "rules.md").write_text("# R\n坏规则\n", encoding="utf-8", newline="\n")   # 未快照的当前改动, 回滚前必须被保存
        called = []
        dr = rollback(P, "foo", "v001", dry=True)
        ck("rollback --dry 不动文件", "坏规则" in (pd / "rules.md").read_text(encoding="utf-8") and dr["dry"])
        r = rollback(P, "foo", "v001", why="selftest", sync_fn=lambda p: (called.append(1), (0, "ok"))[1])
        idx = load_index(P, "foo")
        ids = [e["id"].split("_")[0] for e in idx["versions"]]
        ck("回滚前快照 v003 保存了坏规则", ids[2] == "v003" and "坏规则" in get_obj(P, "foo", manifest(P, "foo", idx["versions"][2])["files"]["rules.md"]["sha256"]).decode())
        ck("回滚后 v004=v001 内容", ids == ["v001", "v002", "v003", "v004"] and idx["versions"][3]["persona_hash"] == idx["versions"][0]["persona_hash"]
           and idx["versions"][3]["rollback_of"] == idx["versions"][0]["id"])
        ck("回滚还原 rules / 删多余权重文件 / 数据文件不动", (pd / "rules.md").read_text(encoding="utf-8") == "# R\nA1 买\n"
           and not (pd / "fingerprint.md").exists() and (pd / "cases_auto.jsonl").read_text(encoding="utf-8").count("\n") == 2)
        ck("sync 调用 + 事件记录", called == [1] and idx["events"][-1]["to"] == idx["versions"][0]["id"])
        # 归属: run_meta 哈希 / 未快照 / 时刻 / v000
        sha = lambda t: sha256b(t.encode())[:12]  # noqa: E731

        def meta(d, rules, prof="画像 v1\n"):
            f = P.results / "foo_chain" / f"live-{d.replace('-', '')}" / "run_meta.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"ts": f"{d}T08:15:00", "dry": False, "asof": None, "chain_md_sha12": "x", "flags": {},
                                     "persona": {"rules.md": {"sha12": sha(rules)}, "profile.md": {"sha12": sha(prof)}}}) + "\n", encoding="utf-8")
        meta("2026-10-14", "# R\nA1 买\nA2 卖\n")
        meta("2026-10-15", "# R\n别的\n")
        c = {}
        a14 = attribute(P, "foo", idx, "2026-10-14", c)
        ck(f"归属 run_meta→v002 {a14}", a14[:3] == ("v002", "run_meta 哈希", True))
        a15 = attribute(P, "foo", idx, "2026-10-15", c)
        ck("归属 未快照→~伪版本", a15[0].startswith("~") and not a15[2])
        ck("归属 时刻(10/13 08:00 前最新=v001)", attribute(P, "foo", idx, "2026-10-13", c)[0] == "v001")
        ck("归属 基线前=v000", attribute(P, "foo", idx, "2026-10-12", c)[0] == "v000")
        # judge: 参照 6 天好, 最近两版各 3 天差 → 建议回滚; 样本少 → 告警
        def seg(v, n, val, rb=True):
            return {"v": v, "rollbackable": rb, "codes": ["c"]}, [{"v": v, "comp": {"ctrl": val + 0.01 * (i % 2), "persist": None}} for i in range(n)]
        def mk(spec):
            segs, days = [], []
            for v, n, val, rb in spec:
                g, d = seg(v, n, val, rb)
                segs.append(g)
                days += d
            return {"segments": segs, "days": days}
        cfg = dict(DEFAULT_CFG)
        j = judge(mk([("v001", 6, 0.3, True), ("v002", 3, 0.0, True), ("v003", 3, -0.1, True)]), cfg)
        ck("judge 建议回滚→v001", j["level"] == "建议回滚" and j["target"] == "v001")
        j = judge(mk([("v001", 2, 0.3, True), ("v002", 1, 0.0, True), ("v003", 1, -0.1, True)]), cfg)
        ck("judge 样本少→告警不动作", j["level"] == "告警" and j["target"] == "v001")
        j = judge(mk([("v001", 6, 0.3, True), ("v002", 3, 0.35, True), ("v003", 3, 0.1, True)]), cfg)
        ck("judge 只一版差→观察", j["level"] == "观察")
        j = judge(mk([("~aa", 6, 0.3, False), ("v002", 3, 0.0, True), ("v003", 3, -0.1, True)]), cfg)
        ck("judge 参照无快照→降为告警", j["level"] == "告警" and j["target"] is None)
        ck("默认 auto=false", DEFAULT_CFG["auto"] is False)
        pr = prune(P, "foo", keep=1)
        idx = load_index(P, "foo")
        pv = [e["id"].split("_")[0] for e in idx["versions"] if e.get("pruned")]
        ck("prune 保留基线+最近+回滚涉及版本(只剪 v002)", pr["objects_dropped"] == 1 and pv == ["v002"])
        (pd / "rules.md").write_text("# R\n第五版\n", encoding="utf-8", newline="\n")
        snapshot(P, "foo", now=dt.datetime(2026, 10, 20, 23, 0))
        (pd / "rules.md").write_text("# R\n第六版\n", encoding="utf-8", newline="\n")
        snapshot(P, "foo", now=dt.datetime(2026, 10, 21, 23, 0))
        idx0 = load_index(P, "foo")
        idx0["events"] = []
        dump(P.sdir("foo") / "index.json", idx0)
        pr = prune(P, "foo", keep=1)
        idx = load_index(P, "foo")
        ck("prune 删中间版对象并标记", pr["objects_dropped"] >= 1 and any(e.get("pruned") for e in idx["versions"])
           and not idx["versions"][0].get("pruned") and not idx["versions"][-1].get("pruned"))
        try:
            rollback(P, "foo", "v005", dry=True)
            ck("回滚到已 prune 版本被拒", False)
        except SystemExit:
            ck("回滚到已 prune 版本被拒", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "全部通过" if not fails else f"{len(fails)} 项失败 {fails}")
    return 0 if not fails else 1


# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description="导师画像版本化 + 每版评估 + 可回滚(零 token)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("snapshot")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--skill")
    g.add_argument("--all", action="store_true")
    a.add_argument("--why", default="manual")
    a = sub.add_parser("log")
    a.add_argument("--skill", required=True)
    for name in ("metrics", "check"):
        a = sub.add_parser(name)
        a.add_argument("--since", default=START)
        a.add_argument("--until")
        if name == "check":
            a.add_argument("--apply", action="store_true", help="允许按 params.yaml persona_rollback.auto 真回滚(auto=false 时无效)")
    a = sub.add_parser("rollback")
    a.add_argument("--skill", required=True)
    a.add_argument("--to", required=True)
    a.add_argument("--why", default="manual")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--include-data", action="store_true", help="连 cases_auto/fills_rt 等数据文件一起还原(默认不动)")
    a.add_argument("--keep-extra", action="store_true", help="不删目标版里没有的权重文件")
    a.add_argument("--no-sync", action="store_true")
    a = sub.add_parser("prune")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--skill")
    g.add_argument("--all", action="store_true")
    a.add_argument("--keep", type=int, default=30)
    a.add_argument("--dry", action="store_true")
    a = sub.add_parser("export")
    a.add_argument("--skill", required=True)
    a.add_argument("--v", required=True)
    a.add_argument("--out", required=True)
    sub.add_parser("selftest")
    args = ap.parse_args()
    P = Paths()
    if args.cmd == "selftest":
        sys.exit(selftest())
    if args.cmd == "snapshot":
        sk = all_skills(P) if args.all else [args.skill]
        n_new = 0
        with vlock(P):
            for s in sk:
                if not P.persona(s).is_dir():
                    print(f"{s}: 无 persona/ 跳过")
                    continue
                e = snapshot(P, s, args.why)
                if e:
                    n_new += 1
                    ch = e["changed"]
                    print(f"{s}: 新版 {e['id']} 改{len(ch['modified'])}/增{len(ch['added'])}/删{len(ch['removed'])} 文件 "
                          f"+{e['lines']['added']}/-{e['lines']['removed']} 行 生效 {e['effective_from']}")
                else:
                    print(f"{s}: 无变化")
        print(f"JSON:{json.dumps({'skills': len(sk), 'new_versions': n_new}, ensure_ascii=False)}")
    elif args.cmd == "log":
        idx = load_index(P, args.skill)
        for e in idx["versions"]:
            ch = e["changed"]
            print(f"{e['id']}  生效 {e['effective_from']}  改{ch['modified']} 增{ch['added']} 删{ch['removed']}  "
                  f"+{e['lines']['added']}/-{e['lines']['removed']}  {e['why']}" + (f"  [回滚自 {e['rollback_of']}]" if e.get("rollback_of") else ""))
        for ev in idx["events"]:
            print("事件:", json.dumps(ev, ensure_ascii=False))
    elif args.cmd in ("metrics", "check"):
        res = metrics(P, args.since, args.until)
        od = P.vroot / "_metrics"
        dump(od / f"metrics_{res['until']}.json", res)
        write_atomic(od / f"metrics_{res['until']}.md", metrics_md(res))
        print(f"metrics → {od / ('metrics_' + res['until'] + '.md')}")
        if args.cmd == "check":
            c = check(P, res, load_cfg(P), apply=args.apply)
            dump(od / f"check_{res['until']}.json", c)
            write_atomic(od / f"check_{res['until']}.md", check_md(c))
            cnt = collections.Counter(j["level"] for j in c["skills"].values())
            for s, j in c["skills"].items():
                if j["level"] in ("告警", "建议回滚"):
                    print(f"!! {s}: {j['level']} → 目标 {j['target']}; {'; '.join(j['note'])}")
            print(f"check → {od / ('check_' + res['until'] + '.md')}")
            print(f"JSON:{json.dumps({'levels': cnt, 'auto': c['cfg']['auto'], 'actions': len(c['actions'])}, ensure_ascii=False)}")
    elif args.cmd == "rollback":
        if args.dry:
            r = rollback(P, args.skill, args.to, args.why, args.include_data, args.keep_extra, dry=True)
        else:
            with vlock(P):
                r = rollback(P, args.skill, args.to, args.why, args.include_data, args.keep_extra, sync=not args.no_sync)
        for act, rel in r["actions"]:
            print(f"  {act}: {rel}")
        print(f"JSON:{json.dumps({k: v for k, v in r.items() if k != 'actions'}, ensure_ascii=False)}")
    elif args.cmd == "prune":
        with vlock(P):
            for s in (all_skills(P) if args.all else [args.skill]):
                if P.sdir(s).is_dir():
                    r = prune(P, s, args.keep, args.dry)
                    print(f"{s}: {'(dry) ' if args.dry else ''}删对象 {r['objects_dropped']} 个 / {r['bytes_freed'] / 1e6:.2f} MB")
    elif args.cmd == "export":
        idx = load_index(P, args.skill)
        e = find_version(idx, args.v) or sys.exit(f"没有版本 {args.v}")
        out = Path(args.out).resolve()
        if out == P.persona(args.skill).resolve():
            sys.exit("export 不能写 persona/ 本身(那是 rollback 的事, 回滚要先存快照)")
        acts = restore_into(P, args.skill, e, out)
        print(f"export {e['id']} → {out}({len(acts)} 个文件)")


if __name__ == "__main__":
    main()
