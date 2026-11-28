"""appdata/export.py and appdata/sql.py: the app's data file, built after each lakehouse run."""
import gzip
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from appdata import export, sql
from core import storage


class SqlRowsTest(unittest.TestCase):
    def test_numbers_become_numbers_and_the_rest_stays_text(self):
        reply = {"manifest": {"schema": {"columns": [{"name": "day", "type_name": "DATE"}, {"name": "net", "type_name": "DOUBLE"},
                                                     {"name": "n", "type_name": "LONG"}]}},
                 "result": {"data_array": [["2026-11-27", "640.5", "3"], ["2026-11-26", None, "0"]]}}
        self.assertEqual(sql.to_rows(reply), [{"day": "2026-11-27", "net": 640.5, "n": 3}, {"day": "2026-11-26", "net": None, "n": 0}])


class QueriesTest(unittest.TestCase):
    def test_a_failed_query_keeps_its_previous_rows(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "good.sql").write_text("SELECT 1")
        (folder / "bad.sql").write_text("SELECT broken")

        def query(text):
            if "broken" in text:
                raise RuntimeError("table not found")
            return [{"x": 1}]

        previous = {"datasets": {"bad": {"rows": [{"x": 0}]}}}
        datasets, failed = export.run_queries(previous, query=query, folder=folder)
        self.assertEqual(datasets, {"good": {"rows": [{"x": 1}]}, "bad": {"rows": [{"x": 0}]}})
        self.assertEqual(failed, ["bad"])

    def test_every_query_file_reads_only_upx_tables(self):
        for f in sorted(export.QUERIES.glob("*.sql")):
            code = re.sub(r"--[^\n]*", "", f.read_text())  # comments are prose, not tables
            ctes = set(re.findall(r"(?i)\b(\w+)\s+AS\s*\(", code))  # WITH name AS (...): the query's own steps
            for table in re.findall(r"(?i)\b(?:from|join)\s+([\w.`]+)", code):
                self.assertTrue(table.strip("`").startswith("upx.") or table in ctes, f"{f.name}: {table}")


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.app = storage.Local(tempfile.mkdtemp())
        rows = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "SBIN", "instrument_key": "NSE_EQ|INE062A01020",
                 "isin": "INE062A01020", "name": "STATE BANK OF INDIA"},
                {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "SBIN", "lot_size": 750, "expiry": 1}]
        self.gz = gzip.compress(json.dumps(rows).encode())

    def fetch(self, method, url, **kw):
        if url.endswith(".json.gz"):
            return self.gz
        if "IndexConstituent" in url:
            return b"Company Name,Industry,Symbol,Series,ISIN Code\nState Bank of India,Financial Services,SBIN,EQ,INE062A01020\n"
        raise OSError("offline")

    def run_once(self, day):
        return export.build(day, self.app, query=lambda text: [{"ok": 1}], fetch=self.fetch, trader=self.app,
                            candles=lambda s, d: [],
                            market_values=lambda: ({"petrol": {"value": 111.21, "as_of": day.isoformat(), "source": "Upstox"}}, ["cng"]))

    def test_writes_the_data_file_the_stock_list_and_the_market_book(self):
        out = self.run_once(date(2026, 11, 28))
        desk = storage.get_json("app/data/desk.json", store=self.app)
        self.assertEqual(desk["markets"][0]["item"], "petrol")
        self.assertIn("data_freshness", desk["datasets"])
        self.assertEqual(desk["failed"], ["markets: cng"])
        self.assertEqual(out["failed"], desk["failed"])
        listed = storage.get_json("app/data/stocks.json", store=self.app)
        self.assertEqual(listed["stocks"][0]["s"], "SBIN")
        self.assertEqual(listed["stocks"][0]["lot"], 750)
        self.assertEqual(listed["indices"]["Nifty 50"], ["SBIN"])
        self.assertIsNotNone(storage.get_json("history/markets/2026-11-28.json", store=self.app))

    def test_the_stock_list_is_rebuilt_once_a_day(self):
        self.run_once(date(2026, 11, 28))
        self.gz = None  # a second download would fail
        self.run_once(date(2026, 11, 28))
        self.assertEqual(storage.get_json("app/data/stocks.json", store=self.app)["day"], "2026-11-28")


if __name__ == "__main__":
    unittest.main()


class PageContractTest(unittest.TestCase):
    def test_every_dataset_the_page_reads_has_a_query(self):
        page = (Path(__file__).parent.parent / "app" / "index.html").read_text()
        used = set(re.findall(r'\bds\("(\w+)"\)', page))
        have = {f.stem for f in export.QUERIES.glob("*.sql")}
        self.assertTrue(used, "the page reads no datasets?")
        self.assertEqual(used - have, set(), "the page reads datasets that no query makes")

    def test_every_market_item_the_page_shows_is_fetched(self):
        from appdata import markets
        page = (Path(__file__).parent.parent / "app" / "index.html").read_text()
        shown = set(re.findall(r'\b(?:market|t|m)\("(\w+)"', page))
        self.assertEqual(shown - set(markets.LABELS), set())
