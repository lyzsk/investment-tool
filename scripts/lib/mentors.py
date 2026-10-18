# -*- coding: utf-8 -*-
"""mentors.py — 导师登记表读取口(10/17 二B-4: 全体链名单唯一真源; mjs 同口径 = mentors.mjs)
登记表 = scripts/tzzb/tzzb_ledgers.json(tzzb 账本条目, id=ledger) + scripts/tzzb/mentor_registry_extra.json(B站 UP/对照组)
只有带 book 字段的条目算"链"(负样本 kind=neg 无 book, 不进名单)。顺序 = UP(附表序) → tzzb(账本文件序) → 对照 = accounts.mjs 槽位序
字段: id, type(UP/tzzb/对照), name(md 小节名), display(显示名), book(paper 账本), short(短描述=facts 导师速览节标题), cluster(风格簇), circle(能力圈一句话), online(上线日)
用法: import mentors as M; M.ids("tzzb"); M.book("buchitudou0") → "A-cb"; M.by_book("A-cb") → "buchitudou0"; 自测 python mentors.py --selftest
"""
import json
from pathlib import Path

_T = Path(__file__).resolve().parents[1] / "tzzb"
_ORDER = {"UP": 0, "tzzb": 1, "对照": 2}


def all():   # noqa: A001  全部链条目(dict, 含 id), 按槽位序
    ex = json.loads((_T / "mentor_registry_extra.json").read_text(encoding="utf-8"))["entries"]
    tz = [dict(e, id=e["ledger"]) for e in json.loads((_T / "tzzb_ledgers.json").read_text(encoding="utf-8")) if e.get("book")]
    return sorted(ex + tz, key=lambda e: _ORDER[e["type"]])   # sorted 稳定: 同类保留文件内顺序


def ids(*types):
    return [e["id"] for e in all() if not types or e["type"] in types]


def excluded():
    """10/18 用户定: 退出 paper 的导师(scripts/tzzb/paper_excluded.json) → 只保留零 token 的机械维护(抓数 / 日志卡 / 名片 / 指纹 / 挖掘),
    花 token 的(每日【推测】层 / 蒸馏 / 加厚 / 日卡解读)一律跳过。{id: 原因}"""
    try:
        return json.loads((_T / "paper_excluded.json").read_text(encoding="utf-8")).get("excluded") or {}
    except (OSError, ValueError):
        return {}


def active_ids(*types):
    """ids() 去掉退出 paper 的导师 = 花 token 的步骤用这个名单"""
    ex = excluded()
    return [i for i in ids(*types) if i not in ex]


def get(mid):
    return next(e for e in all() if e["id"] == mid)


def book(mid):
    return get(mid)["book"]


def by_book(bk):
    return next(e["id"] for e in all() if e["book"] == bk)


def head(mid):   # facts「导师信号速览」节标题关键词 = short 括号前部分
    return get(mid)["short"].split("(")[0]


def _selftest():
    E = all()
    seen = [e["id"] for e in E]
    assert len(seen) == len(set(seen)), "id 重复"
    assert len({e["book"] for e in E}) == len(E), "book 重复"
    for e in E:
        for k in ("id", "type", "name", "display", "book", "short", "circle", "online"):
            assert e.get(k), (e["id"], k)
        assert e["type"] in _ORDER and "cluster" in e, e["id"]
        assert by_book(e["book"]) == e["id"]
    assert ids("UP") == ["taoge", "qushitiange", "lubenyuan"] and ids("对照") == ["control"]
    assert book("buchitudou0") == "A-cb" and head("lianghuaxiaohao") == "量化实验"
    # 10/17 二期: accounts.mjs 已改为由登记表生成, 用 node 求值核对(混合账本除外)
    import subprocess
    r = subprocess.run(["node", "--input-type=module", "-e",
                        "import {ACCOUNTS} from './scripts/dfcf/paper/accounts.mjs'; console.log(JSON.stringify(ACCOUNTS))"],
                       cwd=str(_T.parents[1]), capture_output=True, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    acc = [tuple(x) for x in json.loads(r.stdout) if x[2] not in ("混合", "做T")]   # 10/18: 做T 两本也不是导师链
    want = [(e["book"], e["display"], {"tzzb": "导师"}.get(e["type"], e["type"])) for e in E]
    assert acc == want, f"accounts.mjs 与登记表不一致: {acc} vs {want}"
    print(f"mentors selftest OK: {len(E)} 条链 (UP {len(ids('UP'))} / tzzb {len(ids('tzzb'))} / 对照 {len(ids('对照'))}); accounts.mjs 一致")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        for e in all():
            print(e["type"], e["id"], e["book"], e["display"], e.get("cluster") or "-", e["online"], sep="\t")
