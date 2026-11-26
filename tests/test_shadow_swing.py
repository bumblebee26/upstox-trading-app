"""shadows.swing: the swing catalog on made-up daily bars (sane orders, caps, exits, weekly rebalances)."""
import random
import unittest

from shadows import portfolio as pf
from shadows import swing


def walk(seed, n=320, drift=0.0008):
    rnd, p, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = p
        p = max(5.0, p * (1 + drift + rnd.gauss(0, 0.018)))
        out.append({"ts": f"d{i:03d}", "open": o, "high": max(o, p) * (1 + abs(rnd.gauss(0, 0.006))),
                    "low": min(o, p) * (1 - abs(rnd.gauss(0, 0.006))), "close": p,
                    "volume": int(10 ** 6 * (1 + abs(rnd.gauss(0, 0.8))))})
    return out


def charge(key, qty, pool, side, price):
    return 20.0


class SwingTest(unittest.TestCase):
    def test_every_strategy_runs_sane_over_60_days(self):
        stocks = {f"S{i}": walk(i, drift=0.002 if i % 2 else -0.001) for i in range(12)}
        nifty = walk(99)
        industries = {s: ("IT" if i < 6 else "Auto") for i, s in enumerate(stocks)}
        keys = {s: s for s in stocks}
        for sid, spec in swing.STRATEGIES.items():
            led = pf.new(60_000)
            for t in range(260, 320):
                hist = {s: d[:t + 1] for s, d in stocks.items()}
                swing.step(sid, led, f"d{t:03d}", hist, keys, charge, nifty=nifty[:t + 1], industries=industries,
                           news=set(), week=t // 5)
                self.assertLessEqual(len(led["holdings"]), swing.MAX_HOLD, sid)
                self.assertGreaterEqual(led["cash"], 0, sid)
                for sym, h in led["holdings"].items():
                    self.assertLess(h["stop"], h["entry"] * 1.5, sid)
            self.assertEqual(len(led["equity"]), 60, sid)

    def test_donchian_buys_the_breakout_and_sells_the_10_day_low(self):
        flat = [{"ts": f"d{i}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10 ** 6} for i in range(260)]
        up = flat + [{"ts": "d260", "open": 100, "high": 103, "low": 100, "close": 102.5, "volume": 10 ** 6}]
        led, keys = pf.new(60_000), {"A": "A"}
        swing.step("S03", led, "d260", {"A": up}, keys, charge)
        self.assertEqual(led["pending"][0]["symbol"], "A")
        nxt = up + [{"ts": "d261", "open": 102.6, "high": 103, "low": 102, "close": 102.8, "volume": 10 ** 6}]
        swing.step("S03", led, "d261", {"A": nxt}, keys, charge)
        self.assertIn("A", led["holdings"])
        down = nxt + [{"ts": "d262", "open": 100, "high": 100, "low": 97, "close": 98.0, "volume": 10 ** 6}]
        swing.step("S03", led, "d262", {"A": down}, keys, charge)
        self.assertIn(led["closed"][-1]["reason"], ("stop", "exit_rule"))  # the 10-day low is also its stop

    def test_days_held_count_once_a_day(self):
        flat = [{"ts": f"d{i}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10 ** 6} for i in range(260)]
        up = flat + [{"ts": "d260", "open": 100, "high": 103, "low": 100, "close": 102.5, "volume": 10 ** 6}]
        led, keys = pf.new(60_000), {"A": "A"}
        swing.step("S03", led, "d260", {"A": up}, keys, charge)
        hold = up + [{"ts": f"d{261 + i}", "open": 102.6, "high": 103, "low": 102, "close": 102.8,
                      "volume": 10 ** 6} for i in range(3)]
        for t in range(3):
            swing.step("S03", led, f"d{261 + t}", {"A": hold[:262 + t]}, keys, charge)
        self.assertEqual(led["holdings"]["A"]["bars"], 3)

    def test_catalog(self):
        self.assertEqual(len(swing.STRATEGIES), 31)  # 28 + S12, S13, S24 (NSE data, PR 9d)
        self.assertIn("S05-CH", swing.STRATEGIES)


def dated(closes, opens=None, lows=None):
    out = []
    for i, c in enumerate(closes):
        o = (opens or {}).get(i, c)
        out.append({"ts": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}T00:00:00+05:30", "open": o, "high": max(o, c) + 1,
                    "low": (lows or {}).get(i, min(o, c) - 1), "close": c, "volume": 10 ** 6})
    return out


class NseShadowTest(unittest.TestCase):
    def test_s12_gap_up_after_results_that_holds(self):
        d = dated([100.0] * 39 + [105.0], opens={39: 104.0}, lows={39: 103.5})
        today, before = d[-1]["ts"][:10], d[-2]["ts"][:10]
        self.assertEqual(swing.s12(d, {"results_days": {before}})[1:], (103.5, None))   # results the evening before
        self.assertIsNotNone(swing.s12(d, {"results_days": {today}}))
        self.assertIsNone(swing.s12(d, {"results_days": set()}))
        fades = dated([100.0] * 39 + [103.0], opens={39: 104.0})                         # closed under its open
        self.assertIsNone(swing.s12(fades, {"results_days": {before}}))

    def test_s13_delivery_above_its_average_three_days_with_rising_closes(self):
        d = dated([100.0] * 36 + [101.0, 102.0, 103.0, 103.0])
        days = [b["ts"][:10] for b in d]
        deliv = {x: 40.0 for x in days[-24:-4]} | {x: 60.0 for x in days[-4:-1]}
        self.assertIsNotNone(swing.s13(d, {"deliv": deliv}))
        self.assertIsNone(swing.s13(d, {"deliv": deliv | {days[-2]: 39.0}}))           # one day under the average
        flat = dated([100.0] * 40)
        self.assertIsNone(swing.s13(flat, {"deliv": {b["ts"][:10]: v for b, v in zip(flat, [40.0] * 36 + [60.0] * 4)}}))
        self.assertIsNone(swing.s13(d, {}))                                               # no files yet

    def test_s24_big_buy_with_two_closes_above_the_deal_price(self):
        d = dated([100.0] * 37 + [100.0, 101.0, 102.0])
        deal_day = d[-3]["ts"][:10]
        buy = {"day": deal_day, "price": 100.5, "value": 6e7}
        self.assertEqual(swing.s24(d, {"buys": [buy]})[1:], (100.5, None))
        self.assertIsNone(swing.s24(d, {"buys": [dict(buy, value=4e7)]}))               # under ₹5 crore
        self.assertIsNone(swing.s24(d, {"buys": [dict(buy, price=101.5)]}))             # a close under the price

    def test_catalog_has_them(self):
        for sid in ("S12", "S13", "S24"):
            self.assertEqual(swing.STRATEGIES[sid]["kind"], "nse")


class UniverseTest(unittest.TestCase):
    def test_a_holding_that_leaves_the_universe_still_exits(self):
        d = walk(5, n=260)
        led = pf.new(60_000)
        led["holdings"]["OLD"] = {"qty": 10, "entry": 100.0, "charges": 20.0, "day": "d000", "stop": 10 ** 6,
                                  "high_close": 100.0, "high_high": 100.0}
        swing.step("S03", led, "d259", {"OLD": d}, {"OLD": "K"}, charge, universe={})
        self.assertNotIn("OLD", led["holdings"])  # its stop is checked although it is no longer liquid
        self.assertEqual(led["closed"][0]["reason"], "stop")


if __name__ == "__main__":
    unittest.main()
