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


def main():
    m = upstox.instruments()
    stock = m["eq"]["RELIANCE"]
    key, isin = stock["key"], stock["isin"]
    nifty = m["index"].get("Nifty 50")
    today = date.today()
    checks = {
        "instruments": lambda: f"{len(m['eq'])} stocks, {len(m['index'])} indices",
        "quotes": lambda: upstox.quotes([key, nifty])[key]["last_price"],
        "intraday_candles": lambda: f"{len(upstox.intraday_candles(key))} candles today",
        "historical minutes": lambda: len(upstox.historical_candles(key, "minutes", 5, today - timedelta(days=7), today)),
        "historical days": lambda: len(upstox.historical_candles(nifty, "days", 1, today - timedelta(days=30), today)),
        "holidays": lambda: f"{len(upstox.holidays())} this year",
        "market_status": lambda: upstox.market_status()["status"],
        "fii": lambda: len(upstox.flows("fii", "NSE_EQ|CASH")),
        "dii": lambda: len(upstox.flows("dii", "NSE_EQ|CASH")),
        "charges": lambda: upstox.charges(key, 10, "I", "BUY", 1000),
        "charges delivery sell": lambda: upstox.charges(key, 10, "D", "SELL", 1000),
        "news": lambda: f"{len(upstox.news([key]).get(key, []))} items",
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
