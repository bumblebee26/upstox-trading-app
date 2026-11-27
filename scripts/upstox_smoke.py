"""Call every Upstox endpoint this repo uses once, with the real token, and report which ones work.

The Analytics token is documented for market data; this shows whether charges, news and fundamentals
accept it too. Run by the manual "Upstox check" GitHub job, or locally with UPSTOX_TOKEN set.
Usage: python scripts/upstox_smoke.py   (exit code 1 if any check fails)
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import upstox  # noqa: E402
from trader import facts  # noqa: E402


def _ends(reply):
    """How many rows came back, and the first and last (to see their order and fields)."""
    rows = next(iter(reply.values()), []) if isinstance(reply, dict) else reply
    return f"{len(rows)} rows; first {rows[0] if rows else None}; last {rows[-1] if rows else None}"


def _packet(key, nifty, today):
    daily = upstox.historical_candles(key, "days", 1, today - timedelta(days=400), today - timedelta(days=1))
    quote = upstox.quotes([key])[key]
    p = facts.packet("RELIANCE", upstox.intraday_candles(key, 1), daily, quote,
                     nifty_1m=upstox.intraday_candles(nifty, 1))
    return {"price": p["price"], "vwap": p["day"]["vwap"], "5m": {k: p["tf"]["5m"][k] for k in ("rsi14", "adx")},
            "daily": {k: p["tf"]["daily"][k] for k in ("ema200", "rsi14", "candles")}, "levels": p["levels"]["pivots"],
            "spread_pct": p["quote"]["spread_pct"], "size_chars": len(str(p))}


def main():
    m = upstox.instruments()
    stock = m["eq"]["RELIANCE"]
    key, isin = stock["key"], stock["isin"]
    nifty = m["index"].get("Nifty 50")
    today = date.today()
    checks = {
        "instruments": lambda: f"{len(m['eq'])} stocks, {len(m['index'])} indices",
        "nse indices": lambda: sorted(m["index"]),
        "quotes": lambda: upstox.quotes([key, nifty])[key]["last_price"],
        "intraday_candles": lambda: f"{len(upstox.intraday_candles(key))} candles today",
        "historical minutes": lambda: len(upstox.historical_candles(key, "minutes", 5, today - timedelta(days=7), today)),
        "historical days": lambda: len(upstox.historical_candles(nifty, "days", 1, today - timedelta(days=30), today)),
        "holidays": lambda: f"{len(upstox.holidays())} this year",
        "market_status": lambda: upstox.market_status()["status"],
        "fii": lambda: _ends(upstox.flows("fii", "NSE_EQ|CASH")),
        "dii": lambda: len(upstox.flows("dii", "NSE_EQ|CASH")),
        "charges": lambda: upstox.charges(key, 10, "I", "BUY", 1000),
        "charges delivery sell": lambda: upstox.charges(key, 10, "D", "SELL", 1000),
        "news": lambda: f"{len(upstox.news([key]).get(key, []))} items",
        "facts packet": lambda: _packet(key, nifty, today),
        **{kind: (lambda k=kind: "ok" if upstox.fundamentals(isin, k) is not None else "empty")
           for kind in upstox.FUNDAMENTALS},
    }
    failed = 0
    for name, check in checks.items():
        try:
            print(f"PASS {name}: {check()}")
        except Exception as err:  # report every endpoint, even after one fails
            failed += 1
            print(f"FAIL {name}: {str(err).splitlines()[0][:200]}")
    print(f"calls made: {upstox._limiter.counts}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
