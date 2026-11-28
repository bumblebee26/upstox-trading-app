"""Today's market values for the app's Markets tab, each with its change from the previous saved day.

Sources (owner's choice, 27 Nov): Upstox for Nifty 50, Sensex and India VIX; IBJA for gold and silver (the
closing PM rate of the latest day it published); Coinbase for USD/INR (live, indicative) with MoneyConvert as
backup; Upstox's Mumbai fuel pages for petrol, diesel and CNG. We keep no history from the sources: the export
saves each value with its day, and the app shows the change from the previous saved day (none on the first day).
A source that fails keeps its last good value and date.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from core import http, upstox

INDICES = {"nifty50": "NSE_INDEX|Nifty 50", "sensex": "BSE_INDEX|SENSEX", "vix": "NSE_INDEX|India VIX"}
FUEL = {"petrol": "petrol", "diesel": "diesel", "cng": "cng"}
FUEL_URL = "https://upstox.com/{0}-price/{0}-price-in-mumbai/"
IBJA_URL = "https://www.ibjarates.com/"
COINBASE_URL = "https://api.coinbase.com/v2/exchange-rates?currency=USD"
MONEYCONVERT_URL = "https://cdn.moneyconvert.net/api/latest.json"
LABELS = {"nifty50": ("Nifty 50", ""), "sensex": ("Sensex", ""), "vix": ("India VIX", ""),
          "gold999": ("Gold 999", "₹ / 1 g"), "silver999": ("Silver 999", "₹ / 1 kg"),
          "usdinr": ("USD/INR", "₹ per $1, indicative"),
          "petrol": ("Petrol", "₹ / 1 L"), "diesel": ("Diesel", "₹ / 1 L"), "cng": ("CNG", "₹ / 1 kg")}
IST = timezone(timedelta(hours=5, minutes=30))
SCRAPED = ("gold999", "silver999", "petrol", "diesel", "cng")
BAND = 0.15  # a scraped price more than 15% from the last good one is a misread page, not a real move

_IBJA_ROW = re.compile(r"(\d{2})/(\d{2})/(\d{4})" + r"\s+(\d{4,7})" * 7)
_FUEL = re.compile(r"on \w+ , (\d{1,2} \w+ \d{4}) , stands at ₹ ([\d,.]+) per (?:litre|kg)")


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", html)))


def parse_ibja(html):
    """{"gold999": (₹ per gram, day), "silver999": (₹ per kg, day)} from IBJA's two tables (AM, then PM) of
    date, gold 999, 995, 916, 750, 585, silver 999, platinum 999 (gold per 10 g, silver per kg)."""
    rows = {}
    for m in _IBJA_ROW.finditer(_text(html)):
        day = f"{m[3]}-{m[2]}-{m[1]}"
        rows[day] = (int(m[4]), int(m[9]))  # a day's PM row comes after its AM row, so it wins
    if not rows:
        raise ValueError("IBJA page had no rate rows")
    day = max(rows)
    gold10, silver = rows[day]
    return {"gold999": (round(gold10 / 10, 2), day), "silver999": (float(silver), day)}


def parse_fuel(html):
    """(price, day) from an Upstox Mumbai fuel page."""
    m = _FUEL.search(_text(html))
    if not m:
        raise ValueError("fuel page had no 'stands at' line")
    return float(m[2].replace(",", "")), datetime.strptime(m[1], "%d %B %Y").date().isoformat()


def fetch_all(fetch=http.request, quotes=upstox.quotes):
    """({item: {value, as_of, source}}, [items that failed]). Each source is tried on its own."""
    vals, failed = {}, []

    def take(item, value, as_of, source):
        vals[item] = {"value": value, "as_of": as_of, "source": source}

    try:
        q = quotes(list(INDICES.values()))
    except Exception:  # noqa: BLE001 - Upstox down: the indices keep their last good values
        q = {}
    for item, key in INDICES.items():
        if key in q:
            take(item, q[key]["last_price"], q[key]["timestamp"][:10], "Upstox")
    try:
        for item, (value, day) in parse_ibja(fetch("GET", IBJA_URL, timeout=25).decode("utf-8", "replace")).items():
            take(item, value, day, "IBJA")
    except Exception:  # noqa: BLE001 - one source failing must not stop the others
        pass
    try:
        rate = json.loads(fetch("GET", COINBASE_URL, timeout=20))["data"]["rates"]["INR"]
        take("usdinr", round(float(rate), 4), datetime.now(IST).date().isoformat(), "Coinbase")
    except Exception:  # noqa: BLE001 - backup below
        try:
            d = json.loads(fetch("GET", MONEYCONVERT_URL, timeout=20))
            take("usdinr", round(float(d["rates"]["INR"]), 4), d["ts"][:10], "MoneyConvert")
        except Exception:  # noqa: BLE001
            pass
    for item, slug in FUEL.items():
        try:
            value, day = parse_fuel(fetch("GET", FUEL_URL.format(slug), timeout=25).decode("utf-8", "replace"))
            take(item, value, day, "Upstox")
        except Exception:  # noqa: BLE001
            pass
    return vals, [i for i in LABELS if i not in vals]


def update(book, today):
    """The saved book {item: {value, as_of, prev, prev_as_of, source}} with today's values merged in."""
    book = {k: dict(v) for k, v in (book or {}).items()}
    for item, new in today.items():
        old = book.get(item)
        if old and item in SCRAPED and abs(new["value"] - old["value"]) > BAND * old["value"]:
            continue
        if not old:
            book[item] = {**new, "prev": None, "prev_as_of": None}
        elif new["as_of"] > old["as_of"]:
            book[item] = {**new, "prev": old["value"], "prev_as_of": old["as_of"]}
        elif new["as_of"] == old["as_of"]:
            book[item] = {**old, "value": new["value"], "source": new["source"]}
    return book


def rows(book):
    """The app's rows, in display order: change ₹ and % from the previous saved day (None on the first day)."""
    out = []
    for item, (label, unit) in LABELS.items():
        b = book.get(item)
        if not b:
            continue
        chg = round(b["value"] - b["prev"], 2) if b["prev"] is not None else None
        pct = round(chg / b["prev"] * 100, 2) if chg is not None and b["prev"] else None
        out.append({"item": item, "label": label, "unit": unit, "value": b["value"], "as_of": b["as_of"],
                    "prev": b["prev"], "prev_as_of": b["prev_as_of"], "change": chg, "change_pct": pct,
                    "source": b["source"]})
    return out
