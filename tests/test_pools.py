"""trader.pools: the daily swing and long-term job, end to end over two days with fakes."""
import tempfile
import unittest
from datetime import datetime

from core import journal, storage
from trader import pools


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def uptrend(n=260, start=400.0):
    return [{"ts": f"2026-{1 + i // 28 % 12:02d}-{1 + i % 28:02d}T00:00:00+05:30", "open": start + i * 0.5,
             "high": start + i * 0.5 + 3, "low": start + i * 0.5 - 3, "close": start + i * 0.5 + (2 if i % 2 else -2),
             "volume": 10 ** 6} for i in range(n)]


class FakeUx:
    def __init__(self):
        self.q = {"NSE_EQ|ABC": {"open": 530.0, "close": 532.0}, "NSE_EQ|XYZ": {"open": 300.0, "close": 301.0}}
        self.hols = []

    def instruments(self):
        return {"eq": {"ABC": {"key": "NSE_EQ|ABC", "isin": "INEABC"}, "XYZ": {"key": "NSE_EQ|XYZ", "isin": "INEXYZ"}},
                "index": {}}

    def holidays(self):
        return self.hols

    def quotes(self, keys):
        return {k: {"instrument_token": k, "last_price": self.q[k]["close"], "ohlc": {"open": self.q[k]["open"]},
                    "net_change": 0.0, "depth": {}} for k in keys if k in self.q}

    def historical_candles(self, key, unit, interval, start, end):
        return uptrend()

    def fundamentals(self, isin, kind, **params):
        return [{"name": "P/E", "company_value": "20", "sector_value": "30"},
                {"name": "ROCE", "company_value": "25%", "sector_value": "15%"},
                {"name": "ROE", "company_value": "20%", "sector_value": "15%"}]

    def news(self, keys):
        return {}


class FakeTg:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, reply_to=None, now_ist=None):
        self.sent.append(text)
        return len(self.sent)


class PoolsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = storage.Local(self.dir)
        self.ux, self.tg = FakeUx(), FakeTg()
        self.clock = Clock(datetime(2026, 12, 14, 15, 50))  # Monday
        self.plans, self.councils = [], []
        self.final = {"buys": [{"symbol": "ABC", "stop": 500.0, "target": 600.0, "why": "trend"}], "sells": [],
                      "stops": [], "notes": "kept the buy"}

    def job(self, pool="swing"):
        return pools.DeliveryPool(pool, store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                                  decide_fn=lambda pool, ctx: self.plans.append(ctx) or {"buys": [], "sells": [],
                                                                                         "stops": [], "notes": "-"},
                                  council_fn=lambda pool, ctx, plan: self.councils.append(plan) or
                                  {"final": self.final, "members": {}, "reviews": []},
                                  charges=lambda key, qty, pool, side, price: 20.0,
                                  members={"ABC": {"industry": "IT"}, "XYZ": {"industry": "Auto"}})

    def events(self, day, name):
        return [e for e in journal.read(day, base_dir=self.dir) if e["event"] == name]

    def test_decision_today_fill_at_next_open(self):
        out = self.job().run_day()
        self.assertEqual(out["pending"], [{"side": "BUY", "symbol": "ABC", "qty": 28, "stop": 500.0, "target": 600.0,
                                           "why": "trend"}])  # 25% of ₹60,000 at ₹532 = 28 shares
        self.assertIn("ABC", self.plans[0]["candidates"][0]["symbol"])
        self.assertIn("📈 Swing", self.tg.sent[-1])
        self.clock.t = datetime(2026, 12, 15, 15, 50)
        self.final = {"buys": [], "sells": [], "stops": [], "notes": "-"}
        self.job().run_day()
        st = storage.get_json("state/swing.json", store=self.store)
        self.assertEqual(st["positions"]["ABC"]["fill_price"], pools.ledger.slip(530.0, "BUY"))  # today's open + slippage
        self.assertEqual(self.events("2026-12-15", "fill")[0]["pool"], "swing")

    def test_stop_fires_on_the_close(self):
        self.job().run_day()
        self.clock.t = datetime(2026, 12, 15, 15, 50)
        self.final = {"buys": [], "sells": [], "stops": [], "notes": "-"}
        self.job().run_day()
        self.ux.q["NSE_EQ|ABC"] = {"open": 505.0, "close": 498.0}  # closes under the ₹500 stop
        self.clock.t = datetime(2026, 12, 16, 15, 50)
        self.job().run_day()
        ex = self.events("2026-12-16", "exit")[0]
        self.assertEqual((ex["reason"], ex["price"]), ("stop", 497.75))

    def test_stops_tighten_never_widen_and_sells_fill_next_open(self):
        self.job().run_day()
        self.clock.t = datetime(2026, 12, 15, 15, 50)
        self.final = {"buys": [], "sells": [], "stops": [{"symbol": "ABC", "new_stop": 490.0, "why": "room"}],
                      "notes": "-"}
        out = self.job().run_day()
        self.assertIn("never widen", " ".join(out["notes"]))
        self.final = {"buys": [], "sells": [{"symbol": "ABC", "why": "trend broke"}], "stops": [], "notes": "-"}
        self.clock.t = datetime(2026, 12, 16, 15, 50)
        self.job().run_day()
        self.clock.t = datetime(2026, 12, 17, 15, 50)
        self.final = {"buys": [], "sells": [], "stops": [], "notes": "-"}
        self.job().run_day()
        self.assertEqual(self.events("2026-12-17", "exit")[0]["reason"], "ai_sell")

    def test_gate_blocks_a_bad_buy(self):
        self.final = {"buys": [{"symbol": "ABC", "stop": 540.0, "target": 600.0, "why": "-"}], "sells": [], "stops": [],
                      "notes": "-"}  # stop above the price
        out = self.job().run_day()
        self.assertEqual(out["pending"], [])
        self.assertTrue(any("ABC" in n for n in out["notes"]))

    def test_weekend_swing_does_nothing_long_term_reviews_on_saturday(self):
        self.clock.t = datetime(2026, 12, 19, 10, 15)  # Saturday
        self.assertEqual(self.job("swing").run_day(), {"skipped": "weekend"})
        out = self.job("long_term").run_day()
        self.assertEqual(len(self.plans), 1)
        self.assertEqual(out["pending"][0]["symbol"], "ABC")  # filled at Monday's open

    def test_long_term_weekday_without_news_makes_no_decision(self):
        self.job("long_term").run_day()
        self.assertEqual(self.plans, [])

    def test_holiday(self):
        self.ux.hols = [{"date": "2026-12-14", "holiday_type": "TRADING_HOLIDAY", "closed_exchanges": ["NSE"],
                         "description": "Festival"}]
        self.assertEqual(self.job().run_day(), {"skipped": "Festival"})


if __name__ == "__main__":
    unittest.main()
