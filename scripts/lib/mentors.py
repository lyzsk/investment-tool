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
    # accounts.mjs 字面名单(过渡期仍写死, check_md_daily.py 按文本解析它)须与登记表逐项一致
    import re
    txt = (_T.parent / "dfcf" / "paper" / "accounts.mjs").read_text(encoding="utf-8")
    seg = txt[txt.index("ACCOUNTS"):txt.index("];")]
    acc = [(s, n, k) for s, n, k in re.findall(r'\["(A-[\w-]+)",\s*"([^"]+)",\s*"([^"]+)"\]', seg) if k != "混合"]
    want = [(e["book"], e["display"], {"tzzb": "导师"}.get(e["type"], e["type"])) for e in E]
    assert acc == want, f"accounts.mjs 与登记表不一致:\n{acc}\n{want}"
    print(f"mentors selftest OK: {len(E)} 条链 (UP {len(ids('UP'))} / tzzb {len(ids('tzzb'))} / 对照 {len(ids('对照'))}); accounts.mjs 一致")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        for e in all():
            print(e["type"], e["id"], e["book"], e["display"], e.get("cluster") or "-", e["online"], sep="\t")
