"""core.upstox: rate limiter, instrument map, and the shape of each call (no network).

Sample replies follow the Upstox API documentation (read 26 Nov 2026).
"""
import gzip
import json
import unittest
from datetime import date
from unittest import mock

from core import ssm, upstox


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class LimiterTest(unittest.TestCase):
    def test_spreads_calls_to_stay_under_per_second_cap(self):
        clock = FakeClock()
        lim = upstox.Limiter(limits=((1, 2),), clock=clock.time, sleep=clock.sleep)
        for _ in range(3):
            lim.wait("quotes")
        self.assertEqual(clock.slept, [1.0])

    def test_each_api_has_its_own_budget(self):
        clock = FakeClock()
        lim = upstox.Limiter(limits=((1, 1),), clock=clock.time, sleep=clock.sleep)
        lim.wait("quotes")
        lim.wait("candles")
        self.assertEqual(clock.slept, [])
        self.assertEqual(lim.counts, {"quotes": 1, "candles": 1})

    def test_default_caps_keep_headroom_under_upstox_limits(self):
        for (window, cap), (_, upstox_cap) in zip(upstox.LIMITS, ((1, 50), (60, 500), (1800, 2000))):
            self.assertLessEqual(cap, upstox_cap * 0.8)


NSE_FILE = [
    {"segment": "NSE_EQ", "name": "RELIANCE INDUSTRIES LTD", "exchange": "NSE", "isin": "INE002A01018",
     "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018", "lot_size": 1, "tick_size": 10.0,
     "trading_symbol": "RELIANCE"},
    {"segment": "NSE_EQ", "name": "SOME BOND", "exchange": "NSE", "isin": "INE000X01010",
     "instrument_type": "GB", "instrument_key": "NSE_EQ|INE000X01010", "lot_size": 1, "trading_symbol": "SGB1"},
    {"segment": "NSE_INDEX", "name": "Nifty 50", "exchange": "NSE", "instrument_type": "INDEX",
     "instrument_key": "NSE_INDEX|Nifty 50", "trading_symbol": "NIFTY"},
    {"segment": "NSE_FO", "name": "RELIANCE", "instrument_type": "FUT", "instrument_key": "NSE_FO|1",
     "trading_symbol": "RELIANCE FUT"},
]


class InstrumentsTest(unittest.TestCase):
    def test_maps_equities_and_indices_only(self):
        m = upstox.parse_instruments(gzip.compress(json.dumps(NSE_FILE).encode()))
        self.assertEqual(m["eq"]["RELIANCE"]["key"], "NSE_EQ|INE002A01018")
        self.assertEqual(m["eq"]["RELIANCE"]["isin"], "INE002A01018")
        self.assertNotIn("SGB1", m["eq"])
        self.assertEqual(m["index"]["Nifty 50"], "NSE_INDEX|Nifty 50")
        self.assertEqual(len(m["eq"]), 1)


class Calls(unittest.TestCase):
    """Patch the HTTP layer and record every URL the client asks for."""

    def setUp(self):
        ssm._cache[upstox.TOKEN_PARAM] = "TOKEN"
        self.addCleanup(ssm._cache.clear)
        self.urls = []
        self.replies = []
        patcher = mock.patch.object(upstox.http, "get_json", side_effect=self._get)
        patcher.start()
        self.addCleanup(patcher.stop)
        upstox._limiter = upstox.Limiter(limits=((1, 1000),))

    def _get(self, url, headers=None, **kw):
        self.urls.append(url)
        self.assertEqual(headers["Authorization"], "Bearer TOKEN")
        return self.replies.pop(0) if self.replies else {"status": "success", "data": {}}


class QuotesTest(Calls):
    def test_batches_500_and_keys_reply_by_instrument_key(self):
        keys = [f"NSE_EQ|INE{i:09d}" for i in range(501)]
        self.replies = [
            {"status": "success", "data": {"NSE_EQ:AAA": {"instrument_token": keys[0], "last_price": 10.5}}},
            {"status": "success", "data": {"NSE_EQ:BBB": {"instrument_token": keys[500], "last_price": 20.0}}},
        ]
        q = upstox.quotes(keys)
        self.assertEqual(len(self.urls), 2)
        self.assertIn("/v2/market-quote/quotes?instrument_key=NSE_EQ%7CINE000000000%2C", self.urls[0])
        self.assertEqual(q[keys[0]]["last_price"], 10.5)
        self.assertEqual(q[keys[500]]["last_price"], 20.0)

    def test_error_status_raises(self):
        self.replies = [{"status": "error", "errors": [{"message": "Invalid token"}]}]
        with self.assertRaisesRegex(upstox.UpstoxError, "Invalid token"):
            upstox.quotes(["NSE_EQ|X"])


class CandlesTest(Calls):
    def test_intraday_rows_are_oldest_first_named_fields(self):
        self.replies = [{"status": "success", "data": {"candles": [
            ["2026-11-26T09:20:00+05:30", 101, 103, 100, 102, 5000, 0],
            ["2026-11-26T09:15:00+05:30", 100, 102, 99, 101, 8000, 0],
        ]}}]
        rows = upstox.intraday_candles("NSE_EQ|INE002A01018", 5)
        self.assertIn("/v3/historical-candle/intraday/NSE_EQ%7CINE002A01018/minutes/5", self.urls[0])
        self.assertEqual([r["ts"][11:16] for r in rows], ["09:15", "09:20"])
        self.assertEqual(rows[0], {"ts": "2026-11-26T09:15:00+05:30", "open": 100, "high": 102, "low": 99,
                                   "close": 101, "volume": 8000, "oi": 0})

    def test_minute_history_is_split_into_28_day_requests(self):
        upstox.historical_candles("NSE_EQ|K", "minutes", 1, date(2025, 1, 1), date(2025, 3, 15))
        windows = [u.split("/minutes/1/")[1] for u in self.urls]
        self.assertEqual(windows, ["2025-01-28/2025-01-01", "2025-02-25/2025-01-29", "2025-03-15/2025-02-26"])

    def test_daily_history_one_request_per_decade_and_no_duplicates(self):
        row = ["2020-01-01T00:00:00+05:30", 1, 1, 1, 1, 1, 0]
        self.replies = [{"status": "success", "data": {"candles": [row]}},
                        {"status": "success", "data": {"candles": [row]}}]
        rows = upstox.historical_candles("NSE_INDEX|Nifty 50", "days", 1, date(2005, 1, 1), date(2025, 6, 1))
        self.assertEqual(len(self.urls), 3)
        self.assertEqual(len(rows), 1)

    def test_rejects_unknown_unit(self):
        with self.assertRaises(ValueError):
            upstox.historical_candles("K", "seconds", 1, date(2025, 1, 1), date(2025, 1, 2))


class OtherCallsTest(Calls):
    def test_news_batches_30_keys(self):
        upstox.news([f"NSE_EQ|{i}" for i in range(31)])
        self.assertEqual(len(self.urls), 2)
        self.assertIn("/v2/news?category=instrument_keys&instrument_keys=", self.urls[0])

    def test_charges_query(self):
        self.replies = [{"status": "success", "data": {"charges": {"total": 40.5}}}]
        c = upstox.charges("NSE_EQ|K", 10, "I", "BUY", 712.5)
        self.assertEqual(c["total"], 40.5)
        self.assertIn("/v2/charges/brokerage?instrument_token=NSE_EQ%7CK&quantity=10&product=I"
                      "&transaction_type=BUY&price=712.5", self.urls[0])

    def test_fundamentals_paths(self):
        for kind in upstox.FUNDAMENTALS:
            upstox.fundamentals("INE002A01018", kind)
        self.assertTrue(all("/v2/fundamentals/INE002A01018/" in u for u in self.urls))
        with self.assertRaises(ValueError):
            upstox.fundamentals("INE002A01018", "secrets")

    def test_holidays_status_and_flows(self):
        upstox.holidays()
        upstox.market_status()
        upstox.flows("fii", "NSE_EQ|CASH")
        upstox.flows("dii", "NSE_EQ|CASH")
        self.assertTrue(self.urls[0].endswith("/v2/market/holidays"))
        self.assertTrue(self.urls[1].endswith("/v2/market/status/NSE"))
        self.assertIn("/v2/market/fii?data_type=NSE_EQ%7CCASH&interval=1D", self.urls[2])
        self.assertIn("/v2/market/dii?", self.urls[3])
        with self.assertRaises(ValueError):
            upstox.flows("retail", "NSE_EQ|CASH")


if __name__ == "__main__":
    unittest.main()
