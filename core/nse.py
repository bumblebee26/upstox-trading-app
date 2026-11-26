"""NSE files that Upstox doesn't carry, saved once a day to the state bucket under nse/<day>/ (dummy-money
paper trader: these are inputs only).

- bhav.json      delivery bhavcopy: close, volume and delivery % per EQ stock (published about 18:00 IST)
- bulk.json      bulk deals of the day; block.json the block deals
- filings.json   corporate announcements (the newest page)
- calendar.json  board meetings ahead (results dates)

NSE's static archive and its JSON API answer GitHub's runners (checked 27 Nov 2026); its home page does not,
and isn't needed.

  python -m core.nse            today's files (the 19:30 job)
"""
import csv
import io
import json
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone

from core import http, storage

log = logging.getLogger("upx")
IST = timezone(timedelta(hours=5, minutes=30))
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
           "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"}
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
FILINGS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"
CALENDAR_URL = "https://www.nseindia.com/api/event-calendar"


def fetch(url):
    return http.request("GET", url, headers=HEADERS, retries=2, timeout=30)


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _day(text, fmt):
    try:
        return datetime.strptime(text.strip().title(), fmt).date().isoformat()
    except (AttributeError, ValueError):
        return None


def parse_bhav(text):
    """{symbol: {close, volume, deliv_qty, deliv_pct}} for the EQ series ("-" means not reported)."""
    out = {}
    for r in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("SERIES") != "EQ":
            continue
        qty, pct = _num(r.get("DELIV_QTY")), _num(r.get("DELIV_PER"))
        out[r["SYMBOL"]] = {"close": _num(r.get("CLOSE_PRICE")), "volume": int(_num(r.get("TTL_TRD_QNTY")) or 0),
                            "deliv_qty": int(qty) if qty is not None else None, "deliv_pct": pct}
    return out


def parse_deals(text):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        qty = _num(r.get("Quantity Traded"))
        out.append({"day": _day(r.get("Date", ""), "%d-%b-%Y"), "symbol": r.get("Symbol"), "client": r.get("Client Name"),
                    "side": r.get("Buy/Sell", "").upper(), "qty": int(qty) if qty is not None else None,
                    "price": _num(r.get("Trade Price / Wght. Avg. Price"))})
    return out


def parse_calendar(rows):
    out = []
    for r in rows or []:
        d = _day(str(r.get("date", "")), "%d-%b-%Y")
        if d and r.get("symbol"):
            out.append({"symbol": r["symbol"], "purpose": r.get("purpose"), "day": d})
    return out


def quick_fetch(url):
    """One try, 8 seconds: the intraday session waits on this, so a slow NSE must not stall a decision."""
    return http.request("GET", url, headers=HEADERS, retries=1, timeout=8)


def filings(symbol, now=None, days=2, fetch=quick_fetch, top=5):
    """One stock's NSE filings of the last `days` days, newest first, for the AI's facts. Never raises: a
    refused or broken reply gives [] (filings are context, never a reason to block a decision)."""
    now = now or datetime.now(IST).replace(tzinfo=None)
    try:
        rows = json.loads(fetch(f"{FILINGS_URL}&symbol={urllib.parse.quote(symbol)}"))
    except (http.NotFound, RuntimeError, ValueError, OSError) as err:
        log.warning("NSE filings for %s unavailable: %s", symbol, err)
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            when = datetime.strptime(str(r.get("an_dt")), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            continue
        if (now - when).days < days:
            out.append((when, {"when": f"{when.day} {when:%b %H:%M}", "what": r.get("desc"),
                               "detail": (r.get("attchmntText") or "")[:300]}))
    return [f for _, f in sorted(out, key=lambda x: x[0], reverse=True)][:top]


def save_day(day, store=None, fetch=fetch):
    """Fetch and save the day's files; one missing or refused file doesn't stop the others.
    Returns how many rows each file had (None: not available)."""
    store = store or storage.backend()
    jobs = {
        "bhav": (BHAV_URL.format(ddmmyyyy=day.strftime("%d%m%Y")), lambda b: parse_bhav(b.decode("utf-8", "replace"))),
        "bulk": (BULK_URL, lambda b: parse_deals(b.decode("utf-8", "replace"))),
        "block": (BLOCK_URL, lambda b: parse_deals(b.decode("utf-8", "replace"))),
        "filings": (FILINGS_URL, json.loads),
        "calendar": (CALENDAR_URL, lambda b: parse_calendar(json.loads(b))),
    }
    out = {}
    for name, (url, parse) in jobs.items():
        try:
            rows = parse(fetch(url))
        except (http.NotFound, RuntimeError, ValueError) as err:
            log.warning("NSE %s unavailable for %s: %s", name, day, err)
            out[name] = None
            continue
        storage.put_json(f"nse/{day.isoformat()}/{name}.json", rows, store=store)
        out[name] = len(rows)
    return out


if __name__ == "__main__":
    print(json.dumps(save_day(datetime.now(IST).date())))
