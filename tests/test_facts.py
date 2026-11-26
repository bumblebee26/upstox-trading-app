"""trader.facts: one compact block per stock, built from candles and a quote (no network)."""
import json
import unittest

from trader import facts


def minute_candles(n, start=500.0, step=0.1, vol=2000, day="2026-12-14"):
    out, p = [], start
    for i in range(n):
        h, m = divmod(15 + i, 60)
        out.append({"ts": f"{day}T{9 + h:02d}:{m:02d}:00+05:30", "open": p, "high": p + 0.3, "low": p - 0.2,
                    "close": p + step, "volume": vol})
        p += step
    return out


def daily_candles(n, start=400.0, end_day=13):
    out = []
    for i in range(n):
        p = start + i * 0.4
        out.append({"ts": f"2026-{1 + i // 28 % 12:02d}-{1 + i % 28:02d}T00:00:00+05:30", "open": p,
                    "high": p + 5, "low": p - 5, "close": p + 1, "volume": 10 ** 6})
    out[-1]["ts"] = f"2026-12-{end_day:02d}T00:00:00+05:30"
    return out


QUOTE = {"last_price": 515.0, "upper_circuit_limit": 566.5, "lower_circuit_limit": 463.5, "average_price": 512.0,
         "total_buy_quantity": 60000, "total_sell_quantity": 40000,
         "depth": {"buy": [{"price": 514.9, "quantity": 100}], "sell": [{"price": 515.1, "quantity": 80}]}}


class PacketTest(unittest.TestCase):
    def setUp(self):
        self.p = facts.packet("ABC", minute_candles(150), daily_candles(300), QUOTE,
                              nifty_1m=minute_candles(150, start=24000, step=1.0),
                              sector_1m=minute_candles(150, start=50000, step=-2.0),
                              same_time_volumes=[150_000, 150_000])

    def test_has_every_section(self):
        self.assertEqual(set(self.p), {"symbol", "time", "price", "day", "tf", "levels", "quote", "market"})
        self.assertEqual(set(self.p["tf"]), {"5m", "15m", "daily"})
        for tf in self.p["tf"].values():
            self.assertTrue({"ema20", "rsi14", "atr", "adx", "macd", "supertrend", "candles", "chart"} <= set(tf))

    def test_quote_spread_and_circuit_room(self):
        q = self.p["quote"]
        self.assertEqual((q["bid"], q["ask"]), (514.9, 515.1))
        self.assertAlmostEqual(q["spread_pct"], 0.04, places=2)
        self.assertAlmostEqual(q["to_upper_circuit_pct"], 10.0, places=1)
        self.assertEqual(q["buy_sell_ratio"], 1.5)

    def test_market_context(self):
        m = self.p["market"]
        self.assertGreater(m["nifty_since_open_pct"], 0)
        self.assertLess(m["sector_since_open_pct"], 0)
        self.assertGreater(m["vs_sector_pct"], 0)

    def test_previous_day_levels_and_relative_volume(self):
        self.assertEqual(self.p["levels"]["prev_day"]["close"], daily_candles(300)[-1]["close"])
        self.assertEqual(self.p["day"]["rvol"], 2.0)  # 300,000 so far vs 150,000 on usual days

    def test_is_small_enough_to_send(self):
        self.assertLess(len(json.dumps(self.p)), 4000)

    def test_before_the_open_uses_the_quote(self):
        p = facts.packet("ABC", [], daily_candles(300), QUOTE)
        self.assertEqual(p["price"], 515.0)
        self.assertIsNone(p["day"]["vwap"])


if __name__ == "__main__":
    unittest.main()
