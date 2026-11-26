"""trader.brief: the short morning message (flows, Nifty and VIX, today's results, yesterday's big deals)."""
import json
import tempfile
import unittest
from datetime import datetime

from core import storage
from trader import brief


class FakeUx:
    def instruments(self):
        return {"eq": {}, "index": {"Nifty 50": "NSE_INDEX|Nifty 50", "India VIX": "NSE_INDEX|India VIX"}}

    def quotes(self, keys):
        return {"NSE_INDEX|Nifty 50": {"last_price": 24500.0, "net_change": -73.5},
                "NSE_INDEX|India VIX": {"last_price": 13.25, "net_change": 0.4}}

    def flows(self, who, data_type, interval="1D", start=None):
        amounts = {"fii": (9_000_000_000, 21_340_000_000), "dii": (25_000_000_000, 2_650_000_000)}[who]
        return {"NSE_EQ|CASH": [{"buy_amount": amounts[0], "sell_amount": amounts[1]}]}

    def holidays(self):
        return []


class BriefTest(unittest.TestCase):
    def test_message(self):
        store = storage.Local(tempfile.mkdtemp())
        storage.put_json("nse/2026-11-26/bulk.json", [
            {"day": "2026-11-26", "symbol": "ABC", "client": "BIG FUND LLP", "side": "BUY", "qty": 1_000_000, "price": 450.0},
            {"day": "2026-11-26", "symbol": "XYZ", "client": "SMALL", "side": "SELL", "qty": 1000, "price": 50.0}], store=store)
        storage.put_json("nse/2026-11-26/block.json", [], store=store)
        cal = [{"symbol": s, "purpose": "Financial Results", "date": "27-Nov-2026"} for s in ("TCS", "INFY", "A", "B", "C", "D")]
        sent = []
        out = brief.run(now=datetime(2026, 11, 27, 8, 40), store=store, ux=FakeUx(),
                        tg=type("T", (), {"send": staticmethod(lambda text, **k: sent.append(text))}),
                        fetch=lambda url: json.dumps(cal + [{"symbol": "LATER", "purpose": "Financial Results", "date": "28-Nov-2026"},
                                                           {"symbol": "DIV", "purpose": "Dividend", "date": "27-Nov-2026"}]).encode())
        text = sent[0]
        self.assertEqual(out["results_today"], 6)
        self.assertTrue(text.startswith("🌅 Fri 27 Nov"))
        self.assertIn("FII -₹1,234 cr · DII +₹2,235 cr", text)
        self.assertIn("Nifty 24,500 (-0.30%) · India VIX 13.25", text)
        self.assertIn("Results today (6): TCS, INFY, A, B, C +1 more", text)
        self.assertIn("ABC: BIG FUND LLP bought ₹45 cr", text)
        self.assertNotIn("XYZ", text)  # under ₹1 crore

    def test_quiet_on_closed_days(self):
        self.assertIn("skipped", brief.run(now=datetime(2026, 11, 28, 8, 40), store=storage.Local(tempfile.mkdtemp()),
                                           ux=FakeUx(), tg=None, fetch=None))


if __name__ == "__main__":
    unittest.main()
