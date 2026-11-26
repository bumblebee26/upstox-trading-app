"""trader.universe: Nifty 500 list, sector index for each industry, the daily baseline."""
import tempfile
import unittest
from unittest import mock

from core import storage
from trader import universe

CSV = ("Company Name,Industry,Symbol,Series,ISIN Code\r\n"
       "HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034\r\n"
       "Infosys Ltd.,Information Technology,INFY,EQ,INE009A01021\r\n"
       "Some Textiles Ltd.,Textiles,SOMETEX,EQ,INE000T01011\r\n")


class IndexListTest(unittest.TestCase):
    def test_other_index_lists_use_the_same_sources(self):
        urls = []

        def fake(method, url, **kw):
            urls.append(url)
            return CSV.encode()

        with mock.patch.object(universe.http, "request", fake):
            m = universe.index_list("nifty50", store=storage.Local(tempfile.mkdtemp()), minimum=3)
        self.assertEqual(set(m), {"HDFCBANK", "INFY", "SOMETEX"})
        self.assertTrue(urls[0].endswith("/ind_nifty50list.csv"))


class Nifty500Test(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(universe, "MIN_MEMBERS", 3)  # the sample has 3 stocks, not 500
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parse(self):
        m = universe.parse_members(CSV)
        self.assertEqual(m["INFY"], {"industry": "Information Technology", "isin": "INE009A01021"})
        self.assertEqual(len(m), 3)

    def test_sector_index_with_fallback(self):
        self.assertEqual(universe.sector_index("Information Technology"), "Nifty IT")
        self.assertEqual(universe.sector_index("Textiles"), "Nifty 500")

    def test_fetch_falls_back_to_the_saved_copy(self):
        store = storage.Local(tempfile.mkdtemp())
        with mock.patch.object(universe.http, "request", return_value=CSV.encode()):
            self.assertEqual(len(universe.nifty500(store=store)), 3)
        with mock.patch.object(universe.http, "request", side_effect=RuntimeError("blocked")):
            self.assertEqual(len(universe.nifty500(store=store)), 3)  # yesterday's copy

    def test_no_list_anywhere_raises(self):
        with mock.patch.object(universe.http, "request", side_effect=RuntimeError("blocked")):
            with self.assertRaises(RuntimeError):
                universe.nifty500(store=storage.Local(tempfile.mkdtemp()))


class BaselineTest(unittest.TestCase):
    def test_average_volume_turnover_and_prev_close(self):
        daily = [{"ts": f"2026-12-{d:02d}T00:00:00+05:30", "open": 100, "high": 105, "low": 95, "close": 100 + d,
                  "volume": 1_000_000} for d in range(1, 22)]
        b = universe.baseline_row(daily)
        self.assertEqual(b["avg_volume"], 1_000_000)
        self.assertAlmostEqual(b["avg_turnover_cr"], 11.15, places=2)  # 10 lakh shares x ₹111.50 average = ₹11.15 crore
        self.assertEqual(b["prev_close"], 121)


if __name__ == "__main__":
    unittest.main()
