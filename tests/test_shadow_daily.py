"""shadows.daily: swing, long-term and NIFTYBEES ledgers day by day, monthly fundamentals, families file."""
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta

from core import storage
from shadows import daily
from shadows import swing
from shadows import longterm as lt
from tests.test_shadow_long import company

SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def series(seed, start=date(2025, 9, 1), end=date(2027, 2, 1)):
    rnd, p, out, d = random.Random(seed), 500.0, {}, start
    while d <= end:
        if d.weekday() < 5:
            o, p = p, p * (1 + 0.001 + rnd.gauss(0, 0.012))
            out[d.isoformat()] = {"ts": f"{d.isoformat()}T00:00:00+05:30", "open": o, "high": max(o, p) * 1.004,
                                  "low": min(o, p) * 0.996, "close": p, "volume": 2 * 10 ** 6}
        d += timedelta(days=1)
    return out


class FakeUx:
    def __init__(self):
        self.prices = {f"NSE_EQ|{s}": series(i) for i, s in enumerate(SYMBOLS + ["NIFTYBEES"])}
        self.prices["NSE_INDEX|Nifty 50"] = series(99)
        self.fund_calls = 0

    def instruments(self):
        eq = {s: {"key": f"NSE_EQ|{s}", "isin": f"IN{s}"} for s in SYMBOLS + ["NIFTYBEES"]}
        return {"eq": eq, "index": {"Nifty 50": "NSE_INDEX|Nifty 50"}}

    def holidays(self):
        return []

    def historical_candles(self, key, unit, interval, start, end):
        return [b for d, b in sorted(self.prices[key].items()) if start.isoformat() <= d <= end.isoformat()]

    def quotes(self, keys):
        today = self.today.isoformat()
        out = {}
        for k in keys:
            b = self.prices[k][today]
            out[k] = {"last_price": b["close"], "volume": b["volume"],
                      "ohlc": {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}}
        return out

    def news(self, keys):
        return {}

    def fundamentals(self, isin, kind, **params):
        self.fund_calls += 1
        c = company(pe=str(10 + len(isin)))
        return {"key-ratios": c["ratios"], "income-statement": c["income"], "cash-flow": c["cashflow"],
                "share-holdings": c["holdings"], "corporate-actions": c["actions"]}[kind]


class FakeTg:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, reply_to=None, now_ist=None):
        self.sent.append(text)


class DailyTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ux, self.tg = storage.Local(tempfile.mkdtemp()), FakeUx(), FakeTg()
        self.members = {s: {"industry": "IT" if i < 3 else "Auto", "isin": f"IN{s}"} for i, s in enumerate(SYMBOLS)}

    def day(self, d):
        self.ux.today = d
        return daily.run_day(now=datetime(d.year, d.month, d.day, 16, 20), store=self.store, ux=self.ux, tg=self.tg,
                             members=self.members, charges=lambda key, qty, pool, side, price: 20.0,
                             index_list=lambda name, store=None: {s: {} for s in SYMBOLS[:4]})

    def ledgers(self):
        return storage.get_json(daily.LEDGERS, store=self.store)["ledgers"]

    def test_a_month_of_shadows(self):
        self.day(date(2026, 12, 1))
        led = self.ledgers()
        self.assertEqual(set(led), set(swing.STRATEGIES) | set(lt.STRATEGIES) | set(daily.BENCHMARKS))
        self.assertEqual(self.ux.fund_calls, 5 * len(SYMBOLS))
        self.assertTrue(led["L04"]["pending"])            # first run: the long-term shadows buy
        self.assertEqual(led["L16"]["pending"][0]["symbol"], "AAA")
        self.assertEqual(led["B01-swing"]["capital"], 60_000)
        self.assertEqual(led["B01-long"]["capital"], 100_000)

        self.assertIn("skipped", self.day(date(2026, 12, 1)))  # a second run the same day changes nothing

        d = date(2026, 12, 2)
        while d < date(2027, 1, 1):
            if d.weekday() < 5:
                self.day(d)
            d += timedelta(days=1)
        self.assertEqual(self.ux.fund_calls, 5 * len(SYMBOLS))  # fundamentals once a month
        led = self.ledgers()
        self.assertTrue(led["L04"]["holdings"])
        self.assertLessEqual(len(led["L04"]["holdings"]), 4)     # at most 2 per industry, 2 industries
        b01, b02 = led["B01-long"]["holdings"]["NIFTYBEES"], led["B02-long"]["holdings"]["NIFTYBEES"]
        self.assertGreater(b01["qty"] * b01["entry"], 95_000)  # all in on day 1
        sip = b02["qty"]
        self.day(date(2027, 1, 1))
        self.day(date(2027, 1, 4))
        self.assertGreater(self.ledgers()["B02-long"]["holdings"]["NIFTYBEES"]["qty"], sip)  # January instalment
        self.assertEqual(self.ux.fund_calls, 10 * len(SYMBOLS))

        fam = storage.get_json(daily.FAMILIES, store=self.store)
        names = {r["variant"]: r for r in fam["rows"]}
        self.assertEqual(names["B01-long"]["status"], "benchmark")
        self.assertEqual(names["S03"]["family"], "swing")
        self.assertIn("Swing and long-term shadows", self.tg.sent[-1])

    def test_outages_leave_the_long_term_shadows_untouched(self):
        def down(*a, **k):
            raise RuntimeError("Upstox down")

        def no_list(name, store=None):
            raise RuntimeError("NSE refused")

        self.ux.fundamentals = down
        self.ux.today = date(2026, 12, 1)
        daily.run_day(now=datetime(2026, 12, 1, 16, 20), store=self.store, ux=self.ux, tg=self.tg,
                      members=self.members, charges=lambda *a: 20.0, index_list=no_list)
        led = self.ledgers()
        self.assertNotIn("month", led["L04"])   # no data: no rebalance, tried again tomorrow
        self.assertNotIn("month", led["L16"])
        self.assertIsNone(storage.get_json("shadows/fundamentals/2026-12/AAA.json", store=self.store))  # not cached
        self.assertTrue(led["S03"]["equity"])   # the rest of the day still ran

    def test_nse_context_from_the_saved_files(self):
        storage.put_json("nse/2026-11-26/bhav.json", {"AAA": {"close": 1.0, "volume": 1, "deliv_qty": 1, "deliv_pct": 55.0},
                                                      "ZZZ": {"deliv_pct": 10.0}}, store=self.store)
        storage.put_json("nse/2026-11-26/bulk.json", [{"day": "2026-11-26", "symbol": "AAA", "side": "BUY", "qty": 100000,
                                                       "price": 600.0, "client": "F"},
                                                      {"day": "2026-11-26", "symbol": "AAA", "side": "SELL", "qty": 9,
                                                       "price": 600.0, "client": "G"}], store=self.store)
        storage.put_json("nse/2026-11-25/calendar.json", [{"symbol": "BBB", "purpose": "Financial Results",
                                                           "day": "2026-11-28"},
                                                          {"symbol": "BBB", "purpose": "Dividend", "day": "2026-11-29"}],
                         store=self.store)
        ctx = daily.nse_context(self.store, date(2026, 11, 27), {"AAA", "BBB"})
        self.assertEqual(ctx["AAA"]["deliv"], {"2026-11-26": 55.0})
        self.assertEqual(ctx["AAA"]["buys"], [{"day": "2026-11-26", "price": 600.0, "value": 6e7}])
        self.assertEqual(ctx["BBB"]["results_days"], {"2026-11-28"})
        self.assertNotIn("ZZZ", ctx)

    def test_intraday_results_join_the_families(self):
        storage.put_json("shadows/intraday/2026-12-01.json",
                         {"variants": {"E01-X1": {"trades": [{"net_rs": 50.0}, {"net_rs": -20.0}], "net_rs": 30.0}}},
                         store=self.store)
        self.day(date(2026, 12, 1))
        rows = {r["variant"]: r for r in storage.get_json(daily.FAMILIES, store=self.store)["rows"]}
        self.assertEqual((rows["E01-X1"]["trades"], rows["E01-X1"]["net_rs"]), (2, 30.0))


if __name__ == "__main__":
    unittest.main()
