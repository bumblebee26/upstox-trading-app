"""core.indicators on hand-checkable series."""
import unittest

from core import indicators as ind


def c(o, h, l, cl, v=1000, ts="2026-12-14T09:15:00+05:30"):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": cl, "volume": v}


def minutes(n, start=100.0, step=0.0, vol=1000):
    """n one-minute candles from 09:15, each moving `step` from the last close."""
    out, price = [], start
    for i in range(n):
        h, m = divmod(15 + i, 60)
        ts = f"2026-12-14T{9 + h:02d}:{m:02d}:00+05:30"
        out.append(c(price, price + abs(step) + 0.5, price - 0.5, price + step, vol, ts))
        price += step
    return out


class AveragesTest(unittest.TestCase):
    def test_ema_seeds_with_simple_average(self):
        self.assertEqual(ind.ema([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_of_constant_is_constant(self):
        self.assertAlmostEqual(ind.ema([7.0] * 30, 9)[-1], 7.0)

    def test_too_short_gives_none(self):
        self.assertEqual(ind.ema([1, 2], 3), [None, None])
        self.assertIsNone(ind.rsi([1, 2], 14))


class OscillatorTest(unittest.TestCase):
    def test_rsi_extremes_and_balance(self):
        self.assertEqual(ind.rsi(list(range(1, 40)), 14), 100.0)
        self.assertEqual(ind.rsi(list(range(40, 1, -1)), 14), 0.0)
        self.assertAlmostEqual(ind.rsi([1, 2] * 20, 14), 50.0, delta=4)

    def test_macd_of_constant_is_zero(self):
        m = ind.macd([50.0] * 60)
        self.assertEqual((m["macd"], m["signal"], m["hist"]), (0.0, 0.0, 0.0))

    def test_macd_rising_is_positive(self):
        self.assertGreater(ind.macd([float(i) for i in range(60)])["macd"], 0)

    def test_bollinger_width_zero_on_flat(self):
        b = ind.bollinger([10.0] * 25)
        self.assertEqual((b["mid"], b["upper"], b["lower"], b["width_pct"]), (10.0, 10.0, 10.0, 0.0))


class RangeTest(unittest.TestCase):
    def test_atr_of_constant_range(self):
        self.assertEqual(ind.atr([c(10, 12, 9, 10)] * 20, 14), 3.0)

    def test_adx_strong_uptrend(self):
        candles = [c(100 + i, 101.5 + i, 99.5 + i, 101 + i) for i in range(40)]
        a = ind.adx(candles, 14)
        self.assertGreater(a["adx"], 40)
        self.assertGreater(a["plus_di"], a["minus_di"])

    def test_supertrend_direction(self):
        up = [c(100 + i, 101 + i, 99 + i, 100.8 + i) for i in range(30)]
        down = [c(200 - i, 201 - i, 199 - i, 199.2 - i) for i in range(30)]
        self.assertEqual(ind.supertrend(up)["direction"], "up")
        self.assertEqual(ind.supertrend(down)["direction"], "down")


class IntradayTest(unittest.TestCase):
    def test_vwap_weights_by_volume(self):
        candles = [c(10, 10, 10, 10, 100), c(20, 20, 20, 20, 300)]
        v = ind.vwap(candles)
        self.assertEqual(v["vwap"], 17.5)
        self.assertGreater(v["upper1"], 17.5)

    def test_resample_1m_to_5m(self):
        five = ind.resample(minutes(10, step=1.0), 5)
        self.assertEqual(len(five), 2)
        self.assertEqual((five[0]["open"], five[0]["close"], five[0]["volume"]), (100.0, 105.0, 5000))
        self.assertEqual(five[1]["ts"][11:16], "09:20")

    def test_opening_range(self):
        r = ind.opening_range(minutes(30, step=1.0), 15)
        self.assertEqual((r["low"], r["high"]), (99.5, 115.5))
        r60 = ind.opening_range(minutes(90, step=1.0), 60)  # crosses 10:00
        self.assertEqual(r60["high"], 160.5)

    def test_relative_volume(self):
        self.assertEqual(ind.relative_volume(3000, [1000, 1000, 2000]), 2.25)
        self.assertIsNone(ind.relative_volume(3000, []))


class LevelsTest(unittest.TestCase):
    def test_classic_pivots(self):
        p = ind.pivots(high=110, low=90, close=100)
        self.assertEqual((p["pp"], p["r1"], p["s1"], p["r2"], p["s2"]), (100.0, 110.0, 90.0, 120.0, 80.0))

    def test_camarilla(self):
        p = ind.camarilla(high=110, low=90, close=100)
        self.assertEqual((p["h3"], p["l3"]), (105.5, 94.5))

    def test_round_numbers_scale_with_price(self):
        self.assertEqual(ind.round_levels(712.4), [700, 750])
        self.assertEqual(ind.round_levels(2463), [2400, 2500])
        self.assertEqual(ind.round_levels(88.3), [85, 90])

    def test_value_area_and_point_of_control(self):
        candles = minutes(10, start=100.0, vol=100)
        candles[4] = c(103, 103.2, 102.8, 103, 10_000, candles[4]["ts"])
        va = ind.value_area(candles)
        self.assertEqual(va["poc"], 103.0)
        self.assertLessEqual(va["val"], 103.0)
        self.assertGreaterEqual(va["vah"], 103.0)

    def test_52_week_range(self):
        daily = [c(100, 100 + i % 7, 90 - i % 5, 100) for i in range(300)]
        r = ind.range_52w(daily)
        self.assertEqual((r["high"], r["low"]), (106, 86))


if __name__ == "__main__":
    unittest.main()
