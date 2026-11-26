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
        self.assertEqual(len(swing.STRATEGIES), 28)
        self.assertIn("S05-CH", swing.STRATEGIES)


if __name__ == "__main__":
    unittest.main()
