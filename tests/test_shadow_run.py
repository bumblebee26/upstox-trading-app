"""shadows.run: the daily intraday shadow job with fake Upstox and Telegram."""
import tempfile
import unittest
from datetime import datetime

from core import journal, storage
from shadows import run
from tests.test_shadow_intraday import minute_day


def daily_rows(n=230, close=100.0):
    return [{"ts": f"2026-{(d // 28) % 11 + 1:02d}-{d % 28 + 1:02d}T00:00:00+05:30", "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": 10 ** 7} for d in range(n)]


class FakeUx:
    def __init__(self):
        self.charge_calls = 0
        self.path = [100.0] * 20 + [100.0 + 0.1 * i for i in range(1, 30)] + [103.0] * 326

    def instruments(self):
        return {"eq": {"ABC": {"key": "NSE_EQ|ABC"}, "TINY": {"key": "NSE_EQ|TINY"}},
                "index": {"Nifty 50": "NSE_INDEX|Nifty 50", "India VIX": "NSE_INDEX|India VIX",
                          "Nifty IT": "NSE_INDEX|Nifty IT", "Nifty 500": "NSE_INDEX|Nifty 500"}}

    def holidays(self):
        return []

    def historical_candles(self, key, unit, interval, start, end):
        rows = daily_rows()
        if key == "NSE_EQ|TINY":
            for r in rows:
                r["volume"] = 1000  # ₹1 lakh a day: fails the ₹50 crore turnover guardrail
        if key == "NSE_INDEX|India VIX":
            for r in rows:
                r["close"] = 14.0
        return rows

    def intraday_candles(self, key, minutes=1):
        return minute_day(self.path, vol_at={i: 9000 for i in range(20, 50)})

    def charges(self, *a):
        self.charge_calls += 1
        return {"total": 8.0}


class FakeTg:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, reply_to=None, now_ist=None):
        self.sent.append(text)


class RunTest(unittest.TestCase):
    def test_runs_every_variant_on_the_liquid_universe_and_saves_results(self):
        store, ux, tg = storage.Local(tempfile.mkdtemp()), FakeUx(), FakeTg()
        out = run.run_day(now=datetime(2026, 12, 14, 16, 10), store=store, ux=ux, tg=tg,
                          members={"ABC": {"industry": "Information Technology"}, "TINY": {"industry": "Textiles"}},
                          charges=lambda key, qty, pool, side, price: ux.charges(key) and 8.0)
        saved = storage.get_json("shadows/intraday/2026-12-14.json", store=store)
        self.assertEqual(saved["universe"], ["ABC"])
        self.assertEqual(len(saved["variants"]), 68)  # 66 rule variants + A01 and A02
        self.assertGreater(out["trades"], 0)
        e05 = saved["variants"]["E05-X1"]
        self.assertEqual(e05["trades"][0]["symbol"], "ABC")
        self.assertIn("🧪 Shadows", tg.sent[-1])
        self.assertLess(ux.charge_calls, 2 * out["trades"])  # identical orders are priced once

    def test_ai_split_tests_replay_the_ais_real_entries(self):
        store, ux, tg = storage.Local(tempfile.mkdtemp()), FakeUx(), FakeTg()
        local = tempfile.mkdtemp()
        journal.append("2026-12-14", "review", base_dir=local, mirror=store, review_id="ABC-092000", symbol="ABC",
                       key="NSE_EQ|ABC", side="BUY", stop=99.0)
        journal.append("2026-12-14", "fill", base_dir=local, mirror=store, review_id="ABC-092000", symbol="ABC",
                       side="BUY", qty=10, price=100.0, at="2026-12-14T09:35:20")
        run.run_day(now=datetime(2026, 12, 14, 16, 10), store=store, ux=ux, tg=tg,
                    members={"ABC": {"industry": "Information Technology"}}, charges=lambda *a: 8.0)
        saved = storage.get_json("shadows/intraday/2026-12-14.json", store=store)["variants"]
        self.assertEqual([t["entry_time"][11:16] for t in saved["A01"]["trades"]], ["09:36"])
        self.assertEqual(len(saved["A02"]["trades"]), 1)
        self.assertNotEqual(saved["A01"]["trades"][0]["exit_reason"], saved["A02"]["trades"][0]["exit_reason"])

    def test_holiday_and_weekend_skip(self):
        ux = FakeUx()
        ux.holidays = lambda: [{"date": "2026-12-14", "holiday_type": "TRADING_HOLIDAY", "closed_exchanges": ["NSE"]}]
        self.assertIn("skipped", run.run_day(now=datetime(2026, 12, 14, 16, 10), store=storage.Local(tempfile.mkdtemp()),
                                             ux=ux, tg=FakeTg(), members={}, charges=lambda *a: 8.0))
        self.assertIn("skipped", run.run_day(now=datetime(2026, 12, 19, 16, 10), store=storage.Local(tempfile.mkdtemp()),
                                             ux=FakeUx(), tg=FakeTg(), members={}, charges=lambda *a: 8.0))


if __name__ == "__main__":
    unittest.main()
