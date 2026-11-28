"""appdata/markets.py: today's market values for the app, each with its change from the previous saved day."""
import unittest
from datetime import date

from appdata import markets

IBJA = ("Gold rate daily opening and closing rates for India 999 Purity 12630 (1 Gram) 995 Purity 12579 (1 Gram) "
        "Previous Dates Rate Karat/Purity AM PM 999 995 916 750 585 Silver 999 Platinum 999 "
        "27/11/2026 125316 124814 114789 93987 73310 153275 47540 26/11/2026 122982 122490 112652 92237 71944 146933 45577 "
        "999 995 916 750 585 Silver 999 Platinum 999 "
        "27/11/2026 126299 125793 115690 94724 73885 154300 47740 26/11/2026 122641 122150 112339 91981 71745 147347 46800 "
        "*Gold rates per 10gm & Silver rate per 1kg")
PETROL = ("Petrol price in Mumbai on Saturday , 28 November 2026 , stands at ₹ 111.21 per litre. Compared to 1 week&#x27;s "
          "ago price of ₹ 111.21 on 21 November 2026")
CNG = "CNG price in Mumbai on Saturday , 28 November 2026 , stands at ₹ 91.50 per kg. Compared to 1 weeks"


class ParseTest(unittest.TestCase):
    def test_ibja_takes_the_latest_day_and_the_closing_pm_rates(self):
        self.assertEqual(markets.parse_ibja(IBJA), {"gold999": (12629.9, "2026-11-27"), "silver999": (154300.0, "2026-11-27")})

    def test_fuel_price_and_its_day(self):
        self.assertEqual(markets.parse_fuel(PETROL), (111.21, "2026-11-28"))
        self.assertEqual(markets.parse_fuel(CNG), (91.5, "2026-11-28"))

    def test_an_unexpected_page_raises(self):
        with self.assertRaises(ValueError):
            markets.parse_fuel("Prices are not available")
        with self.assertRaises(ValueError):
            markets.parse_ibja("maintenance")


class FetchTest(unittest.TestCase):
    def fetch(self, method, url, **kw):
        if "ibjarates" in url:
            return IBJA.encode()
        if "coinbase" in url:
            raise OSError("down")
        if "moneyconvert" in url:
            return b'{"rates": {"INR": 92.96}, "ts": "2026-11-28T09:25:01Z"}'
        if "petrol" in url or "diesel" in url:
            return PETROL.encode()
        if "cng" in url:
            return CNG.encode()
        raise AssertionError(url)

    def quotes(self, keys):
        return {"NSE_INDEX|Nifty 50": {"last_price": 25607.2, "timestamp": "2026-11-28T15:37:22.251+05:30"},
                "BSE_INDEX|SENSEX": {"last_price": 84328.59, "timestamp": "2026-11-28T15:37:22.251+05:30"}}

    def test_each_source_or_nothing_and_usd_falls_back_to_moneyconvert(self):
        vals, failed = markets.fetch_all(fetch=self.fetch, quotes=self.quotes)
        self.assertEqual(vals["usdinr"], {"value": 92.96, "as_of": "2026-11-28", "source": "MoneyConvert"})
        self.assertEqual(vals["nifty50"]["value"], 25607.2)
        self.assertEqual(vals["gold999"]["source"], "IBJA")
        self.assertEqual(vals["cng"]["value"], 91.5)
        self.assertNotIn("vix", vals)  # no quote came back for it
        self.assertEqual(failed, ["vix"])


class ChangeTest(unittest.TestCase):
    def test_first_day_shows_no_change(self):
        book = markets.update({}, {"petrol": {"value": 111.21, "as_of": "2026-11-28", "source": "Upstox"}})
        self.assertEqual(book["petrol"]["prev"], None)
        self.assertEqual(markets.rows(book)[0]["change"], None)

    def test_a_new_day_moves_today_to_previous(self):
        book = {"petrol": {"value": 111.21, "as_of": "2026-11-27", "prev": None, "prev_as_of": None, "source": "Upstox"}}
        book = markets.update(book, {"petrol": {"value": 113.18, "as_of": "2026-11-28", "source": "Upstox"}})
        r = markets.rows(book)[0]
        self.assertEqual((r["value"], r["prev"], r["prev_as_of"]), (113.18, 111.21, "2026-11-27"))
        self.assertEqual((r["change"], r["change_pct"]), (1.97, 1.77))

    def test_the_same_day_updates_the_value_but_keeps_the_previous_day(self):
        book = {"nifty50": {"value": 25500, "as_of": "2026-11-28", "prev": 25884.5, "prev_as_of": "2026-11-27", "source": "Upstox"}}
        book = markets.update(book, {"nifty50": {"value": 25607.2, "as_of": "2026-11-28", "source": "Upstox"}})
        self.assertEqual((book["nifty50"]["value"], book["nifty50"]["prev"]), (25607.2, 25884.5))

    def test_a_failed_source_keeps_the_last_good_value_and_its_date(self):
        book = {"gold999": {"value": 12629.9, "as_of": "2026-11-27", "prev": 12298.2, "prev_as_of": "2026-11-26", "source": "IBJA"}}
        self.assertEqual(markets.update(book, {}), book)

    def test_a_scraped_price_far_from_the_last_good_one_is_ignored(self):
        book = {"diesel": {"value": 97.83, "as_of": "2026-11-27", "prev": None, "prev_as_of": None, "source": "Upstox"}}
        self.assertEqual(markets.update(book, {"diesel": {"value": 9.783, "as_of": "2026-11-28", "source": "Upstox"}}), book)


if __name__ == "__main__":
    unittest.main()
