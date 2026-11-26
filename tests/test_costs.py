"""core.costs: charges come only from Upstox; when Upstox can't answer, the answer is None (never a guess)."""
import unittest
from unittest import mock

from core import costs, upstox


class CostsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        patcher = mock.patch.object(upstox, "charges", side_effect=self._charges)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fail_with = None

    def _charges(self, key, qty, product, side, price):
        self.calls.append((key, qty, product, side, price))
        if self.fail_with:
            raise self.fail_with
        return {"total": 7.76 if side == "BUY" else 9.5}

    def test_order_charges_is_upstox_total(self):
        self.assertEqual(costs.order("NSE_EQ|K", 10, "intraday", "BUY", 1000.0), 7.76)
        self.assertEqual(self.calls, [("NSE_EQ|K", 10, "I", "BUY", 1000.0)])

    def test_round_trip_prices_both_orders(self):
        total = costs.round_trip("NSE_EQ|K", 10, "swing", "BUY", 1000.0, 1100.0)
        self.assertEqual(total, 17.26)
        self.assertEqual(self.calls, [("NSE_EQ|K", 10, "D", "BUY", 1000.0), ("NSE_EQ|K", 10, "D", "SELL", 1100.0)])

    def test_short_round_trip_sells_first(self):
        costs.round_trip("NSE_EQ|K", 10, "intraday", "SELL", 1000.0, 990.0)
        self.assertEqual([c[3] for c in self.calls], ["SELL", "BUY"])

    def test_upstox_down_gives_none(self):
        for err in (upstox.UpstoxError("x"), RuntimeError("GET failed after 3 attempts")):
            self.fail_with = err
            self.assertIsNone(costs.order("NSE_EQ|K", 10, "intraday", "BUY", 1000.0))
            self.assertIsNone(costs.round_trip("NSE_EQ|K", 10, "intraday", "BUY", 1000.0, 1010.0))


if __name__ == "__main__":
    unittest.main()
