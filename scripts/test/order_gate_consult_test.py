# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live" / "v2"))
from mentor_consult import validate_orders  # noqa: E402


def pack():
    return {"code": "600785", "at": "2026-11-01T09:30:00",
            "account": {"cash": 10000, "positions": {"600785": {"qty": 100, "sellable": 100, "cost": 11.5}}},
            "knowledge": {"context": {"instrument": {"day": {"preClose": 12.59}}}}}


class OrderGateTest(unittest.TestCase):
    def test_valid_order_and_missing_book_warning(self):
        d = validate_orders(pack(), {"orders": [{"side": "BUY", "price": 11.82, "qty": 100}]})
        self.assertEqual(d["order_gate"]["accepted"], 1)
        self.assertTrue(any("G5" in x for x in d["order_gate"]["warnings"]))

    def test_t1_sellable_is_enforced(self):
        d = validate_orders(pack(), {"orders": [{"side": "SELL", "price": 11.82, "qty": 200}]})
        self.assertEqual(d["orders"], [])
        self.assertIn("G1", d["order_gate"]["rejected"][0]["errors"][0])

    def test_no_account_cannot_execute(self):
        p = dict(pack(), account=None)
        d = validate_orders(p, {"orders": [{"side": "BUY", "price": 11.82, "qty": 100}]})
        self.assertEqual(d["orders"], [])


if __name__ == "__main__":
    unittest.main()
