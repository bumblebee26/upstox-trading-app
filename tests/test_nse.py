"""core.nse: the NSE files (delivery bhavcopy, bulk and block deals, filings, results calendar), parsed and saved."""
import json
import tempfile
import unittest
from datetime import date

from core import http, nse, storage

BHAV = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, "
        "TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "ABC, EQ, 26-Nov-2026, 100.00, 101.00, 105.00, 99.00, 104.00, 104.50, 102.30, 200000, 204.60, 5000, 120000, 60.00\n"
        "ABC, BE, 26-Nov-2026, 100.00, 101.00, 105.00, 99.00, 104.00, 104.50, 102.30, 10, 0.01, 1, 10, 100.00\n"
        "XYZ, EQ, 26-Nov-2026, 50.00, 50.00, 51.00, 49.00, 50.00, 50.20, 50.10, 1000, 0.50, 20, -, -\n")
DEALS = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
         "26-NOV-2026,ABC,ABC Ltd,BIG FUND LLP,BUY,\"1,00,000\",104.25,-\n"
         "26-NOV-2026,XYZ,XYZ Ltd,SOMEONE,SELL,5000,50.1,-\n")


class ParseTest(unittest.TestCase):
    def test_bhavcopy_keeps_eq_rows_with_delivery(self):
        rows = nse.parse_bhav(BHAV)
        self.assertEqual(set(rows), {"ABC", "XYZ"})
        self.assertEqual(rows["ABC"], {"close": 104.5, "volume": 200000, "deliv_qty": 120000, "deliv_pct": 60.0})
        self.assertIsNone(rows["XYZ"]["deliv_pct"])

    def test_deals(self):
        d = nse.parse_deals(DEALS)
        self.assertEqual(d[0], {"day": "2026-11-26", "symbol": "ABC", "client": "BIG FUND LLP", "side": "BUY",
                                "qty": 100000, "price": 104.25})
        self.assertEqual(d[1]["side"], "SELL")

    def test_calendar_dates(self):
        cal = nse.parse_calendar([{"symbol": "TCS", "company": "TCS Ltd", "purpose": "Financial Results",
                                   "date": "28-Nov-2026"}, {"symbol": "BAD", "date": "soon"}])
        self.assertEqual(cal, [{"symbol": "TCS", "purpose": "Financial Results", "day": "2026-11-28"}])


class SaveTest(unittest.TestCase):
    def test_saves_each_file_and_survives_a_missing_one(self):
        store = storage.Local(tempfile.mkdtemp())

        def fetch(url):
            if "sec_bhavdata_full_26112026" in url:
                raise http.NotFound(url)  # not published yet, or a holiday
            if url.endswith("bulk.csv") or url.endswith("block.csv"):
                return DEALS.encode()
            if "corporate-announcements" in url:
                return json.dumps([{"symbol": "ABC", "desc": "Outcome of Board Meeting", "an_dt": "26-Nov-2026 18:00:00",
                                    "attchmntFile": "https://nsearchives.nseindia.com/x.pdf"}]).encode()
            if "event-calendar" in url:
                return b'[{"symbol": "TCS", "purpose": "Financial Results", "date": "28-Nov-2026"}]'
            raise AssertionError(url)

        out = nse.save_day(date(2026, 11, 26), store=store, fetch=fetch)
        self.assertEqual(out, {"bhav": None, "bulk": 2, "block": 2, "filings": 1, "calendar": 1})
        self.assertEqual(storage.get_json("nse/2026-11-26/bulk.json", store=store)[0]["symbol"], "ABC")
        self.assertEqual(storage.get_json("nse/2026-11-26/filings.json", store=store)[0]["desc"], "Outcome of Board Meeting")
        self.assertIsNone(storage.get_json("nse/2026-11-26/bhav.json", store=store))


if __name__ == "__main__":
    unittest.main()
