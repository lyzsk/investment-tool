# -*- coding: utf-8 -*-
"""persona_versions.py — 导师 skill 当"模型权重"管: 版本化 + 每版评估 + 往前滚式回滚(零 token; 2026-10-16 晚建, TODO 二B-11;
                        10/18 用户批"全 skill 版本化": 版本单位从 persona/ 扩到整个 skill 目录 + 全局件另起一套 + 回滚=往前滚不丢蒸馏)

为什么: 每天蒸馏改写 skills/<skill>-skill/persona/ 下的文本(=导师的"权重"), 提示词(SKILL.md / workflows/chain.md)和全局件
        (params.yaml / chain_flags.txt / 驱动器)也常改, 但没人量"这次改完拟人度变好还是变差"——等于训练没有验证集。
        git 归用户手工提交, 所以本脚本自己存快照(不碰 git)。
版本单位(10/18 起):
  ① 每个 skill: skills/<skill>-skill/ 整个目录, 每个文件带类别 cls:
       画像  = persona/ 下人写/蒸馏写的文本(rules.md / profile.md / cases.md / language.md ...)
       提示词 = SKILL.md + workflows/*.md(含 chain.md) + 其他非 persona 文件(references/ 等)
       数据  = persona/ 下机器生成的: *.jsonl / orders_inferred.json / fingerprint.md / *_index.md / *.vec.json / ic.json /
               pools.json / case_log/
     版本哈希 = 全部"非整份重算(bulk)"文件; bulk = *.jsonl / cases_auto / fills_rt / case_log/(每晚整份重算): 只随版本存档,
     单独变化不升版本, 回滚默认不动(--include-data 才动)。
  ② 全局: skills_versions/_global/(同一套内容寻址方案, 全文快照不只哈希): scripts/dfcf/paper/params.yaml、
     scripts/claude_profile/chain_flags.txt、scripts/taoge-chain/run_chain.py; snapshot --all 时有变化就一起存。
  兼容: 10/18 之前的旧版本 manifest 只有 persona/ 文件(键=persona 内相对路径, cls=weight/data), 读取时统一规范成
       "persona/<名>" + 新类别(files_of); 旧版→新版第一次快照, SKILL.md/workflows 记为 changed.newly_tracked(新纳入, 不算改动)。
子命令:
  snapshot --skill X | --all | --global [--why ...]   内容哈希与上一版不同才存新版 skills_versions/<skill>/v<NNN>_<YYYYMMDD-HHMM>/
  log      --skill X(X=_global 看全局)                  列版本(含问题版本标记/撤回关系)
  metrics  [--since D] [--until D]           拟人度(mimicry 每日结果)+收益(books nav) 按"当日生效的画像版本"分段统计
  check    [--since D] [--until D]           只告警(10/18 用户定, --apply 已失效): 最近两版 vs 再前一段拟人度显著变差 →
                                             告警 + 给出可直接复制的 rollback 命令(含自动生成的证据文本)
  rollback --skill X --bad vXXX --reason R [--evidence E] [--dry] [--include-data] [--no-sync]
           默认=往前滚(像 git revert): 先给当前状态存快照; 只撤 vXXX 那次带进来的改动(vXXX 相对其父版的 diff 三方合并到
           当前文件上), vXXX 之后的蒸馏照留; 新开一版 vN+1(revert_of=vXXX); index.json 里给 vXXX 打「问题版本」标
           (原因/证据/状态/撤了哪些文件); 某文件三方合并冲突 → 不自动裁决, 该文件保持当前内容不动, 冲突块列在输出和
           index.json(status=待人工裁决); 机器生成的数据文件之后又变过 → 不合并, 列为"需重新生成"
  rollback --skill X --full --to vYYY --reason R [--bad vXXX] [--evidence E] [--keep-extra] [--include-data] [--dry] [--no-sync]
           整体还原到 vYYY(仍是新开一版, 不删任何版本; 旧格式 vYYY 只还原 persona/, 不动提示词)
           两种模式都: 被移除的画像规则文本追加进 skills_versions/<skill>/withdrawn.md(「已撤回」清单, 供蒸馏避免学回);
           改完跑 node scripts/sync_skills.mjs(--no-sync 跳过; _global 不跑)
  mark     --skill X --v vXXX --reason R [--evidence E] [--status S]   只打「问题版本」标/改状态(如人工裁决完改 已人工裁决), 不动文件
  prune    --skill X | --all [--keep 30] [--dry]  体积闸: 只留基线+最近 N 版+回滚/问题版本涉及版本的内容, 其余只留哈希/diff
  export   --skill X --v vNNN --out DIR      把某版完整还原到任意目录(看/比对用; skill 版按 skill 目录结构写, 旧格式版写到 DIR/persona/)
  selftest                                   全部在临时目录里测(整 skill/全局快照、往前滚撤回含冲突、--full、旧格式兼容), 不碰真实文件
存储:
  skills_versions/<skill>/index.json                  版本表(版本号/时刻/生效时刻/哈希/变更文件(分类别)/变更行数/why/代码指纹/问题版本标) + 回滚事件
  skills_versions/<skill>/objects/<sha256>.gz         内容寻址存储(gzip, 同内容只存一份 → 未改的文件跨版本零成本; 新旧格式共用)
  skills_versions/<skill>/v<NNN>_<时刻>/manifest.json 该版每个文件的 sha256/字节/行数/mtime/类别/bulk + 代码指纹明细(unit=skill|global; 无 unit=旧格式)
  skills_versions/<skill>/v<NNN>_<时刻>/diff.patch    相对上一版的 unified diff(数据 bulk 文件只记 +/− 行数)
  skills_versions/<skill>/withdrawn.md                「已撤回」清单(rollback 自动追加, 只增不删)
  skills_versions/_global/...                         全局件版本流(同上结构)
  skills_versions/_metrics/metrics_<止>.json/.md, check_<止>.json/.md
版本归属(D 日结果算哪一版): ①results/<skill>_chain/live-D/run_meta.jsonl 里 0915 那次运行记下的 rules/profile/cases/language
  sha12 与某版完全一致 → 就是那版(最准); ②有 run_meta 但对不上任何快照 → 伪版本 "~<哈希8位>"(真实存在过但没快照, 不可回滚);
  ③没有 run_meta → D 日 08:00 前生效的最新版; 都没有 → v000(基线前未版本化)。
用法: scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py <子命令> ...
硬约束: 不调 claude -p / 不写数据库 / 不做 git; 子进程 CREATE_NO_WINDOW; 只写 skills_versions/ 与(rollback 时)skills/<skill>-skill/
       (全局件的 rollback 会写对应全局文件, 慎用)。
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
DATA_NAMES = {"cases_auto.jsonl", "fills_rt.jsonl"}      # bulk: 每晚整份重算, 不升版本
GEN_NAMES = {"orders_inferred.json", "fingerprint.md", "ic.json", "pools.json"}   # 机器生成但链会读 → 类别=数据, 仍升版本
CAT_P, CAT_T, CAT_D, CAT_G = "画像", "提示词", "数据", "全局"
PERSONA_PREFIX = "persona/"
GLOBAL = "_global"
GLOBAL_FILES = ["scripts/dfcf/paper/params.yaml", "scripts/claude_profile/chain_flags.txt", "scripts/taoge-chain/run_chain.py"]
SKIP_RE = re.compile(r"(\.bak|\.tmp|\.lock|~$|\.pyc$|__pycache__)", re.I)
RUN_META_FILES = ("rules.md", "profile.md", "cases.md", "language.md")   # run_chain.record_rules_version 记的四个
DIFF_MAX_BYTES, DIFF_MAX_LINES = 1_600_000, 3000
# 同 mimicry_score.py MAIN / METRICS(每层一个主指标; err 类 lift=基线误差−链误差)
MAIN = [("L1_交易", "acc"), ("L2_方向", "acc"), ("L3_持仓Jaccard", "sim"), ("L4_总仓误差", "err")]
CHAIN_CODE = ["scripts/taoge-chain/run_chain.py", "skills/{s}-skill/workflows/chain.md", "skills/{s}-skill/SKILL.md",
              "scripts/dfcf/paper/params.yaml"]
DISTILL_CODE = ["skills/{s}-skill/workflows/distill.md", "scripts/tzzb/distill_daily.py", "scripts/tzzb/llm_batch_tzzb.py",
                "scripts/tzzb/mentor_fingerprint.py", "scripts/backfill_bilibili/backfill_bilibili.py",
                "scripts/md/gen_profile_index.py", "scripts/md/gen_rules_index.mjs", "scripts/md/check_md_daily.py"]
DEFAULT_CFG = {   # params.yaml 顶层 persona_rollback: 下同名键覆盖(文件里没有这一节=全用默认)
    "auto": False,             # 10/18 起失效(check 只告警, 回滚须人工 rollback --reason/--evidence); 保留键只为读旧 params 不报错
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

    def skill_dir(self, s):
        return self.skills / f"{s}-skill"

    def persona(self, s):
        return self.skill_dir(s) / "persona"

    def base(self, s):
        """版本单位的根: skill=skills/<s>-skill/, 全局=仓库根(GLOBAL_FILES 相对它)"""
        return self.root if s == GLOBAL else self.skill_dir(s)

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


def is_bulk(rel):
    """整份重算的数据(不升版本): *.jsonl / cases_auto / fills_rt / case_log/ 下一切"""
    return Path(rel).name in DATA_NAMES or rel.endswith(".jsonl") or "case_log/" in f"/{rel}"


def classify(rel):
    """skill 目录内相对路径 → 画像 / 提示词 / 数据"""
    if not rel.startswith(PERSONA_PREFIX):
        return CAT_T
    name = Path(rel).name
    if is_bulk(rel) or name in GEN_NAMES or name.endswith("_index.md") or name.endswith(".vec.json"):
        return CAT_D
    return CAT_P


def all_skills(P):
    """skills/ 下所有 *-skill 目录(有文件即算; 10/18 起不再要求有 persona/)"""
    return [d.name[:-len("-skill")] for d in sorted(P.skills.glob("*-skill"))
            if d.is_dir() and any(f.is_file() for f in d.rglob("*"))]


def fmeta(f, cls, bulk, b=None):
    b = f.read_bytes() if b is None else b
    return {"sha256": sha256b(b), "bytes": len(b), "lines": b.count(b"\n") + (1 if b and not b.endswith(b"\n") else 0),
            "mtime": dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"), "cls": cls, "bulk": bulk}


def scan(sdir_):
    """skill 目录 → {相对路径: meta}"""
    files = {}
    if not sdir_.is_dir():
        return files
    for f in sorted(sdir_.rglob("*")):
        rel = f.relative_to(sdir_).as_posix()
        if not f.is_file() or SKIP_RE.search(rel):
            continue
        files[rel] = fmeta(f, classify(rel), is_bulk(rel))
    return files


def cur_files(P, s, dest):
    """dest 下当前文件(全局=只看 GLOBAL_FILES; skill=整目录)"""
    dest = Path(dest)
    if s == GLOBAL:
        return {r: fmeta(dest / r, CAT_G, False) for r in GLOBAL_FILES if (dest / r).is_file()}
    return scan(dest)


def unit_files(P, s):
    return cur_files(P, s, P.base(s))


def combo(files, bulk=False):
    s = "\n".join(f"{r}\t{m['sha256']}" for r, m in sorted(files.items()) if bool(m.get("bulk")) == bulk)
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


def is_legacy(man):
    """10/18 前的旧格式(只有 persona/, 键=persona 内相对路径)"""
    return not (man or {}).get("unit")


def files_of(P, s, e, man=None):
    """某版文件表, 统一成 skill 目录内相对路径 + 新类别(旧格式 'rules.md' → 'persona/rules.md', weight/data → 画像/数据 + bulk)"""
    man = man if man is not None else (manifest(P, s, e) or {})
    fs = man.get("files") or {}
    if not is_legacy(man):
        return fs
    out = {}
    for r, m in fs.items():
        nr = PERSONA_PREFIX + r
        out[nr] = dict(m, cls=classify(nr), bulk=m.get("cls") == "data")
    return out


def scope_of(P, s, e):
    """该版覆盖的范围前缀: 旧格式只管 persona/, 新格式整个 skill 目录(全局=固定清单)"""
    return PERSONA_PREFIX if is_legacy(manifest(P, s, e)) else ""


def vhash(e):
    return e.get("version_hash") or e.get("persona_hash")


def line_delta(a, b):
    ca = collections.Counter(a.splitlines())
    cb = collections.Counter(b.splitlines())
    return sum((cb - ca).values()), sum((ca - cb).values())


def snapshot(P, s, why="manual", now=None, extra=None, force_data=False, force=False):
    """版本哈希(全部非 bulk 文件)与上一版相同 → 返回 None; force_data=True 时 bulk 数据变了也存(供 --include-data 回滚前保存);
    force=True 无变化也开新版(回滚事件要在版本时间线上留一版); 否则存新版"""
    base = P.base(s)
    files = unit_files(P, s)
    if not files:
        return None
    idx = load_index(P, s)
    vh, dh = combo(files, False), combo(files, True)
    last = idx["versions"][-1] if idx["versions"] else None
    if last and not force and vhash(last) == vh and not (force_data and last.get("data_hash") != dh):
        return None
    now = now or dt.datetime.now()
    for rel in files:
        b = (base / rel).read_bytes()
        if put_obj(P, s, b) != files[rel]["sha256"]:   # 扫描与存档之间文件被改 → 以存进去的为准
            files[rel] = fmeta(base / rel, files[rel]["cls"], files[rel]["bulk"], b)
    vh, dh = combo(files, False), combo(files, True)
    lman = manifest(P, s, last) if last else None
    pm = files_of(P, s, last, lman) if last else {}
    legacy_prev = bool(last) and is_legacy(lman)
    nb_now = {r for r, m in files.items() if not m["bulk"]}
    nb_old = {r for r, m in pm.items() if not m["bulk"]}
    new_r = sorted(nb_now - nb_old)
    tracked = [r for r in new_r if legacy_prev and not r.startswith(PERSONA_PREFIX)]   # 旧格式→整 skill: 新纳入, 不算改动
    added = [r for r in new_r if r not in tracked]
    removed = sorted(nb_old - nb_now)
    modified = sorted(r for r in nb_now & nb_old if files[r]["sha256"] != pm[r]["sha256"])
    data_changed = sorted(r for r, m in files.items() if m["bulk"] and (r not in pm or pm[r]["sha256"] != m["sha256"]))
    by_cat = {}
    for r in added + modified + removed:
        by_cat.setdefault((files.get(r) or pm.get(r))["cls"], []).append(r)
    vnum = (last["v"] + 1) if last else 1
    vid = f"v{vnum:03d}_{now:%Y%m%d-%H%M}"
    vdir = P.sdir(s) / vid
    plus = minus = 0
    patch = []
    for r in added + modified + removed:
        old = get_obj(P, s, pm[r]["sha256"]).decode("utf-8", "replace") if r in pm else ""
        new = (base / r).read_bytes().decode("utf-8", "replace") if r in files else ""
        a, m_ = line_delta(old, new)
        plus, minus = plus + a, minus + m_
        if last and not r.endswith(".vec.json") and max(len(old), len(new)) <= DIFF_MAX_BYTES:
            d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"{last['id']}/{r}", f"{vid}/{r}", lineterm="", n=2))
            if len(d) > DIFF_MAX_LINES:
                d = d[:DIFF_MAX_LINES] + [f"... (截断, 共 {len(d)} 行; 全文用 export 取)"]
            patch += d
        elif last:
            patch.append(f"=== {r}: 体积大/向量索引, 不出 diff(+{a}/-{m_} 行; 全文用 export 取)")
    for r in tracked:
        patch.append(f"=== 新纳入版本化(10/18 全 skill 版本化, 非改动): {r}({files[r]['lines']} 行; 全文用 export 取)")
    # 生效时刻 = 变更文件最晚 mtime(内容最晚何时成形), 不早于上一版快照时刻, 不晚于本次快照
    mt = [files[r]["mtime"] for r in added + modified]
    eff = max(mt) if mt else now.isoformat(timespec="seconds")
    if last:
        eff = max(eff, last["ts"])
    eff = min(eff, now.isoformat(timespec="seconds"))
    code = code_fp(P, s) if s != GLOBAL else None
    cat_hash = {c: combo({r: m for r, m in files.items() if m["cls"] == c and not m["bulk"]})
                for c in sorted({m["cls"] for m in files.values()})}
    e = {"v": vnum, "id": vid, "ts": now.isoformat(timespec="seconds"), "effective_from": eff,
         "unit": "global" if s == GLOBAL else "skill", "version_hash": vh, "cat_hash": cat_hash, "data_hash": dh,
         "parent": last["id"] if last else None,
         "changed": {"added": added, "modified": modified, "removed": removed} | ({"newly_tracked": tracked} if tracked else {}),
         "changed_by_cat": by_cat, "data_changed": data_changed, "lines": {"added": plus, "removed": minus},
         "bytes_weight": sum(m["bytes"] for m in files.values() if not m["bulk"]),
         "why": why, "code": {"chain": code["chain"], "distill": code["distill"]} if code else None} | (extra or {})
    dump(vdir / "manifest.json", {"skill": s, "unit": e["unit"], "version": e, "files": files, "code": code})
    if patch:
        write_atomic(vdir / "diff.patch", "\n".join(patch) + "\n")
    idx["versions"].append(e)
    try:   # 10/18 用户定: 退出 paper 的导师在版本库里也分开标(group=excluded), 顶层另有 skills_versions/EXCLUDED.md 名单
        _ex = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tzzb" / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded") or {}
        idx["group"] = "excluded" if s in _ex else ("instrument" if s in ("bank", "nasdaq") else "active")   # 10/18: 品种 skill(银行股/纳指)单独一组
    except (OSError, ValueError):
        pass
    dump(P.sdir(s) / "index.json", idx)
    return e


def restore_into(P, s, e, dest, include_data=True, keep_extra=True, dry=False):
    """把版本 e 的文件写进 dest(rollback --full: dest=skill 目录; export: 任意目录)。返回动作清单。
    keep_extra=False 只删 e 的覆盖范围内(旧格式=persona/)多出来的文件, 范围外(如旧格式版的 SKILL.md/workflows)不动"""
    dest = Path(dest)
    files = files_of(P, s, e)
    want = {r: m for r, m in files.items() if include_data or not m["bulk"]}
    cur = cur_files(P, s, dest)
    acts = []
    for r, m in sorted(want.items()):
        if r in cur and cur[r]["sha256"] == m["sha256"]:
            continue
        acts.append(("写回" if r in cur else "新建", r))
        if not dry:
            write_atomic(dest / r, get_obj(P, s, m["sha256"]))   # 新写入 → mtime=现在(生效时刻正确)
    if not keep_extra:
        scope = scope_of(P, s, e)
        for r, m in sorted(cur.items()):
            if r not in want and r.startswith(scope) and (include_data or not m["bulk"]):
                acts.append(("删除(内容仍在之前的版本里)", r))
                if not dry:
                    (dest / r).unlink()
    return acts


def run_sync(P):
    r = subprocess.run(["node", "scripts/sync_skills.mjs"], cwd=P.root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout or "")[-400:] + (r.stderr or "")[-400:]


# ---------------- 往前滚式回滚(10/18 用户定: 回滚永不丢蒸馏历史) ----------------
def _trunc(t, n=600):
    return t if len(t) <= n else t[:n] + f"…(共 {len(t)} 字)"


def merge3(base, ours, theirs):
    """行级三方合并。base=问题版本 vXXX 的内容, ours=当前文件, theirs=vXXX 的父版本(撤回目标)。
    两边改动区间重叠或相邻(含同点插入)且结果不同 → 冲突(保守, 同 diff3)。返回 (合并后行列表 | None, 冲突块列表)"""
    def regions(other, side):
        sm = difflib.SequenceMatcher(None, base, other, autojunk=False)
        return [(i1, i2, side, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]

    def ver(rs, lo, hi):
        o, p = [], lo
        for i1, i2, _, rep in sorted(rs, key=lambda x: (x[0], x[1])):
            o += base[p:i1] + rep
            p = i2
        return o + base[p:hi]
    regs = sorted(regions(ours, "o") + regions(theirs, "t"), key=lambda x: (x[0], x[1]))
    clusters = []
    for r in regs:
        if clusters and r[0] <= clusters[-1][1]:
            clusters[-1][1] = max(clusters[-1][1], r[1])
            clusters[-1][2].append(r)
        else:
            clusters.append([r[0], r[1], [r]])
    out, pos, hunks = [], 0, []
    for lo, hi, rs in clusters:
        out += base[pos:lo]
        os_, ts = [r for r in rs if r[2] == "o"], [r for r in rs if r[2] == "t"]
        vo, vt = ver(os_, lo, hi), ver(ts, lo, hi)
        if not ts or vo == vt:
            out += vo
        elif not os_:
            out += vt
        else:
            hunks.append({"问题版本行": f"{lo + 1}-{hi}" if hi > lo else f"{lo}后插入", "问题版本": _trunc("".join(base[lo:hi])),
                          "当前": _trunc("".join(vo)), "撤回目标": _trunc("".join(vt))})
            out += vo
        pos = hi
    out += base[pos:]
    return (None if hunks else out), hunks


def plus_lines(old_b, new_b):
    """new 里有、old 里没有的非空行(=被撤回/移除的规则文本)"""
    o = collections.Counter((old_b or b"").decode("utf-8", "replace").splitlines())
    out = []
    for ln in (new_b or b"").decode("utf-8", "replace").splitlines():
        if not ln.strip():
            continue
        if o[ln] > 0:
            o[ln] -= 1
            continue
        out.append(ln)
    return out


def revert_plan(P, s, A, B, include_data=False):
    """撤回 B(=问题版本, 父版本 A)带进来的改动 → 逐文件计划(不写盘)。
    kind: 撤回(当前=B 原样, 直接还原成 A) / 撤回·三方合并(保留 B 之后的改动) / 已是撤回态 / 冲突 / 需重新生成(机器生成文件之后又变过)"""
    fa, fb = files_of(P, s, A), files_of(P, s, B)
    scope = scope_of(P, s, A)   # 父版是旧格式 → 只比 persona/(否则 SKILL.md 等"新纳入"会被当成 B 新增而误删)
    base = P.base(s)
    rels = sorted(r for r in set(fa) | set(fb)
                  if r.startswith(scope) and (fa.get(r) or {}).get("sha256") != (fb.get(r) or {}).get("sha256")
                  and (include_data or not (fb.get(r) or fa.get(r))["bulk"]))
    plan = []
    for r in rels:
        m = fb.get(r) or fa[r]
        a = get_obj(P, s, fa[r]["sha256"]) if r in fa else None
        b = get_obj(P, s, fb[r]["sha256"]) if r in fb else None
        c = (base / r).read_bytes() if (base / r).is_file() else None
        it = {"file": r, "cls": m["cls"]}
        if c == a:
            it["kind"] = "已是撤回态"
        elif c == b:
            it.update(kind="撤回", new=a)
        elif m["cls"] == CAT_D:
            it["kind"] = "需重新生成"
        elif a is None or b is None or c is None:
            why = ("问题版本新增了该文件, 之后又被改过(整文件删除会丢后续改动)" if a is None else
                   "问题版本删除了该文件, 之后又重建过" if b is None else "该文件当前已被删除")
            it.update(kind="冲突", hunks=[{"问题版本行": "整文件", "说明": why}])
        else:
            try:
                tb, tc, ta = (x.decode("utf-8") for x in (b, c, a))
            except UnicodeDecodeError:
                it.update(kind="冲突", hunks=[{"问题版本行": "整文件", "说明": "非 UTF-8 文本, 不做行合并"}])
                plan.append(it)
                continue
            merged, hunks = merge3(tb.splitlines(True), tc.splitlines(True), ta.splitlines(True))
            if hunks:
                it.update(kind="冲突", hunks=hunks)
            else:
                it.update(kind="撤回·三方合并", new="".join(merged).encode("utf-8"))
        if it["kind"].startswith("撤回") and m["cls"] == CAT_P:
            it["withdrawn"] = plus_lines(a, b)
        plan.append(it)
    return plan


def append_withdrawn(P, s, head, withdrawn, conflicts=(), regen=()):
    """skills_versions/<skill>/withdrawn.md: 「已撤回」清单, 只增不删(供蒸馏避免把撤掉的规则又学回来)"""
    f = P.sdir(s) / "withdrawn.md"
    old = f.read_text(encoding="utf-8") if f.exists() else (
        f"# {s} 已撤回清单\n\n> persona_versions.py rollback 自动追加, 只增不删(人工可编辑/加注)。下列是因「问题版本」被撤回或整体还原而"
        "从画像里移除的规则文本——蒸馏时不要把这些内容再学回 persona; 确有新证据要恢复时, 在对应条目下注明证据。\n\n")
    L = head + [""]
    for r, lines in withdrawn.items():
        L.append(f"### {r}")
        L += [f"- {_trunc(x, 400)}" for x in lines[:200]]
        if len(lines) > 200:
            L.append(f"- …(另 {len(lines) - 200} 行, 全文见问题版本的 diff.patch)")
        L.append("")
    if conflicts:
        L.append("### 待人工裁决(冲突, 未撤; 当前文件保持原样, 冲突块见 index.json 该版 problem.conflicts)")
        L += [f"- {c['file']}: {len(c['hunks'])} 处" for c in conflicts] + [""]
    if regen:
        L.append("### 需重新生成(机器生成文件, 未撤; 重跑对应生成器后再 snapshot)")
        L += [f"- {r}" for r in regen] + [""]
    write_atomic(f, old + "\n".join(L) + "\n")


def _set_problem(idx, vid, mark):
    e = find_version(idx, vid)
    if e.get("problem"):
        e.setdefault("problem_history", []).append(e["problem"])
    e["problem"] = mark


def rollback(P, s, bad=None, to=None, reason="", evidence="", full=False, include_data=False, keep_extra=False,
             sync=True, dry=False, sync_fn=None):
    """往前滚: 永不删版本、永不丢蒸馏。默认撤回 bad 那一版带进来的改动; full=True 整体还原到 to(仍开新版)。见模块说明"""
    idx = load_index(P, s)
    if not idx["versions"]:
        raise SystemExit(f"{s}: 没有任何版本")
    last_id = idx["versions"][-1]["id"]
    B = find_version(idx, bad) if bad else None
    if bad and not B:
        raise SystemExit(f"{s}: 没有版本 {bad}(用 log --skill {s} 看)")
    base = P.base(s)
    conflicts, regen, withdrawn, plan, acts = [], [], {}, [], []
    if full:
        T = find_version(idx, to) if to else None
        if not T:
            raise SystemExit(f"{s}: --full 需要 --to 目标版本(没有 {to})")
        tf = files_of(P, s, T)
        for m in tf.values():          # 先验对象完整, 再动文件
            if include_data or not m["bulk"]:
                get_obj(P, s, m["sha256"])
        if dry:
            return {"dry": True, "mode": "full", "to": T["id"], "actions": restore_into(P, s, T, base, include_data, keep_extra, dry=True)}
        pre = snapshot(P, s, why=f"rollback 前自动保存(整体还原→{T['id']})", force_data=include_data)
        scope = scope_of(P, s, T)
        for r, m in cur_files(P, s, base).items():
            if r.startswith(scope) and m["cls"] == CAT_P and (r not in tf or tf[r]["sha256"] != m["sha256"]):
                ls = plus_lines(get_obj(P, s, tf[r]["sha256"]) if r in tf else b"", (base / r).read_bytes())
                if ls:
                    withdrawn[r] = ls
        acts = restore_into(P, s, T, base, include_data, keep_extra)
        status = "已整体还原"
        post = snapshot(P, s, why=f"整体还原→{T['id']}(往前滚): {reason}",
                        extra={"restore_of": T["id"]} | ({"revert_of": B["id"]} if B else {}), force=True)
    else:
        if not B:
            raise SystemExit("默认模式需要 --bad vXXX(问题版本); 整体还原用 --full --to vYYY")
        if not B.get("parent"):
            raise SystemExit(f"{s}: {B['id']} 是基线版(无父版本), 没有'它带进来的改动'可撤; 整体还原用 --full --to")
        A = find_version(idx, B["parent"])
        if not A:
            raise SystemExit(f"{s}: {B['id']} 的父版本 {B['parent']} 不在 index.json")
        T = None
        if dry:
            plan = revert_plan(P, s, A, B, include_data)
            return {"dry": True, "mode": "revert", "bad": B["id"], "actions": [(it["kind"], it["file"]) for it in plan],
                    "conflicts": [{"file": it["file"], "hunks": it["hunks"]} for it in plan if it["kind"] == "冲突"]}
        pre = snapshot(P, s, why=f"rollback 前自动保存(撤回 {B['id']})", force_data=include_data)
        plan = revert_plan(P, s, A, B, include_data)
        for it in plan:
            if it["kind"].startswith("撤回"):
                if it["new"] is None:
                    (base / it["file"]).unlink()
                else:
                    write_atomic(base / it["file"], it["new"])
            if it.get("withdrawn"):
                withdrawn[it["file"]] = it["withdrawn"]
        acts = [(it["kind"], it["file"]) for it in plan]
        conflicts = [{"file": it["file"], "hunks": it["hunks"]} for it in plan if it["kind"] == "冲突"]
        regen = [it["file"] for it in plan if it["kind"] == "需重新生成"]
        n_ok = sum(1 for it in plan if it["kind"].startswith("撤回"))
        status = "已撤回" if not conflicts else ("部分撤回·待人工裁决" if n_ok else "待人工裁决")
        post = snapshot(P, s, why=f"撤回 {B['id']} 的改动(往前滚): {reason}", extra={"revert_of": B["id"], "revert_status": status}, force=True)
    cur_v = pre["id"] if pre else last_id
    idx = load_index(P, s)
    ts = now_s()
    if B:
        _set_problem(idx, B["id"], {"标记": "问题版本", "status": status, "reason": reason, "evidence": evidence, "marked_at": ts,
                                    "mode": "full" if full else "revert", "handled_by": post["id"], "restore_to": T["id"] if T else None,
                                    "reverted_files": [r for k, r in acts if k.startswith(("撤回", "写回", "新建", "删除"))],
                                    "conflicts": conflicts, "regen_needed": regen})
    ev = {"ts": ts, "type": "full_restore" if full else "revert", "bad": B["id"] if B else None, "to": T["id"] if T else None,
          "from": cur_v, "new_version": post["id"], "reason": reason, "evidence": evidence, "status": status,
          "files": len([a for a in acts if a[0] not in ("已是撤回态",)]), "conflicts": len(conflicts), "include_data": include_data}
    if withdrawn or conflicts or regen:
        what = f"撤回 {B['id']}" if not full else f"整体还原→{T['id']}" + (f"(问题版本 {B['id']})" if B else "")
        append_withdrawn(P, s, [f"## {ts} {what} → 新版 {post['id']}", f"- 原因: {reason}", f"- 证据: {evidence or '—'}",
                                f"- 状态: {status}"], withdrawn, conflicts, regen)
    sres = None
    if sync and s != GLOBAL:
        rc, out = (sync_fn or run_sync)(P)
        sres = {"rc": rc, "tail": out[-300:]}
        ev["sync_rc"] = rc
    idx["events"].append(ev)
    dump(P.sdir(s) / "index.json", idx)
    return {"mode": ev["type"], "bad": ev["bad"], "to": ev["to"], "from": cur_v, "new_version": post["id"], "status": status,
            "actions": acts, "conflicts": conflicts, "regen_needed": regen, "withdrawn_lines": sum(len(v) for v in withdrawn.values()),
            "persona_changed": any(r.startswith(PERSONA_PREFIX) for k, r in acts if k.startswith(("撤回", "写回", "新建", "删除"))), "sync": sres}


def mark(P, s, v, reason, evidence="", status="问题版本(未处理)"):
    """只打标/改状态, 不动文件(例: 冲突人工裁决完 → status=已人工裁决)"""
    idx = load_index(P, s)
    e = find_version(idx, v)
    if not e:
        raise SystemExit(f"{s}: 没有版本 {v}")
    _set_problem(idx, e["id"], {"标记": "问题版本", "status": status, "reason": reason, "evidence": evidence, "marked_at": now_s(), "mode": "mark"})
    idx["events"].append({"ts": now_s(), "type": "mark", "bad": e["id"], "status": status, "reason": reason, "evidence": evidence})
    dump(P.sdir(s) / "index.json", idx)
    return e["id"]


def prune(P, s, keep=30, dry=False):
    """体积闸: 只保留 v001(基线) + 最近 keep 个版本 + 回滚事件/问题版本涉及的版本(及问题版本的父版本)的文件内容;
    其余版本只留 manifest/diff(哈希+行数), 不可再回滚"""
    idx = load_index(P, s)
    vs = idx["versions"]
    pin = {vs[0]["id"]} if vs else set()
    pin |= {e["id"] for e in vs[-keep:]} if keep > 0 else set()
    pin |= {x for ev in idx["events"] for x in (ev.get(k) for k in ("from", "to", "new_version", "bad")) if x}
    pin |= {x for e in vs if e.get("problem") for x in (e["id"], e.get("parent")) if x}
    pin = {(find_version(idx, x) or {}).get("id", x) for x in pin}
    need = set()
    for e in vs:
        if e["id"] in pin:
            need |= {m["sha256"] for m in files_of(P, s, e).values()}
    od = P.sdir(s) / "objects"
    drop = [f for f in od.glob("*.gz") if f.stem not in need] if od.is_dir() else []
    freed = sum(f.stat().st_size for f in drop)
    if not dry:
        for f in drop:
            f.unlink()
        for e in vs:
            if e["id"] not in pin and not e.get("pruned"):
                fs = files_of(P, s, e)
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
            fs = cache.setdefault(e["id"], files_of(P, s, e))   # 新旧格式统一成 persona/<名>
            ok = all((fs.get(PERSONA_PREFIX + n) or {}).get("sha256", "")[:12] == rm["sha"].get(n) if n in rm["sha"]
                     else PERSONA_PREFIX + n not in fs for n in RUN_META_FILES)
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


def suggest(s, j):
    """告警/建议回滚 → 可直接复制的往前滚命令(问题版本=最近两版里较早的那版, 证据=本次判定的数)"""
    if j["level"] not in ("告警", "建议回滚") or not j["recent"]:
        return None
    bad = j["recent"][0]["v"]
    ci = j.get("diff_ci") or [None, None]
    ev = (f"check {dt.date.today().isoformat()} 口径={j['baseline']}: 参照 " + ",".join(f"{x['v']}({x['n']}天 综合{num(x['mean'])})" for x in j["ref"])
          + "; 最近 " + ",".join(f"{x['v']}({x['n']}天 综合{num(x['mean'])} 比参照{num(x['vs_ref'])})" for x in j["recent"])
          + f"; 差 95% [{num(ci[0])}, {num(ci[1])}]")
    if bad.startswith("~") or bad == "v000":
        return {"bad": None, "evidence": ev, "cmd": None, "note": f"问题段 {bad} 没有快照, 无法按版本撤回; 可 --full --to {j['target'] or '?'}"}
    cmd = (f'scripts/venv/Scripts/python.exe -X utf8 scripts/skills_ver/persona_versions.py rollback --skill {s} --bad {bad} '
           f'--reason "check {j["level"]}: 拟人度综合 lift 变差" --evidence "{ev}" --dry')
    return {"bad": bad, "evidence": ev, "cmd": cmd, "full_target": j["target"]}


def check(P, res, cfg, apply=False):
    """10/18 用户定: 只告警。回滚=往前滚, 必须人工带原因/证据跑 rollback; --apply / params auto 不再触发任何文件改动"""
    out = {"generated_at": now_s(), "cfg": cfg, "skills": {}, "actions": []}
    for s, sk in res["skills"].items():
        j = judge(sk, cfg)
        j["suggest"] = suggest(s, j)
        out["skills"][s] = j
    if apply or cfg.get("auto"):
        out["actions"].append({"skip": "10/18 起 check 只告警(回滚=往前滚, 须人工带 --reason/--evidence 跑 rollback); --apply / auto 已失效"})
    return out


def check_md(c):
    L = [f"# 画像版本 check {c['generated_at']}", "",
         f"> 只告警(10/18 起不自动回滚; params auto={c['cfg']['auto']} 已失效, 来源 {c['cfg']['_src']}); 主口径 baseline={c['cfg']['baseline']}; "
         f"delta={c['cfg']['delta']}; 建议回滚门槛: 参照 ≥{c['cfg']['min_ref_days']} 天 + 最近两版 ≥{c['cfg']['min_recent_days']} 天 + bootstrap 95% 上界<0", "",
         "| skill | 判定 | 口径 | 参照段(天/综合) | 最近两版(天/综合/比参照) | 差 95% | 整体还原目标 | 说明 |", "|---|---|---|---|---|---|---|---|"]
    for s, j in c["skills"].items():
        ref = ", ".join(f"{x['v']}({x['n']}/{num(x['mean'])})" for x in j["ref"]) or "—"
        rec = ", ".join(f"{x['v']}({x['n']}/{num(x['mean'])}/{num(x['vs_ref'])})" for x in j["recent"]) or "—"
        ci = j.get("diff_ci") or [None, None]
        L.append(f"| {s} | {j['level']} | {j['baseline']} | {ref} | {rec} | [{num(ci[0])}, {num(ci[1])}] | {j['target'] or '—'} | {'; '.join(j['note']) or ''} |")
    sg = [(s, j["suggest"]) for s, j in c["skills"].items() if j.get("suggest")]
    if sg:
        L += ["", "## 建议命令(往前滚, 先 --dry 看计划, 确认后去掉 --dry)", ""]
        for s, x in sg:
            L.append(f"- {s}: `{x['cmd']}`" if x.get("cmd") else f"- {s}: {x.get('note')}")
    L += ["", "动作: " + (json.dumps(c["actions"], ensure_ascii=False) if c["actions"] else "无(只告警)"), ""]
    return "\n".join(L)


# ---------------- selftest ----------------
def _legacy_snapshot(P, s, now):
    """selftest 用: 按 10/18 前的旧格式(只 persona/, 键=persona 内相对路径, cls=weight/data, manifest 无 unit)造一版"""
    pdir = P.persona(s)
    files = {}
    for f in sorted(pdir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(pdir).as_posix()
            b = f.read_bytes()
            files[rel] = {"sha256": put_obj(P, s, b), "bytes": len(b), "lines": b.count(b"\n"),
                          "mtime": now.isoformat(timespec="seconds"), "cls": "data" if rel.endswith(".jsonl") else "weight"}
    ph = sha256b("\n".join(f"{r}\t{m['sha256']}" for r, m in sorted(files.items()) if m["cls"] == "weight").encode())
    idx = load_index(P, s)
    last = idx["versions"][-1] if idx["versions"] else None
    vnum = last["v"] + 1 if last else 1
    vid = f"v{vnum:03d}_{now:%Y%m%d-%H%M}"
    e = {"v": vnum, "id": vid, "ts": now.isoformat(timespec="seconds"), "effective_from": now.isoformat(timespec="seconds"),
         "persona_hash": ph, "data_hash": "x", "parent": last["id"] if last else None,
         "changed": {"added": sorted(files), "modified": [], "removed": []}, "data_changed": [],
         "lines": {"added": 0, "removed": 0}, "bytes_weight": 0, "why": "旧格式", "code": {}}
    dump(P.sdir(s) / vid / "manifest.json", {"skill": s, "version": e, "files": files, "code": {}})
    idx["versions"].append(e)
    try:   # 10/18 用户定: 退出 paper 的导师在版本库里也分开标(group=excluded), 顶层另有 skills_versions/EXCLUDED.md 名单
        _ex = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tzzb" / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded") or {}
        idx["group"] = "excluded" if s in _ex else ("instrument" if s in ("bank", "nasdaq") else "active")   # 10/18: 品种 skill(银行股/纳指)单独一组
    except (OSError, ValueError):
        pass
    dump(P.sdir(s) / "index.json", idx)
    return e


def selftest():
    fails = []

    def ck(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    def W(p, t):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8", newline="\n")

    def R(p):
        return p.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="pv_selftest_"))
    synced = []
    sf = lambda p: (synced.append(1), (0, "ok"))[1]  # noqa: E731
    try:
        P = Paths(tmp, tmp / "skills_versions")
        sd, pd = P.skill_dir("foo"), P.persona("foo")
        R0 = "# R\nA1 买\nA2 卖\nA3 观望\n"
        W(sd / "SKILL.md", "skill v1\n")
        W(sd / "workflows" / "chain.md", "step01 模板\n")
        W(pd / "rules.md", R0)
        W(pd / "profile.md", "画像 v1\n")
        W(pd / "cases_auto.jsonl", '{"a":1}\n')
        # ---- 旧格式(persona-only)兼容 ----
        L1 = _legacy_snapshot(P, "foo", dt.datetime(2026, 10, 12, 22, 0))
        R1 = R0 + "L9 旧格式坏规则\n"
        W(pd / "rules.md", R1)
        L2 = _legacy_snapshot(P, "foo", dt.datetime(2026, 10, 12, 23, 0))
        fl = files_of(P, "foo", L1)
        ck("旧格式 manifest 规范成 persona/<名> + 新类别", set(fl) == {"persona/rules.md", "persona/profile.md", "persona/cases_auto.jsonl"}
           and fl["persona/rules.md"]["cls"] == CAT_P and fl["persona/cases_auto.jsonl"]["bulk"] and not fl["persona/rules.md"]["bulk"])
        ex = tmp / "exp"
        restore_into(P, "foo", L1, ex)
        ck("export 旧格式版 → <out>/persona/", R(ex / "persona" / "rules.md") == R0 and not (ex / "SKILL.md").exists())
        e3 = snapshot(P, "foo", "迁移", now=dt.datetime(2026, 10, 13, 22, 0))
        ck("旧→新首版: 提示词记为新纳入, 不算改动", bool(e3) and e3["unit"] == "skill" and e3["parent"] == L2["id"]
           and e3["changed"].get("newly_tracked") == ["SKILL.md", "workflows/chain.md"]
           and not (e3["changed"]["added"] or e3["changed"]["modified"] or e3["changed"]["removed"]) and e3["lines"] == {"added": 0, "removed": 0})
        ck("撤回迁移版的计划为空(不误删 SKILL.md)", revert_plan(P, "foo", L2, e3) == [])
        ck("无变化不升版", snapshot(P, "foo", now=dt.datetime(2026, 10, 13, 22, 1)) is None)
        W(pd / "cases_auto.jsonl", '{"a":1}\n{"a":2}\n')
        ck("只改 bulk 数据不升版", snapshot(P, "foo", now=dt.datetime(2026, 10, 13, 22, 2)) is None)
        # 归属: run_meta 哈希(旧格式版也能命中) / 未快照 / v000
        sha = lambda t: sha256b(t.encode())[:12]  # noqa: E731

        def meta(d, rules, prof="画像 v1\n"):
            f = P.results / "foo_chain" / f"live-{d.replace('-', '')}" / "run_meta.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"ts": f"{d}T08:15:00", "dry": False, "asof": None, "chain_md_sha12": "x", "flags": {},
                                     "persona": {"rules.md": {"sha12": sha(rules)}, "profile.md": {"sha12": sha(prof)}}}) + "\n", encoding="utf-8")
        meta("2026-10-13", R1)
        meta("2026-10-14", "# R\n别的\n")
        idx = load_index(P, "foo")
        a13 = attribute(P, "foo", idx, "2026-10-13", {})
        ck(f"归属 run_meta 命中旧格式版 v002 {a13[:2]}", a13[:3] == ("v002", "run_meta 哈希", True))
        a14 = attribute(P, "foo", idx, "2026-10-14", {})
        ck("归属 未快照→~伪版本", a14[0].startswith("~") and not a14[2])
        ck("归属 基线前=v000", attribute(P, "foo", idx, "2026-10-12", {})[0] == "v000")
        # ---- 整 skill 快照: 画像/提示词/数据三类 ----
        W(sd / "workflows" / "chain.md", "step01 模板 改\n")
        W(pd / "fingerprint.md", "fp\n")
        e4 = snapshot(P, "foo", "提示词+数据", now=dt.datetime(2026, 10, 14, 22, 0))
        man = manifest(P, "foo", e4)["files"]
        ck("整 skill 快照: 类别 画像/提示词/数据 + bulk", man["SKILL.md"]["cls"] == CAT_T and man["workflows/chain.md"]["cls"] == CAT_T
           and man["persona/rules.md"]["cls"] == CAT_P and man["persona/fingerprint.md"]["cls"] == CAT_D
           and not man["persona/fingerprint.md"]["bulk"] and man["persona/cases_auto.jsonl"]["bulk"])
        ck("变更按类别记", e4["changed_by_cat"] == {CAT_T: ["workflows/chain.md"], CAT_D: ["persona/fingerprint.md"]}
           and e4["data_changed"] == ["persona/cases_auto.jsonl"])
        ck("diff.patch 含提示词改动", "+step01 模板 改" in R(P.sdir("foo") / e4["id"] / "diff.patch"))
        ck("归属 时刻(10/15 无 run_meta → 08:00 前最新=v004)", attribute(P, "foo", load_index(P, "foo"), "2026-10-15", {})[0] == "v004")
        # ---- 往前滚: 撤回旧格式版 v002(跨格式) ----
        n0 = len(load_index(P, "foo")["versions"])
        r = rollback(P, "foo", bad="v002", reason="旧格式坏规则", evidence="10/13 L1 掉 0.2", sync_fn=sf)
        idx = load_index(P, "foo")
        ck("撤回旧格式版: 规则还原 + 提示词不动 + 新开一版", R(pd / "rules.md") == R0 and R(sd / "SKILL.md") == "skill v1\n"
           and R(sd / "workflows" / "chain.md") == "step01 模板 改\n" and r["status"] == "已撤回"
           and len(idx["versions"]) == n0 + 1 and idx["versions"][-1]["revert_of"] == L2["id"])
        pb = find_version(idx, "v002").get("problem") or {}
        ck("问题版本打标(状态/原因/证据)", pb.get("标记") == "问题版本" and pb.get("status") == "已撤回" and pb.get("evidence") == "10/13 L1 掉 0.2")
        # ---- 往前滚: 无冲突三方合并(问题版之后的蒸馏保留) ----
        W(pd / "rules.md", "# R\nA1 买\n坏规则 X\nA2 卖\nA3 观望\n")
        W(pd / "profile.md", "画像 v2 坏\n")
        W(pd / "language.md", "口头禅\n")
        bad1 = snapshot(P, "foo", "蒸馏(坏)", now=dt.datetime(2026, 10, 20, 22, 0))
        W(pd / "rules.md", "# R\nA1 买\n坏规则 X\nA2 卖\nA3 观望\nA9 好规则 Y\n")
        snapshot(P, "foo", "蒸馏(好)", now=dt.datetime(2026, 10, 21, 22, 0))
        n0 = len(load_index(P, "foo")["versions"])
        r = rollback(P, "foo", bad=bad1["id"], reason="坏规则致 L2 掉", evidence="10/21~22 L2_方向 -0.3", sync_fn=sf)
        idx = load_index(P, "foo")
        ck("三方合并: 撤掉坏规则、保留之后的好规则", R(pd / "rules.md") == "# R\nA1 买\nA2 卖\nA3 观望\nA9 好规则 Y\n")
        ck("问题版之后没再改的文件直接还原 / 问题版新增的文件删除", R(pd / "profile.md") == "画像 v1\n" and not (pd / "language.md").exists())
        ck("无冲突 → 已撤回 + 新版 revert_of + 不删任何版本", r["status"] == "已撤回" and not r["conflicts"] and len(idx["versions"]) == n0 + 1
           and idx["versions"][-1]["revert_of"] == bad1["id"] and all((P.sdir("foo") / e["id"] / "manifest.json").exists() for e in idx["versions"]))
        wd = R(P.sdir("foo") / "withdrawn.md")
        ck("已撤回清单记下被撤规则(且不含保留的)", "- 坏规则 X" in wd and "- 画像 v2 坏" in wd and "- 口头禅" in wd
           and "- L9 旧格式坏规则" in wd and "A9 好规则 Y" not in wd)
        ck("sync 每次真回滚调用一次", synced == [1, 1])
        # ---- 往前滚: 冲突(问题版改的行之后又被改) → 不自动裁决 ----
        W(pd / "rules.md", "# R\nA1 买\nA2 卖出(坏)\nA3 观望\nA9 好规则 Y\n")
        W(sd / "workflows" / "chain.md", "step01 模板 坏\n")
        bad2 = snapshot(P, "foo", "蒸馏(坏2)", now=dt.datetime(2026, 10, 22, 22, 0))
        cur = "# R\nA1 买\nA2 卖出(坏, 又修)\nA3 观望\nA9 好规则 Y\n"
        W(pd / "rules.md", cur)        # 未快照的后续改动: rollback 前必须先被存档
        dr = rollback(P, "foo", bad=bad2["id"], reason="x", dry=True)
        ck("--dry 不动文件且报出冲突", dr["dry"] and R(pd / "rules.md") == cur and R(sd / "workflows" / "chain.md") == "step01 模板 坏\n"
           and [c["file"] for c in dr["conflicts"]] == ["persona/rules.md"])
        n0 = len(load_index(P, "foo")["versions"])
        r = rollback(P, "foo", bad=bad2["id"], reason="A2 改坏", evidence="10/23 L1 -0.4", sync_fn=sf)
        idx = load_index(P, "foo")
        pre = idx["versions"][n0]
        ck("回滚前自动快照保存了未快照的改动", "又修" in get_obj(P, "foo", manifest(P, "foo", pre)["files"]["persona/rules.md"]["sha256"]).decode())
        ck("冲突文件保持当前内容不动", R(pd / "rules.md") == cur)
        ck("同版无冲突文件照撤(提示词 chain.md)", R(sd / "workflows" / "chain.md") == "step01 模板 改\n")
        pb = find_version(idx, bad2["id"])["problem"]
        h = ((pb.get("conflicts") or [{}])[0].get("hunks") or [{}])[0]
        ck("冲突 → 部分撤回·待人工裁决, 冲突块进 index.json", r["status"] == "部分撤回·待人工裁决" and pb["status"] == r["status"]
           and pb["conflicts"][0]["file"] == "persona/rules.md" and "又修" in h.get("当前", "") and h.get("撤回目标") == "A2 卖\n")
        ck("冲突时 新版=回滚前快照+撤回版", len(idx["versions"]) == n0 + 2 and idx["versions"][-1]["revert_status"] == "部分撤回·待人工裁决")
        ck("已撤回清单列出待人工裁决", "待人工裁决" in R(P.sdir("foo") / "withdrawn.md"))
        mark(P, "foo", bad2["id"], "人工改好了", status="已人工裁决")
        pv2 = find_version(load_index(P, "foo"), bad2["id"])
        ck("mark 改状态并保留历史", pv2["problem"]["status"] == "已人工裁决" and len(pv2["problem_history"]) == 1)
        # ---- --full 整体还原(仍是新开一版) ----
        W(pd / "extra.md", "多余\n")
        dr = rollback(P, "foo", to="v004", full=True, reason="x", dry=True)
        ck("--full --dry 不动文件", dr["dry"] and (pd / "extra.md").exists())
        cases_before = R(pd / "cases_auto.jsonl")
        n0 = len(load_index(P, "foo")["versions"])
        r = rollback(P, "foo", to="v004", full=True, reason="整体回 v004", evidence="e", sync_fn=sf)
        idx = load_index(P, "foo")
        ck("--full: 画像+提示词全回 v004, 多余文件删除, bulk 不动", R(pd / "rules.md") == R1 and R(sd / "workflows" / "chain.md") == "step01 模板 改\n"
           and not (pd / "extra.md").exists() and (pd / "fingerprint.md").exists() and R(pd / "cases_auto.jsonl") == cases_before)
        ck("--full: 新版 restore_of + 删掉的文件在回滚前快照里", r["status"] == "已整体还原"
           and idx["versions"][-1]["restore_of"] == find_version(idx, "v004")["id"] and len(idx["versions"]) == n0 + 2
           and "persona/extra.md" in manifest(P, "foo", idx["versions"][n0])["files"])
        ck("--full: 被移除的规则进已撤回清单", "- A9 好规则 Y" in R(P.sdir("foo") / "withdrawn.md"))
        rollback(P, "foo", to="v001", full=True, reason="回旧格式基线", sync_fn=sf)
        ck("--full 到旧格式版: 只还原 persona/, 提示词不删", R(pd / "rules.md") == R0 and (sd / "SKILL.md").exists()
           and (sd / "workflows" / "chain.md").exists() and not (pd / "fingerprint.md").exists())
        # ---- 全局版本流 ----
        for rel, t in zip(GLOBAL_FILES, ("a: 1\n", "X=1\n", "print(1)\n")):
            W(tmp / rel, t)
        g1 = snapshot(P, GLOBAL, "全局基线", now=dt.datetime(2026, 10, 18, 20, 0))
        gm = manifest(P, GLOBAL, g1) if g1 else {"files": {}}
        ck("全局快照 v001: 三个全局件, 类别=全局", bool(g1) and g1["unit"] == "global" and sorted(gm["files"]) == sorted(GLOBAL_FILES)
           and all(m["cls"] == CAT_G for m in gm["files"].values()))
        ck("全局无变化不升版", snapshot(P, GLOBAL, now=dt.datetime(2026, 10, 18, 20, 1)) is None)
        W(tmp / GLOBAL_FILES[2], "print(2)\n")
        g2 = snapshot(P, GLOBAL, "改驱动器", now=dt.datetime(2026, 10, 18, 21, 0))
        ck("全局改驱动器 → v002 + diff", bool(g2) and g2["changed"]["modified"] == [GLOBAL_FILES[2]]
           and "+print(2)" in R(P.sdir(GLOBAL) / g2["id"] / "diff.patch"))
        ck("全局存全文(旧版内容可取回)", get_obj(P, GLOBAL, gm["files"][GLOBAL_FILES[2]]["sha256"]) == b"print(1)\n")
        ck("all_skills 不含 _global", all_skills(P) == ["foo"])
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
        # ---- check 只告警(auto=true + --apply 也不动) ----
        n0, rb = len(load_index(P, "foo")["versions"]), R(pd / "rules.md")
        c = check(P, {"skills": {"foo": mk([("v001", 6, 0.3, True), ("v002", 3, 0.0, True), ("v003", 3, -0.1, True)])}},
                  dict(cfg, auto=True, _src="selftest"), apply=True)
        sg = c["skills"]["foo"].get("suggest") or {}
        ck("check 只告警: 建议回滚但不动文件/不开版本, 给出往前滚命令", c["skills"]["foo"]["level"] == "建议回滚" and sg.get("bad") == "v002"
           and "--bad v002" in (sg.get("cmd") or "") and len(load_index(P, "foo")["versions"]) == n0 and R(pd / "rules.md") == rb
           and "skip" in c["actions"][0] and "建议命令" in check_md(c))
        # ---- prune ----
        for k, t in enumerate(("第A版", "第B版", "第C版")):
            W(pd / "rules.md", f"# R\n{t}\n")
            snapshot(P, "foo", now=dt.datetime(2026, 10, 25 + k, 22, 0))
        va = load_index(P, "foo")["versions"][-3]["id"]
        pr = prune(P, "foo", keep=1)
        idx = load_index(P, "foo")
        pv = {e["id"] for e in idx["versions"] if e.get("pruned")}
        ck("prune 剪掉无人引用的中间版", pr["objects_dropped"] >= 1 and va in pv)
        ck("prune 保留基线/最近/问题版本及其父版", not ({idx["versions"][0]["id"], idx["versions"][-1]["id"], bad1["id"], bad1["parent"],
                                                       bad2["id"], bad2["parent"], L2["id"]} & pv))
        try:
            rollback(P, "foo", to=va, full=True, reason="x", dry=True)
            ck("回滚到已 prune 版本被拒", False)
        except SystemExit:
            ck("回滚到已 prune 版本被拒", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "全部通过" if not fails else f"{len(fails)} 项失败 {fails}")
    return 0 if not fails else 1


# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description="导师 skill 全目录版本化 + 全局件版本流 + 每版评估 + 往前滚式回滚(零 token)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("snapshot")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--skill", help=f"skill 名(不带 -skill); {GLOBAL} = 全局件")
    g.add_argument("--all", action="store_true", help="全部 skill + 全局件")
    g.add_argument("--global", dest="glob", action="store_true", help="只存全局件")
    a.add_argument("--why", default="manual")
    a = sub.add_parser("log")
    a.add_argument("--skill", required=True, help=f"skill 名; {GLOBAL} = 全局件")
    for name in ("metrics", "check"):
        a = sub.add_parser(name)
        a.add_argument("--since", default=START)
        a.add_argument("--until")
        if name == "check":
            a.add_argument("--apply", action="store_true", help="10/18 起失效(check 只告警), 保留只为兼容旧调用")
    a = sub.add_parser("rollback", help="往前滚: 默认撤回 --bad 版带进来的改动; --full --to 整体还原; 都开新版不删历史")
    a.add_argument("--skill", required=True)
    a.add_argument("--bad", help="问题版本 vXXX(默认模式必填; --full 时可选, 用于打标)")
    a.add_argument("--to", help="--full 的目标版本 vYYY")
    a.add_argument("--full", action="store_true", help="整体还原到 --to(仍新开一版)")
    a.add_argument("--reason", required=True, help="为什么判它是问题版本")
    a.add_argument("--evidence", default="", help="证据(哪几天、哪层拟人度/收益掉了)")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--include-data", action="store_true", help="连 *.jsonl 等整份重算的数据一起撤/还原(默认不动)")
    a.add_argument("--keep-extra", action="store_true", help="--full 时不删目标版里没有的文件")
    a.add_argument("--no-sync", action="store_true")
    a = sub.add_parser("mark", help="只给版本打「问题版本」标 / 改状态(不动文件)")
    a.add_argument("--skill", required=True)
    a.add_argument("--v", required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--evidence", default="")
    a.add_argument("--status", default="问题版本(未处理)")
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
        sk = (all_skills(P) + [GLOBAL]) if args.all else [GLOBAL] if args.glob else [args.skill]
        n_new = 0
        with vlock(P):
            for s in sk:
                if s != GLOBAL and not P.skill_dir(s).is_dir():
                    print(f"{s}: 无 skills/{s}-skill/ 跳过")
                    continue
                e = snapshot(P, s, args.why)
                if e:
                    n_new += 1
                    ch = e["changed"]
                    cats = " ".join(f"{k}{len(v)}" for k, v in e["changed_by_cat"].items())
                    print(f"{s}: 新版 {e['id']} 改{len(ch['modified'])}/增{len(ch['added'])}/删{len(ch['removed'])} 文件"
                          + (f"(新纳入 {len(ch['newly_tracked'])})" if ch.get("newly_tracked") else "") + (f" [{cats}]" if cats else "")
                          + f" +{e['lines']['added']}/-{e['lines']['removed']} 行 生效 {e['effective_from']}")
                else:
                    print(f"{s}: 无变化")
        print(f"JSON:{json.dumps({'units': len(sk), 'new_versions': n_new}, ensure_ascii=False)}")
    elif args.cmd == "log":
        idx = load_index(P, args.skill)
        for e in idx["versions"]:
            ch = e["changed"]
            tags = []
            if e.get("unit") is None:
                tags.append("旧格式·仅persona")
            if ch.get("newly_tracked"):
                tags.append(f"新纳入{len(ch['newly_tracked'])}")
            if e.get("revert_of"):
                tags.append(f"撤回 {e['revert_of'].split('_')[0]}" + (f"·{e['revert_status']}" if e.get("revert_status") else ""))
            if e.get("restore_of") or e.get("rollback_of"):
                tags.append(f"整体还原→{(e.get('restore_of') or e.get('rollback_of')).split('_')[0]}")
            if e.get("problem"):
                tags.append(f"问题版本:{e['problem']['status']}({e['problem'].get('reason', '')})")
            if e.get("pruned"):
                tags.append("已prune")
            print(f"{e['id']}  生效 {e['effective_from']}  改{ch['modified']} 增{ch['added']} 删{ch['removed']}  "
                  f"+{e['lines']['added']}/-{e['lines']['removed']}  {e['why']}" + (f"  [{'; '.join(tags)}]" if tags else ""))
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
                    sg = j.get("suggest") or {}
                    print(f"!! {s}: {j['level']}; {'; '.join(j['note'])}" + (f"\n   建议: {sg['cmd']}" if sg.get("cmd") else f" ({sg.get('note', '')})"))
            print(f"check → {od / ('check_' + res['until'] + '.md')}")
            print(f"JSON:{json.dumps({'levels': cnt, 'alert_only': True, 'actions': 0}, ensure_ascii=False)}")
    elif args.cmd == "rollback":
        kw = dict(bad=args.bad, to=args.to, reason=args.reason, evidence=args.evidence, full=args.full,
                  include_data=args.include_data, keep_extra=args.keep_extra)
        if args.dry:
            r = rollback(P, args.skill, dry=True, **kw)
        else:
            with vlock(P):
                r = rollback(P, args.skill, sync=not args.no_sync, **kw)
        for act, rel in r["actions"]:
            print(f"  {'(dry) ' if r.get('dry') else ''}{act}: {rel}")
        for c in r.get("conflicts") or []:
            print(f"  !! 冲突(待人工裁决, 当前文件未动): {c['file']}")
            for h in c["hunks"]:
                print(f"     @{h.get('问题版本行')} {h.get('说明', '')}")
                for k in ("问题版本", "当前", "撤回目标"):
                    if k in h:
                        print(f"       [{k}] " + h[k].rstrip("\n").replace("\n", "\n       " + " " * (len(k) + 3)))
        if r.get("persona_changed"):
            print("  提示: 画像文件变了 → 重跑索引生成器(gen_rules_index.mjs / gen_profile_index.py)后再 snapshot, 否则 *_index.md 仍是旧的")
        print(f"JSON:{json.dumps({k: v for k, v in r.items() if k not in ('actions', 'conflicts')} | {'conflicts': len(r.get('conflicts') or [])}, ensure_ascii=False)}")
    elif args.cmd == "mark":
        with vlock(P):
            vid = mark(P, args.skill, args.v, args.reason, args.evidence, args.status)
        print(f"{args.skill}: {vid} 标记 问题版本 status={args.status}")
    elif args.cmd == "prune":
        with vlock(P):
            for s in ((all_skills(P) + [GLOBAL]) if args.all else [args.skill]):
                if P.sdir(s).is_dir():
                    r = prune(P, s, args.keep, args.dry)
                    print(f"{s}: {'(dry) ' if args.dry else ''}删对象 {r['objects_dropped']} 个 / {r['bytes_freed'] / 1e6:.2f} MB")
    elif args.cmd == "export":
        idx = load_index(P, args.skill)
        e = find_version(idx, args.v) or sys.exit(f"没有版本 {args.v}")
        out = Path(args.out).resolve()
        if out in (P.base(args.skill).resolve(), P.persona(args.skill).resolve(), P.root.resolve()):
            sys.exit("export 不能写 skill 目录/仓库根本身(那是 rollback 的事, 回滚要先存快照)")
        acts = restore_into(P, args.skill, e, out)
        print(f"export {e['id']} → {out}({len(acts)} 个文件)")


if __name__ == "__main__":
    main()
