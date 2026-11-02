# -*- coding: utf-8 -*-
"""本地派生知识存储；只写 downloads/ontology/ontology.db，不触碰业务库。"""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_manifest(
 source_id TEXT PRIMARY KEY, type TEXT, uri TEXT, sha1 TEXT, source_time TEXT,
 ingest_time TEXT, parser_version TEXT, quality_status TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS context_snapshot(
 context_id TEXT PRIMARY KEY, subject TEXT, as_of TEXT, available_at TEXT,
 market TEXT, theme TEXT, instrument TEXT, dimensions TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS case_record(
 case_id TEXT PRIMARY KEY, subject TEXT, context_id TEXT, issued_at TEXT, available_at TEXT,
 target_start TEXT, target_end TEXT, hypothesis TEXT, action TEXT, outcome TEXT,
 label TEXT, confidence TEXT, epistemic TEXT, review_state TEXT, source_id TEXT
);
CREATE TABLE IF NOT EXISTS rule(
 id TEXT, owner TEXT, version INTEGER, context_id TEXT, trigger TEXT, action TEXT,
 evidence TEXT, relations TEXT, confidence TEXT, epistemic TEXT, review TEXT,
 PRIMARY KEY(id, owner, version)
);
CREATE TABLE IF NOT EXISTS belief_state(
 id TEXT PRIMARY KEY, as_of TEXT, state TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS knowledge_link(src TEXT, rel TEXT, dst TEXT, meta TEXT);
"""
JSON_COLS = {
    "source_manifest": set(),
    "context_snapshot": {"market", "theme", "instrument", "dimensions", "evidence"},
    "case_record": {"action", "outcome", "confidence", "epistemic"},
    "rule": {"trigger", "action", "evidence", "relations", "confidence", "epistemic", "review"},
    "belief_state": {"state", "evidence"},
}


class KnowledgeStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("pragma table_info(case_record)")}
        if "case_record_id" in cols and "case_id" not in cols:
            self.db.execute("alter table case_record rename column case_record_id to case_id")
            self.db.commit()
        for table, col in (("context_snapshot", "dimensions"), ("case_record", "epistemic"), ("rule", "epistemic"), ("knowledge_link", "meta")):
            names = {x[1] for x in self.db.execute(f"pragma table_info({table})")}
            if col not in names:
                self.db.execute(f"alter table {table} add column {col} TEXT")
        self.db.commit()
        # 旧知识默认候选，不伪造 n/命中率；旧 active 规则同时降为候选，防止迁移后继续被 04/06 引用
        for cid, available, source in self.db.execute("select case_id,available_at,source_id from case_record where epistemic is null").fetchall():
            e = {"status": "candidate", "n": 0, "hit_rate": None, "source": "migration", "as_of": available, "evidence": [source]}
            self.db.execute("update case_record set epistemic=? where case_id=?", (json.dumps(e, ensure_ascii=False), cid))
        for rid, owner, version, review in self.db.execute("select id,owner,version,review from rule where epistemic is null").fetchall():
            e = {"status": "candidate", "n": 0, "hit_rate": None, "source": "migration", "as_of": "", "evidence": []}
            rv = json.loads(review or "{}")
            if rv.get("state") == "active":
                rv["state"] = "candidate"
            self.db.execute("update rule set epistemic=?,review=? where id=? and owner=? and version=?",
                            (json.dumps(e, ensure_ascii=False), json.dumps(rv, ensure_ascii=False), rid, owner, version))
        self.db.commit()

    def close(self):
        self.db.close()

    def link(self, src, rel, dst, meta=None):
        encoded = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        self.db.execute("insert into knowledge_link(src,rel,dst,meta) select ?,?,?,? where not exists(select 1 from knowledge_link where src=? and rel=? and dst=?)",
                        (src, rel, dst, encoded, src, rel, dst))
        self.db.commit()

    def links(self, src=None, dst=None):
        q, p = "select src,rel,dst,meta from knowledge_link", []
        if src is not None:
            q += " where src=?"
            p.append(src)
        elif dst is not None:
            q += " where dst=?"
            p.append(dst)
        return [{"src": a, "rel": b, "dst": c, "meta": json.loads(m) if m else None} for a, b, c, m in self.db.execute(q, p)]

    @staticmethod
    def _encode(table, rec):
        out = dict(rec)
        for k in JSON_COLS.get(table, set()):
            if k in out:
                out[k] = json.dumps(out[k], ensure_ascii=False)
        return out

    @staticmethod
    def _decode(table, rec):
        out = dict(rec)
        for k in JSON_COLS.get(table, set()):
            if k in out and isinstance(out[k], str):
                out[k] = json.loads(out[k])
        return out

    def upsert(self, table, rec, key):
        assert table in JSON_COLS, table
        rec = self._encode(table, rec)
        cols = list(rec)
        placeholders = ",".join("?" for _ in cols)
        keys = [x.strip() for x in key.split(",")]
        updates = ",".join(f"{k}=excluded.{k}" for k in cols if k not in keys)
        self.db.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({placeholders}) ON CONFLICT({key}) DO UPDATE SET {updates}", [rec[k] for k in cols])
        self.db.commit()

    def get(self, table, key, value):
        assert table in JSON_COLS, table
        r = self.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        if not r:
            return None
        cols = [x[1] for x in self.db.execute(f"PRAGMA table_info({table})").fetchall()]
        return self._decode(table, dict(zip(cols, r)))

    def all(self, table):
        assert table in JSON_COLS, table
        cols = [x[1] for x in self.db.execute(f"PRAGMA table_info({table})").fetchall()]
        return [self._decode(table, dict(zip(cols, r))) for r in self.db.execute(f"SELECT * FROM {table}").fetchall()]

    def latest(self, table, time_col, at):
        assert table in JSON_COLS, table
        cols = [x[1] for x in self.db.execute(f"PRAGMA table_info({table})").fetchall()]
        r = self.db.execute(f"SELECT * FROM {table} WHERE {time_col}<=? ORDER BY {time_col} DESC LIMIT 1", (at,)).fetchone()
        return self._decode(table, dict(zip(cols, r))) if r else None
