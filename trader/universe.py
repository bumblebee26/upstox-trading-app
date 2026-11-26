"""What the trader may look at: the Nifty 500 (with each stock's industry and sector index) as the core,
plus any other NSE stock the screen finds moving on news or volume (trader/screen.py).
"""
import csv
import io
import logging

from core import http, storage

log = logging.getLogger("upx")

NIFTY500_URLS = (
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
)
NIFTY500_KEY = "universe/nifty500.csv"  # the last good copy, used when NSE blocks the download

# niftyindices industry -> the Upstox NSE index that tracks it (names as Upstox lists them, 26 Nov 2026).
# shortcut: banks sit inside "Financial Services" in this list, so they compare against Nifty Fin Service,
# not Nifty Bank; split them if the Basic Industry column becomes available.
SECTOR_INDEX = {
    "Financial Services": "Nifty Fin Service",
    "Information Technology": "Nifty IT",
    "Healthcare": "NIFTY HEALTHCARE",
    "Automobile and Auto Components": "Nifty Auto",
    "Fast Moving Consumer Goods": "Nifty FMCG",
    "Metals & Mining": "Nifty Metal",
    "Oil Gas & Consumable Fuels": "NIFTY OIL AND GAS",
    "Power": "Nifty Energy",
    "Capital Goods": "NIFTY INDIA MFG",
    "Construction": "Nifty Infra",
    "Construction Materials": "Nifty Cement",
    "Realty": "Nifty Realty",
    "Chemicals": "Nifty Chemicals",
    "Consumer Durables": "NIFTY CONSR DURBL",
    "Consumer Services": "Nifty Consumption",
    "Telecommunication": "Nifty MS IT Telcm",
    "Media Entertainment & Publication": "Nifty Media",
    "Services": "Nifty Serv Sector",
}
FALLBACK_INDEX = "Nifty 500"
MIN_MEMBERS = 400


def sector_index(industry):
    return SECTOR_INDEX.get(industry, FALLBACK_INDEX)


def parse_members(text):
    """{symbol: {industry, isin}} from the niftyindices CSV."""
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return {r["Symbol"].strip(): {"industry": r["Industry"].strip(), "isin": r["ISIN Code"].strip()}
            for r in rows if r.get("Symbol") and r.get("Series", "EQ").strip() == "EQ"}


def nifty500(store=None):
    """Today's Nifty 500 members. Tries NSE, then niftyindices, then the last good copy."""
    store = store or storage.backend()
    for url in NIFTY500_URLS:
        try:
            text = http.request("GET", url, headers={"Accept": "text/csv"}, retries=2, timeout=30).decode("utf-8")
            members = parse_members(text)
            if len(members) >= MIN_MEMBERS:  # a real list, not an error page
                store.put(NIFTY500_KEY, text.encode())
                return members
        except (RuntimeError, http.NotFound, UnicodeDecodeError) as err:
            log.warning("Nifty 500 list from %s failed: %s", url, err)
    saved = store.get(NIFTY500_KEY)
    if saved is None:
        raise RuntimeError("Nifty 500 list unavailable: NSE and niftyindices refused, and no saved copy")
    log.warning("using the saved Nifty 500 list")
    return parse_members(saved.decode("utf-8"))


def baseline_row(daily):
    """Usual activity from the last 20 daily candles: average volume and turnover (₹ crore), last close."""
    last = daily[-20:]
    if not last:
        return None
    return {"avg_volume": round(sum(c["volume"] for c in last) / len(last)),
            "avg_turnover_cr": round(sum(c["volume"] * c["close"] for c in last) / len(last) / 1e7, 2),
            "prev_close": daily[-1]["close"]}
