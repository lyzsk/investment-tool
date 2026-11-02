# -*- coding: utf-8 -*-
"""周一live v2盘前预检：机械链/数据/推送dry，不启动自动模型。"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "live"), str(ROOT / "scripts" / "knowledge"), str(ROOT / "scripts" / "chain"), str(ROOT / "scripts" / "live" / "v2")]
import signals as SG  # noqa: E402
import chain_steps as CS  # noqa: E402
from store import KnowledgeStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-02")
    a = ap.parse_args()
    checks = {}

    def put(name, fn):
        try:
            value = fn()
            checks[name] = {"ok": bool(value), "detail": value}
        except Exception as e:  # 预检必须大声失败
            checks[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    put("watch_seed_next_day", lambda: (ROOT / "results" / "_live" / a.date / "watch_seed.json").exists())
    put("book_snapshot_previous", lambda: any((ROOT / "downloads" / "market" / "2026-10-30").glob("book_snap.jsonl*")))
    put("signal_selftest", lambda: subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "live" / "signals_selftest.py")],
                                                   capture_output=True, timeout=120).returncode == 0)
    put("hot_cb_mapping", lambda: "111024" in SG.hot_cb_codes("2026-10-30"))
    put("live_model_disabled", lambda: SG._flag("LIVE_V2_MODEL", "0") == "0")

    def facts01():
        state = {"cash": 0, "positions": {}, "trades": []}
        strategy = {"codes": [{"code": "600785", "rules": []}]}
        text, _, _, _ = CS.build_01("buchitudou0", a.date, "09:00:00", "盘前预检", state, strategy, [], {}, "", "预检", None, live=False)
        return "01 事实" in text and "600785" in text
    put("facts01_increment", facts01)
    put("push_dry", lambda: SG.push_test("2026-10-30") is not False)
    put("viewer_user_trades", lambda: "DATA" in (ROOT / "docs" / "private" / "replay_viewer.html").read_text(encoding="utf-8"))
    out = ROOT / "results" / "_live" / a.date / "preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"date": a.date, "ok": all(x["ok"] for x in checks.values()), "checks": checks}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
