# -*- coding: utf-8 -*-
"""知识底座 v1 的真实数据自举与样例输出；不写业务库，不调用模型。"""
import argparse
import json
from pathlib import Path
import sys
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import ForecastAdapter, KlineAdapter, MarketAdapter, TzzbAdapter, UPAdapter, UserAdapter, read_status
from context_pack import get_context_pack
from store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CODES = ["600785", "111024", "113698"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--cycle", default="", help="仅作先验备注；正式周期阶段由行情机械生成")
    ap.add_argument("--db", default=str(ROOT / "downloads" / "ontology" / "ontology.db"))
    ap.add_argument("--codes", default=",".join(DEFAULT_CODES))
    ap.add_argument("--out", default=str(ROOT / "results" / "knowledge"))
    ap.add_argument("--status-file", default=str(ROOT / "results" / "kline" / "2026-10-30" / "_status.json"))
    a = ap.parse_args()
    codes = [x.strip() for x in a.codes.split(",") if x.strip()]
    store = KnowledgeStore(a.db)
    status_path = Path(a.status_file)
    code = "import json;print(json.dumps(json.load(open(r'" + str(status_path) + "',encoding='utf-8')),ensure_ascii=False))"
    status = json.loads(subprocess.check_output([sys.executable, "-X", "utf8", "-I", "-c", code], text=True, encoding="utf-8"))
    counts = {"market": MarketAdapter(store).ingest_day(a.date, a.cycle, codes),
              "tzzb": TzzbAdapter(store).ingest_day(a.date, codes),
              "kline": KlineAdapter(store).ingest_day(a.date, status=status),
              "forecast": ForecastAdapter(store).ingest_day(a.date, codes),
              "user": UserAdapter(store).ingest_day(a.date),
              "up": UPAdapter(store).ingest_day(a.date)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for code in codes:
        pack = get_context_pack(store, code, f"{a.date}T23:59:59", purpose="viewer", budget="full")
        (out / f"{code}_context_pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"PACK {code} cases={len(pack['cases'])} forecast_n={pack['forecast']['n']} → {out / (code + '_context_pack.json')}")
    print("COUNTS", counts)
    store.close()


if __name__ == "__main__":
    main()
