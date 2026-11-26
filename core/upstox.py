"""Upstox API client (standard library only): one place for every call this repo makes to Upstox.

Uses the read-only Analytics token, which cannot place orders. Every call goes through one rate limiter,
kept at 80% of Upstox's limits so the trader, the Lambdas and the jobs together stay under them.
Docs: https://upstox.com/developer/api-documentation (read 26 Nov 2026).
"""
import gzip
import json
import os
import tempfile
import time
import urllib.parse
from collections import deque
from datetime import date, timedelta
from pathlib import Path

from core import http, ssm

BASE = "https://api.upstox.com"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
TOKEN_PARAM = "/upx/upstox-analytics-token"

# Upstox: 50 a second, 500 a minute, 2,000 per 30 minutes, per API and per user. Ours: 80% of each.
LIMITS = ((1, 40), (60, 400), (1800, 1600))

# Longest date range one historical request may cover, in days (Upstox: 1 month for 1-15 minute candles,
# 1 quarter for longer minute or hour candles, 1 decade for days). Kept a little under each.
_MAX_DAYS = {"short_minutes": 28, "minutes": 88, "hours": 88, "days": 3650, "weeks": None, "months": None}

FUNDAMENTALS = ("key-ratios", "share-holdings", "corporate-actions", "income-statement", "balance-sheet", "cash-flow")


class UpstoxError(RuntimeError):
    """Upstox answered, but with an error status."""


class Limiter:
    """Waits before a call that would break a limit. Each API (endpoint) has its own budget.

    shortcut: counts only this process's calls; the processes don't share counts. Fine while planned use stays
    under 10% of each limit; upgrade to a shared counter (S3 or SSM) if several busy processes run at once.
    """

    def __init__(self, limits=LIMITS, clock=time.monotonic, sleep=time.sleep):
        self.limits, self.clock, self.sleep = limits, clock, sleep
        self.calls = {}   # api -> recent call times
        self.counts = {}  # api -> calls made by this process (logged daily)

    def wait(self, api):
        recent = self.calls.setdefault(api, deque())
        longest = max(window for window, _ in self.limits)
        while True:
            now = self.clock()
            while recent and recent[0] <= now - longest:
                recent.popleft()
            delay = 0.0
            for window, cap in self.limits:
                inside = [t for t in recent if t > now - window]
                if len(inside) >= cap:
                    delay = max(delay, inside[-cap] + window - now)
            if delay <= 0:
                break
            self.sleep(delay)
        recent.append(self.clock())
        self.counts[api] = self.counts.get(api, 0) + 1


_limiter = Limiter()


def _token():
    # A manual GitHub check job passes the token in UPSTOX_TOKEN; everything else reads SSM.
    return os.environ.get("UPSTOX_TOKEN") or ssm.get(TOKEN_PARAM)


def _q(value):
    return urllib.parse.quote(str(value), safe="")


def _get(api, path, params=None):
    """Call one endpoint and return its "data". `api` names the rate-limit budget."""
    _limiter.wait(api)
    url = BASE + path + ("?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote) if params else "")
    body = http.get_json(url, headers={"Authorization": f"Bearer {_token()}", "Accept": "application/json"})
    if body.get("status") != "success":
        messages = "; ".join(e.get("message", "") for e in body.get("errors", [])) or json.dumps(body)[:300]
        raise UpstoxError(f"{path}: {messages}")
    return body.get("data")


def _batches(items, size):
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items), size)]


# ---- Instruments: symbol -> instrument key and ISIN -------------------------------------------------------

def parse_instruments(gz_bytes):
    """{"eq": {symbol: {key, isin, name, lot_size, tick_size}}, "index": {index name: key}} from the NSE file."""
    eq, index = {}, {}
    for r in json.loads(gzip.decompress(gz_bytes)):
        if r.get("segment") == "NSE_EQ" and r.get("instrument_type") == "EQ":
            eq[r["trading_symbol"]] = {"key": r["instrument_key"], "isin": r.get("isin"), "name": r.get("name"),
                                       "lot_size": r.get("lot_size"), "tick_size": r.get("tick_size")}
        elif r.get("segment") == "NSE_INDEX":
            index[r["name"]] = r["instrument_key"]
    return {"eq": eq, "index": index}


def instruments(today=None):
    """Today's instrument map. Upstox refreshes the file about 06:00 IST; we download it once a day.

    shortcut: cached in this machine's temp folder only; PR 9 moves the daily copy to the state bucket.
    """
    today = today or date.today()
    cache = Path(tempfile.gettempdir()) / f"upx-instruments-{today.isoformat()}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    m = parse_instruments(http.request("GET", INSTRUMENTS_URL, timeout=60))
    cache.write_text(json.dumps(m))
    return m


# ---- Market data -------------------------------------------------------------------------------------------

def quotes(keys):
    """Full quotes keyed by instrument key: last_price, ohlc, depth (5 bid/ask), volume, average_price,
    circuit limits, last_trade_time. Up to 500 instruments per call."""
    out = {}
    for batch in _batches(keys, 500):
        data = _get("quotes", "/v2/market-quote/quotes", {"instrument_key": ",".join(batch)}) or {}
        for q in data.values():  # the reply is keyed "NSE_EQ:SYMBOL"; instrument_token is the key we asked for
            out[q["instrument_token"]] = q
    return out


def _rows(data):
    rows = [dict(zip(("ts", "open", "high", "low", "close", "volume", "oi"), c)) for c in (data or {}).get("candles", [])]
    return sorted(rows, key=lambda r: r["ts"])


def intraday_candles(key, minutes=5):
    """Today's candles so far, oldest first."""
    return _rows(_get("intraday_candles", f"/v3/historical-candle/intraday/{_q(key)}/minutes/{minutes}"))


def historical_candles(key, unit, interval, start, end):
    """Candles from start to end (dates, both included), oldest first, split into requests Upstox accepts.
    Upstox adjusts past prices for splits and bonuses."""
    if unit not in _MAX_DAYS or unit == "short_minutes":
        raise ValueError(f"unit must be minutes, hours, days, weeks or months, not {unit}")
    span = _MAX_DAYS["short_minutes" if unit == "minutes" and interval <= 15 else unit]
    rows, lo = {}, start
    while lo <= end:
        hi = end if span is None else min(end, lo + timedelta(days=span - 1))
        data = _get("historical_candles", f"/v3/historical-candle/{_q(key)}/{unit}/{interval}/{hi}/{lo}")
        rows.update((r["ts"], r) for r in _rows(data))
        lo = hi + timedelta(days=1)
    return [rows[ts] for ts in sorted(rows)]


# ---- Market information --------------------------------------------------------------------------------------

def holidays():
    """This year's NSE/BSE holidays: date, description, holiday_type, closed_exchanges, open_exchanges."""
    return _get("holidays", "/v2/market/holidays")


def market_status(exchange="NSE"):
    """{"exchange", "status" (e.g. NORMAL_OPEN), "last_updated"}."""
    return _get("market_status", f"/v2/market/status/{exchange}")


def flows(who, data_type, interval="1D", start=None):
    """FII or DII buy/sell amounts (₹) per day ("1D", up to 30 days) or month ("1M"). Data from 1 Apr 2026."""
    if who not in ("fii", "dii"):
        raise ValueError("who must be fii or dii")
    params = {"data_type": data_type, "interval": interval, **({"from": start.isoformat()} if start else {})}
    return _get(who, f"/v2/market/{who}", params)


def charges(key, quantity, product, side, price):
    """Upstox's own charges for one order: total, brokerage, taxes (gst, stt, stamp_duty), other_charges.
    product: "I" intraday or "D" delivery; side: "BUY" or "SELL"."""
    data = _get("charges", "/v2/charges/brokerage", {"instrument_token": key, "quantity": quantity,
                                                       "product": product, "transaction_type": side, "price": price})
    return data["charges"]


def news(keys):
    """{instrument key: [{heading, summary, article_link, published_time}]}, newest page only.

    shortcut: first page of up to 100 items per 30 keys; add paging if a busy day ever fills it.
    """
    out = {}
    for batch in _batches(keys, 30):
        data = _get("news", "/v2/news", {"category": "instrument_keys", "instrument_keys": ",".join(batch),
                                         "page_size": 100}) or {}
        out.update(data)
    return out


def fundamentals(isin, kind, **params):
    """One fundamentals report by ISIN. kind: key-ratios, share-holdings, corporate-actions, income-statement,
    balance-sheet or cash-flow. Statements accept type=consolidated|standalone and time_period=yearly|quarterly."""
    if kind not in FUNDAMENTALS:
        raise ValueError(f"kind must be one of {FUNDAMENTALS}")
    return _get(kind, f"/v2/fundamentals/{_q(isin)}/{kind}", params or None)
