# -*- coding: utf-8 -*-
"""persona_asof.py — as-of 回放用的"当日盘前画像"还原(10/17 晚, 审计 #4 头号风险: 回放读到未来画像; 零 token, 只读 git / skills_versions)

问题: as-of 回放 D 日时, 链读的是 skills/<skill>-skill/persona/ 的当前文件——里面已蒸馏进 D 日及以后导师的真实操作和结果
      (实证: 10/16 沙盒读的刘忆青 rules.md 改于 10/17 00:07, 已写着 10/16 14:56 跌停价清百洋) → 拟人度和收益虚高。
做法: 把 D 日 09:15 之前最后一版画像还原到 <沙盒>/persona/<skill>/, 驱动器 as-of 模式见到该目录就整条链改读它(run_chain.persona_dir)。
版本来源(取两者中时间更晚、但早于 D 09:15 的那份):
  ① git: 最后一个改动过 skills/<skill>-skill/persona 且提交时间 < D 09:15 的提交(用户几乎每天 08:10 前后提交一次; 只读 git log / git show)
  ② skills_versions: persona_versions 快照, ts < D 09:15(10/16 22:49 起才有; 10/18 起快照是整个 skill 目录, 旧版只有 persona/, 两种都认)
  只拷画像文本(画像 + 机器生成但链会读的 fingerprint/*_index 等); cases_auto.jsonl 这类每晚整份重算的 bulk 数据不拷(里面同样有未来样本),
  链读不到就按无该文件处理
10/18 起(全 skill 版本化): 提示词 workflows/chain.md 也按 D 09:15 锁——单独选源(git 上最后改过 chain.md 且 < D 09:15 的提交 vs
  < D 09:15 的最新整 skill 快照, 取更晚的), 写到 <out>/_workflows/chain.md 并记进 _asof.json 的 chain_md 字段;
  找不到 D 前版本 → chain_md.source=null(驱动器照旧读当前 chain.md)。驱动器怎么读它由 run_chain.py 决定(本脚本只负责还原)。
都找不到(该导师 D 日还没有画像) → 返回 None, 调用方决定跳过该链或报错, 绝不退回当前画像
用法: python persona_asof.py --skill liuyiqing --date 2026-10-16 --out <目录>   |   --selftest
"""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CUT_HM = "09:15"   # D 日开盘集合竞价开始; 此前提交的画像不可能含 D 日交易信息
CHAIN_REL = "workflows/chain.md"
CHAIN_OUT = "_workflows/chain.md"   # 写在沙盒画像目录下(与 _asof.json 同为下划线前缀, 不与画像文件重名)


def _git(*args, root=ROOT):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, creationflags=NOWIN)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.stdout


def git_candidate(skill, cut, root=ROOT, sub="persona"):
    """(提交时间, 提交号) 或 None; sub=skill 目录内的子路径(persona / workflows/chain.md)"""
    out = _git("log", "-1", f"--before={cut}", "--format=%H %cI", "--", f"skills/{skill}-skill/{sub}", root=root).decode().strip()
    if not out:
        return None
    h, t = out.split(" ", 1)
    return datetime.fromisoformat(t).replace(tzinfo=None), h


def snap_candidate(skill, cut, root=ROOT):
    """(快照时间, 版本 id) 或 None"""
    f = root / "skills_versions" / skill / "index.json"
    if not f.exists():
        return None
    best = None
    for v in json.loads(f.read_text(encoding="utf-8")).get("versions", []):
        ts = datetime.fromisoformat(v["ts"])
        if ts < cut and (best is None or ts > best[0]):
            best = (ts, v["id"])
    return best


def snap_files(root, skill, vid):
    """快照 manifest → [(skill 目录内相对路径, meta)]; 旧格式(无 unit, 键=persona 内相对路径)补 persona/ 前缀"""
    man = json.loads((root / "skills_versions" / skill / vid / "manifest.json").read_text(encoding="utf-8"))
    fs = man["files"]
    items = fs.items() if isinstance(fs, dict) else ((x.get("name") or x.get("path"), x) for x in fs)
    legacy = not man.get("unit")
    return [(("persona/" + str(n)) if legacy else str(n), m) for n, m in items]


def _obj(root, skill, sha):
    return gzip.decompress((root / "skills_versions" / skill / "objects" / f"{sha}.gz").read_bytes())


def _is_bulk(rel, meta):
    return bool(meta.get("bulk")) or meta.get("cls") == "data" or rel.endswith(".jsonl") or "case_log/" in rel


def chain_candidate(skill, cut, root=ROOT, use_git=True):
    """D 09:15 前最后一版 chain.md → (时间, 来源 dict, bytes) 或 None"""
    cands = []
    s = snap_candidate(skill, cut, root)
    if s:
        hit = [m for r, m in snap_files(root, skill, s[1]) if r == CHAIN_REL]
        if hit:
            cands.append((s[0], {"source": "skills_versions", "version": s[1]}, lambda m=hit[0]: _obj(root, skill, m["sha256"])))
    if use_git:
        g = git_candidate(skill, cut, root, CHAIN_REL)
        if g:
            cands.append((g[0], {"source": "git", "commit": g[1][:12]},
                          lambda h=g[1]: _git("show", f"{h}:skills/{skill}-skill/{CHAIN_REL}", root=root)))
    if not cands:
        return None
    t, src, get = max(cands, key=lambda x: x[0])
    return t, src, get()


def materialize(skill, date, out, root=ROOT, use_git=True):
    """还原到 out(先清空); 返回来源说明 dict, 找不到返回 None"""
    root = Path(root)
    cut = datetime.strptime(f"{date} {CUT_HM}", "%Y-%m-%d %H:%M")
    g = git_candidate(skill, cut, root) if use_git else None
    s = snap_candidate(skill, cut, root)
    if not g and not s:
        return None
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pre = f"skills/{skill}-skill/persona/"
    if s and (not g or s[0] > g[0]):
        n = 0
        for rel, meta in snap_files(root, skill, s[1]):
            if not rel.startswith("persona/") or _is_bulk(rel, meta):
                continue
            dst = out / rel[len("persona/"):]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_obj(root, skill, meta["sha256"]))
            n += 1
        src = {"source": "skills_versions", "version": s[1], "time": s[0].isoformat(), "files": n}
    else:
        names = [x for x in _git("ls-tree", "-r", "--name-only", g[1], "--", pre, root=root).decode("utf-8").splitlines()
                 if x and not x.endswith(".jsonl")]
        for name in names:
            dst = out / name[len(pre):]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_git("show", f"{g[1]}:{name}", root=root))
        src = {"source": "git", "commit": g[1][:12], "time": g[0].isoformat(), "files": len(names)}
    c = chain_candidate(skill, cut, root, use_git)
    if c:
        dst = out / CHAIN_OUT
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(c[2])
        src["chain_md"] = dict(c[1], time=c[0].isoformat(), path=CHAIN_OUT, sha12=hashlib.sha256(c[2]).hexdigest()[:12])
    else:
        src["chain_md"] = {"source": None, "note": f"{date} {CUT_HM} 前没有 chain.md 版本, 驱动器读当前 chain.md"}
    src.update(skill=skill, date=date, cut=cut.isoformat(), made_at=datetime.now().isoformat(timespec="seconds"))
    (out / "_asof.json").write_text(json.dumps(src, ensure_ascii=False, indent=1), encoding="utf-8")
    return src


def _selftest_offline(td):
    """临时仓库(无 git): 用 persona_versions 造 旧格式版 + 整 skill 版, 验证两种 manifest 都能还原、chain.md 按时刻锁"""
    sys.path.insert(0, str(ROOT / "scripts" / "skills_ver"))
    import persona_versions as PV   # noqa: PLC0415
    root = Path(td) / "repo"
    P = PV.Paths(root, root / "skills_versions")
    sd, pd = P.skill_dir("foo"), P.persona("foo")
    for p, t in ((sd / "SKILL.md", "s\n"), (sd / CHAIN_REL, "chain 旧\n"), (pd / "rules.md", "R 旧\n"), (pd / "cases_auto.jsonl", "{}\n")):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8", newline="\n")
    PV._legacy_snapshot(P, "foo", datetime(2026, 10, 15, 22, 0))           # 旧格式: 只有 persona, 没有 chain.md
    (sd / CHAIN_REL).write_text("chain 新\n", encoding="utf-8", newline="\n")
    (pd / "rules.md").write_text("R 新\n", encoding="utf-8", newline="\n")
    (pd / "fingerprint.md").write_text("fp\n", encoding="utf-8", newline="\n")
    PV.snapshot(P, "foo", "整 skill", now=datetime(2026, 10, 16, 22, 0))
    r1 = materialize("foo", "2026-10-16", Path(td) / "o1", root=root, use_git=False)
    assert r1 and r1["version"].startswith("v001") and (Path(td) / "o1" / "rules.md").read_text(encoding="utf-8") == "R 旧\n", r1
    assert r1["chain_md"]["source"] is None and not (Path(td) / "o1" / CHAIN_OUT).exists(), "旧格式版无 chain.md, 不得写出"
    assert not list((Path(td) / "o1").glob("*.jsonl")), "bulk 数据不该拷"
    r2 = materialize("foo", "2026-10-17", Path(td) / "o2", root=root, use_git=False)
    assert r2 and r2["version"].startswith("v002") and (Path(td) / "o2" / "rules.md").read_text(encoding="utf-8") == "R 新\n", r2
    assert (Path(td) / "o2" / "fingerprint.md").exists() and not (Path(td) / "o2" / "SKILL.md").exists(), "只拷 persona(含生成数据), 不拷提示词到画像目录"
    assert (Path(td) / "o2" / CHAIN_OUT).read_text(encoding="utf-8") == "chain 新\n" and r2["chain_md"]["source"] == "skills_versions", r2
    assert json.loads((Path(td) / "o2" / "_asof.json").read_text(encoding="utf-8"))["chain_md"]["path"] == CHAIN_OUT


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _selftest_offline(td)
        print("PERSONA_ASOF OFFLINE(新旧 manifest + chain.md 锁) PASS")
        r = materialize("liuyiqing", "2026-10-16", Path(td) / "p")
        assert r and r["source"] == "git" and r["commit"].startswith("72534c9"), r   # 10/16 08:11 那次提交; 快照 10/16 22:49 起才有, 不得选
        rules = (Path(td) / "p" / "rules.md").read_text(encoding="utf-8")
        assert "14:56:09" not in rules, "还原出的画像仍含 10/16 收盘后才知道的操作"
        assert not list((Path(td) / "p").glob("*.jsonl")), "数据文件不该拷"
        cm = r.get("chain_md") or {}
        assert cm.get("source") == "git" and cm.get("time", "") < "2026-10-16T09:15" and (Path(td) / "p" / CHAIN_OUT).exists(), cm
        want = _git("show", f"{_git('log', '-1', '--before=2026-10-16 09:15:00', '--format=%H', '--', 'skills/liuyiqing-skill/' + CHAIN_REL).decode().strip()}"
                            f":skills/liuyiqing-skill/{CHAIN_REL}")
        assert (Path(td) / "p" / CHAIN_OUT).read_bytes() == want, "chain.md 不是 D 09:15 前最后一版"
        r2 = materialize("liuyiqing", "2026-10-19", Path(td) / "q")   # 10/19 盘前: 应取 10/17 之后最新一份(快照或提交)
        assert r2 and r2["time"] > "2026-10-17", r2
        assert (r2.get("chain_md") or {}).get("source"), r2
        assert materialize("no_such_mentor", "2026-10-16", Path(td) / "x") is None
    print("PERSONA_ASOF SELFTEST PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--date")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    r = materialize(a.skill, a.date, a.out)
    print(json.dumps(r, ensure_ascii=False) if r else f"{a.skill} 在 {a.date} {CUT_HM} 前没有任何画像版本")
    return 0 if r else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
