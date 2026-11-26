"""shadows.portfolio: a daily-bar paper ledger (fills at the next open, exits on the close, Upstox charges)."""
import unittest

from shadows import portfolio as pf


def bar(o, c, h=None, l=None):
    return {"open": o, "high": h or max(o, c), "low": l or min(o, c), "close": c, "volume": 10 ** 6}


def charge(key, qty, pool, side, price):
    return 20.0 if side == "BUY" else 43.6  # sells carry the DP charge


class PortfolioTest(unittest.TestCase):
    def setUp(self):
        self.p = pf.new(60_000)
        self.keys = {"ABC": "K1", "XYZ": "K2"}

    def step(self, day, bars):
        return pf.fill_and_value(self.p, day, bars, self.keys, charge, "swing")

    def test_buy_fills_at_next_open_with_slippage_and_charges(self):
        pf.order_buy(self.p, "ABC", amount=15_000, stop=90.0)
        self.step("2026-12-15", {"ABC": bar(100.0, 102.0)})
        h = self.p["holdings"]["ABC"]
        self.assertEqual(h["entry"], 100.05)
        self.assertEqual(h["qty"], 149)  # ₹15,000 / ₹100.05
        self.assertAlmostEqual(self.p["cash"], 60_000 - 149 * 100.05 - 20.0, places=2)
        self.assertAlmostEqual(self.p["equity"][-1][1], self.p["cash"] + 149 * 102.0, places=2)

    def test_exit_on_the_close_records_the_trade(self):
        pf.order_buy(self.p, "ABC", amount=15_000, stop=90.0)
        self.step("2026-12-15", {"ABC": bar(100.0, 102.0)})
        pf.exit_on_close(self.p, "ABC", 95.0, "2026-12-16", "stop", self.keys, charge, "swing")
        t = self.p["closed"][-1]
        self.assertEqual((t["symbol"], t["reason"], t["exit"]), ("ABC", "stop", 94.95))
        self.assertAlmostEqual(t["net_rs"], round((94.95 - 100.05) * 149 - 20.0 - 43.6, 2), places=2)
        self.assertNotIn("ABC", self.p["holdings"])

    def test_top_up_adds_to_a_holding_at_the_average_price(self):
        pf.order_buy(self.p, "ABC", amount=10_000, stop=0.0)
        self.step("d1", {"ABC": bar(100, 100)})
        pf.order_buy(self.p, "ABC", amount=10_000, stop=0.0, top_up=True)
        self.step("d2", {"ABC": bar(200, 200)})
        h = self.p["holdings"]["ABC"]
        self.assertEqual(h["qty"], 99 + 49)
        self.assertAlmostEqual(h["entry"], (99 * 100.05 + 49 * 200.1) / 148, places=2)
        self.assertEqual((h["charges"], h["day"]), (40.0, "d1"))

    def test_buy_never_spends_more_than_the_cash(self):
        pf.order_buy(self.p, "ABC", amount=100_000, stop=90.0)
        self.step("2026-12-15", {"ABC": bar(100.0, 100.0)})
        self.assertGreaterEqual(self.p["cash"], 0)

    def test_no_price_today_drops_the_order(self):
        pf.order_buy(self.p, "ABC", amount=15_000, stop=90.0)
        self.step("2026-12-15", {})
        self.assertEqual((self.p["holdings"], self.p["pending"]), ({}, []))

    def test_rebalance_sells_the_old_and_buys_the_new_at_the_next_open(self):
        pf.order_buy(self.p, "ABC", amount=15_000, stop=0.0)
        self.step("2026-12-15", {"ABC": bar(100.0, 100.0)})
        pf.rebalance(self.p, ["XYZ"], weight=0.10, closes={"ABC": 100.0, "XYZ": 50.0})
        self.step("2026-12-16", {"ABC": bar(101.0, 101.0), "XYZ": bar(50.0, 51.0)})
        self.assertEqual(set(self.p["holdings"]), {"XYZ"})
        self.assertEqual(self.p["closed"][-1]["reason"], "rebalance")

    def test_buy_and_hold_and_monthly_sip(self):
        b = pf.new(100_000)
        pf.order_buy(b, "NIFTYBEES", amount=100_000, stop=0.0)
        pf.fill_and_value(b, "2026-12-15", {"NIFTYBEES": bar(280.0, 281.0)}, {"NIFTYBEES": "N"}, charge, "long_term")
        self.assertEqual(b["holdings"]["NIFTYBEES"]["qty"], 356)
        sip = pf.new(100_000)
        self.assertEqual(pf.sip_amount(sip, months=12), round(100_000 / 12, 2))


if __name__ == "__main__":
    unittest.main()
