"""trader.rank: code-ranked candidates for the swing and long-term AI."""
import unittest

from trader import rank


def daily(closes, vol=10 ** 6):
    return [{"ts": f"d{i}", "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": vol}
            for i, c in enumerate(closes)]


UP = daily([100 + i * 0.5 + (2 if i % 2 else -2) for i in range(260)])  # uptrend with normal dips, near its high
DOWN = daily([300 - i * 0.5 + (2 if i % 2 else -2) for i in range(260)])  # downtrend
HOT = daily([100 + i * 0.5 for i in range(250)] + [230 + i * 8 for i in range(10)])  # stretched, RSI near 100


class SwingTest(unittest.TestCase):
    def test_uptrends_only_best_first_with_numbers(self):
        rows = rank.swing({"UP": UP, "DOWN": DOWN, "HOT": HOT})
        self.assertEqual([r["symbol"] for r in rows], ["UP"])  # DOWN is not in an uptrend, HOT is RSI 80+
        r = rows[0]
        self.assertGreater(r["ret_3m_pct"], 0)
        self.assertLess(r["from_52w_high_pct"], 1)

    def test_needs_enough_history(self):
        self.assertEqual(rank.swing({"NEW": daily([100] * 50)}), [])


RATIOS = {
    "GOOD": [{"name": "P/E", "company_value": "18.5", "sector_value": "25.0"},
             {"name": "ROE", "company_value": "21.0%", "sector_value": "15%"},
             {"name": "ROCE", "company_value": "24.5%", "sector_value": "16%"},
             {"name": "P/B", "company_value": "3.1", "sector_value": "4"}],
    "DEAR": [{"name": "P/E", "company_value": "90", "sector_value": "25.0"},
             {"name": "ROE", "company_value": "22%", "sector_value": "15%"},
             {"name": "ROCE", "company_value": "25%", "sector_value": "16%"}],
    "WEAK": [{"name": "P/E", "company_value": "10", "sector_value": "25.0"},
             {"name": "ROE", "company_value": "6%", "sector_value": "15%"},
             {"name": "ROCE", "company_value": "7%", "sector_value": "16%"}],
    "BAD": [{"name": "P/E", "company_value": "-", "sector_value": "25"}],
}


class LongTermTest(unittest.TestCase):
    def test_quality_at_a_fair_price_ranks_first(self):
        rows = rank.long_term(RATIOS)
        self.assertEqual(rows[0]["symbol"], "GOOD")
        self.assertNotIn("WEAK", [r["symbol"] for r in rows])  # ROCE under 15%
        self.assertNotIn("BAD", [r["symbol"] for r in rows])   # no usable numbers
        self.assertEqual(rows[0]["roce_pct"], 24.5)

    def test_parse_ratio_values(self):
        self.assertEqual([rank.num(v) for v in ("21.0%", "18.5", "-", None, "1,234.5")], [21.0, 18.5, None, None, 1234.5])


if __name__ == "__main__":
    unittest.main()
