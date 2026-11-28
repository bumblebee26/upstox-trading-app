"""appdata/stocks.py: the stock list for the app's search and Explore tab, with Upstox links and index lists."""
import gzip
import json
import unittest

from appdata import stocks

CSV = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
       "HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034\n"
       "State Bank of India,Financial Services,SBIN,EQ,INE062A01020\n")
EQ = {"SBIN": {"key": "NSE_EQ|INE062A01020", "isin": "INE062A01020", "name": "STATE BANK OF INDIA"},
      "HDFCBANK": {"key": "NSE_EQ|INE040A01034", "isin": "INE040A01034", "name": "HDFC BANK LTD"},
      "M&M": {"key": "NSE_EQ|INE101A01026", "isin": "INE101A01026", "name": "MAHINDRA & MAHINDRA LTD"}}


class LinkTest(unittest.TestCase):
    def test_upstox_link_from_name_and_isin(self):
        self.assertEqual(stocks.upstox_link("Mahindra & Mahindra Ltd.", "INE101A01026"),
                         "https://upstox.com/stocks/mahindra-and-mahindra-ltd/INE101A01026")  # isolation-ok


class IndexTest(unittest.TestCase):
    def test_reads_nse_index_file(self):
        self.assertEqual(stocks.parse_index_csv(CSV), [
            {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd.", "industry": "Financial Services", "isin": "INE040A01034"},
            {"symbol": "SBIN", "name": "State Bank of India", "industry": "Financial Services", "isin": "INE062A01020"}])

    def test_a_file_without_the_columns_raises(self):
        with self.assertRaises(ValueError):
            stocks.parse_index_csv("<html>blocked</html>")

    def test_lists_refresh_once_a_month_and_a_failed_index_keeps_last_month(self):
        calls = []

        def fetch(method, url, **kw):
            calls.append(url)
            if "banklist" in url:
                raise OSError("down")
            return CSV.encode()

        last = {"month": "2026-10", "lists": {"Bank Nifty": [{"symbol": "SBIN"}]}}
        book = stocks.index_lists(last, "2026-11", fetch=fetch, files={"Nifty 50": "ind_nifty50list.csv", "Bank Nifty": "ind_niftybanklist.csv"})
        self.assertEqual(book["month"], "2026-11")
        self.assertEqual([r["symbol"] for r in book["lists"]["Nifty 50"]], ["HDFCBANK", "SBIN"])
        self.assertEqual(book["lists"]["Bank Nifty"], [{"symbol": "SBIN"}])
        self.assertEqual(book["failed"], ["Bank Nifty"])
        n = len(calls)
        self.assertIs(stocks.index_lists(book, "2026-11", fetch=fetch), book)  # same month: no download
        self.assertEqual(len(calls), n)


class ListTest(unittest.TestCase):
    def test_every_nse_stock_with_its_industry_indices_fo_lot_and_link(self):
        lists = {"Nifty 50": stocks.parse_index_csv(CSV), "Bank Nifty": stocks.parse_index_csv(CSV)[1:]}
        out = {r["s"]: r for r in stocks.stock_list(EQ, lists, {"SBIN": 750})}
        self.assertEqual(out["SBIN"], {"s": "SBIN", "n": "State Bank of India", "ind": "Financial Services",
                                       "ix": ["Nifty 50", "Bank Nifty"], "lot": 750,
                                       "u": "https://upstox.com/stocks/state-bank-of-india/INE062A01020"})  # isolation-ok
        self.assertEqual(out["M&M"]["n"], "Mahindra & Mahindra Ltd")  # not in an index: the instrument name, title-cased
        self.assertNotIn("lot", out["M&M"])

    def test_fo_lots_from_the_instrument_file(self):
        rows = [{"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "SBIN", "lot_size": 750, "expiry": 2},
                {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "SBIN", "lot_size": 700, "expiry": 1},
                {"segment": "NSE_FO", "instrument_type": "CE", "underlying_symbol": "TCS", "lot_size": 175, "expiry": 1},
                {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "NIFTY", "lot_size": 75, "expiry": 1}]
        self.assertEqual(stocks.fo_lots(gzip.compress(json.dumps(rows).encode()), {"SBIN", "TCS"}), {"SBIN": 700})


if __name__ == "__main__":
    unittest.main()
