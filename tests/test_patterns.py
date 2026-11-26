"""core.patterns: candle and simple chart patterns on made-up candles."""
import unittest

from core import patterns as pat


def c(o, h, l, cl):
    return {"open": o, "high": h, "low": l, "close": cl, "volume": 1000}


DOWN = [c(110, 111, 105, 106), c(106, 107, 101, 102), c(102, 103, 97, 98)]
UP = [c(90, 95, 89, 94), c(94, 99, 93, 98), c(98, 103, 97, 102)]


class CandleTest(unittest.TestCase):
    def found(self, candles):
        return set(pat.candles(candles))

    def test_bullish_and_bearish_engulfing(self):
        self.assertIn("bullish_engulfing", self.found(DOWN + [c(97, 104, 96.5, 103.5)]))
        self.assertIn("bearish_engulfing", self.found(UP + [c(103, 103.5, 96, 96.5)]))

    def test_hammer_after_a_fall_and_shooting_star_after_a_rise(self):
        self.assertIn("hammer", self.found(DOWN + [c(97.5, 98.2, 93, 98)]))
        self.assertIn("shooting_star", self.found(UP + [c(102.5, 107.5, 102.2, 102.4)]))

    def test_doji_and_marubozu(self):
        self.assertIn("doji", self.found(UP + [c(102, 104, 100, 102.05)]))
        self.assertIn("bullish_marubozu", self.found(DOWN + [c(98, 104, 98, 104)]))

    def test_harami(self):
        self.assertIn("bullish_harami", self.found(DOWN[:2] + [c(103, 103.5, 96, 96.5), c(98, 99.5, 97.5, 99)]))

    def test_morning_and_evening_star(self):
        self.assertIn("morning_star", self.found(DOWN[:2] + [c(103, 103.5, 96, 96.5), c(96, 96.6, 95.4, 96.2),
                                                             c(96.5, 102, 96.4, 101.5)]))
        self.assertIn("evening_star", self.found(UP[:2] + [c(97, 104, 96.5, 103.5), c(104, 104.6, 103.4, 104.2),
                                                           c(103.8, 104, 98, 98.5)]))

    def test_three_white_soldiers(self):
        self.assertIn("three_white_soldiers", self.found(DOWN + UP))

    def test_nothing_on_too_few_candles(self):
        self.assertEqual(pat.candles([c(1, 2, 0.5, 1.5)]), [])


class ChartTest(unittest.TestCase):
    def test_inside_bar(self):
        self.assertIn("inside_bar", pat.chart([c(100, 110, 90, 105), c(101, 108, 95, 103)]))

    def test_nr7(self):
        wide = [c(100, 110, 90, 100)] * 6
        self.assertIn("nr7", pat.chart(wide + [c(100, 102, 99, 101)]))

    def test_bull_flag(self):
        pole = [c(100 + 4 * i, 104.5 + 4 * i, 99.5 + 4 * i, 104 + 4 * i) for i in range(5)]
        flag = [c(120, 121, 118.5, 119.5), c(119.5, 120.5, 118.2, 119), c(119, 120.2, 118, 119.4),
                c(119.4, 120.4, 118.3, 120)]
        base = [c(100, 101, 99, 100)] * 15
        self.assertIn("bull_flag", pat.chart(base + pole + flag))

    def test_contracting_triangle(self):
        tri = [c(100, 110 - i, 90 + i, 100) for i in range(8)]
        self.assertIn("triangle", pat.chart([c(100, 110, 90, 100)] * 6 + tri))


if __name__ == "__main__":
    unittest.main()
