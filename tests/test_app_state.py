"""appdata/state.py: the pools' holdings and limits, and the per-trade charts, for the app."""
import json
import tempfile
import unittest
from datetime import time

from appdata import state
from core import storage


class PoolsTest(unittest.TestCase):
    def test_holdings_with_todays_price_and_the_limits(self):
        store = storage.Local(tempfile.mkdtemp())
        storage.put_json("state/swing.json", {"auto": True, "positions": {
            "HAL": {"side": "BUY", "qty": 4, "fill_price": 4410.0, "stop": 4200.0, "target": 4900.0, "opened_at": "2026-11-24T09:20:00"}}}, store=store)
        out = state.pools(store, {"HAL": 4551.0}, limits={"swing": {"risk_pct": 2.0, "entry_window": (time(9, 30), time(14, 30))}})
        self.assertEqual(out["swing"]["auto"], True)
        self.assertEqual(out["swing"]["positions"], [{"symbol": "HAL", "qty": 4, "avg": 4410.0, "now": 4551.0, "stop": 4200.0,
                                                      "target": 4900.0, "since": "2026-11-24"}])
        self.assertEqual(out["swing"]["limits"], {"risk_pct": 2.0, "entry_window": "09:30–14:30"})
        self.assertNotIn("intraday", out)  # no saved state: nothing to show


class OutcomeTest(unittest.TestCase):
    candles = [{"ts": "2026-11-27T10:00:00+05:30", "high": 101, "low": 99}, {"ts": "2026-11-27T10:05:00+05:30", "high": 102, "low": 97},
               {"ts": "2026-11-27T10:10:00+05:30", "high": 106, "low": 100}]

    def test_a_buy_that_hit_its_stop_first(self):
        self.assertEqual(state.first_hit(self.candles, "BUY", stop=98, target=105, after="2026-11-27T10:00:00"), "stop")

    def test_a_buy_that_reached_its_target(self):
        self.assertEqual(state.first_hit(self.candles, "BUY", stop=96, target=105, after="2026-11-27T10:00:00"), "target")

    def test_a_short_and_a_day_that_hit_neither(self):
        self.assertEqual(state.first_hit(self.candles, "SELL", stop=110, target=90, after="2026-11-27T09:00:00"), "neither")

    def test_candles_before_the_review_do_not_count(self):
        self.assertEqual(state.first_hit(self.candles, "BUY", stop=98, target=105, after="2026-11-27T10:06:00"), "target")


class ChartsTest(unittest.TestCase):
    def test_each_reviewed_trade_of_the_last_day_gets_its_candles_and_outcome(self):
        rows = [{"trade_date": "2026-11-27", "pool": "intraday", "event": "review", "review_id": "ABC-100000", "symbol": "ABC",
                 "side": "BUY", "entry": 100, "stop": 98, "target": 105, "at_ist": "2026-11-27T10:00:00"},
                {"trade_date": "2026-11-27", "pool": "intraday", "event": "skipped", "review_id": "ABC-100000", "symbol": "ABC"},
                {"trade_date": "2026-11-26", "pool": "intraday", "event": "review", "review_id": "OLD-1", "symbol": "OLD"}]
        calls = []

        def candles(symbol, day):
            calls.append((symbol, day))
            return OutcomeTest.candles

        out = state.trade_charts(rows, candles)
        self.assertEqual(calls, [("ABC", "2026-11-27")])
        self.assertEqual(out[0]["review_id"], "ABC-100000")
        self.assertEqual(out[0]["skipped"], True)
        self.assertEqual(out[0]["would_have"], "stop")
        self.assertEqual(len(out[0]["candles"]), 3)
        self.assertEqual(out[0]["candles"][0], ["10:00", 99, 101, None, None])  # time, low, high, open, close

    def test_a_failed_candle_fetch_skips_that_chart_only(self):
        rows = [{"trade_date": "2026-11-27", "pool": "intraday", "event": "review", "review_id": "A-1", "symbol": "A", "side": "BUY",
                 "entry": 1, "stop": 0.5, "target": 2, "at_ist": "2026-11-27T10:00:00"}]
        self.assertEqual(state.trade_charts(rows, lambda s, d: (_ for _ in ()).throw(RuntimeError("down"))), [])


if __name__ == "__main__":
    unittest.main()
