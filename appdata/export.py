"""The app's data, built as the last step of the Lakehouse job (after the pipelines), into the upx-app bucket:

  app/data/desk.json    the datasets (one per appdata/queries/*.sql file), the market values, the pools' holdings
                        and limits (from the trader's state bucket) and the last day's per-trade candle charts
  app/data/stocks.json  every NSE stock for search and Explore (rebuilt once a day), with the index lists
  history/markets/      the market values book (today and the previous saved day) and a copy for each day
  history/indices/      the index lists (refreshed once a month)

A query that fails keeps its previous rows (and is listed in "failed"), so one late table never blanks the app.
Usage: python -m appdata.export   (needs UPX_APP_BUCKET, UPX_STATE_BUCKET, DATABRICKS_HOST, DATABRICKS_TOKEN)
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from appdata import markets, sql, state, stocks
from core import http, storage, upstox

IST = timezone(timedelta(hours=5, minutes=30))
QUERIES = Path(__file__).parent / "queries"
DESK, STOCKS = "app/data/desk.json", "app/data/stocks.json"
BOOK, INDICES = "history/markets/book.json", "history/indices/book.json"


def run_queries(previous, query=sql.query, folder=QUERIES):
    """({dataset: {rows}}, [failed]) for every .sql file in folder."""
    old = (previous or {}).get("datasets") or {}
    datasets, failed = {}, []
    for f in sorted(Path(folder).glob("*.sql")):
        try:
            datasets[f.stem] = {"rows": query(f.read_text())}
        except Exception as err:  # noqa: BLE001 - keep the last good rows for this one dataset
            print(f"dataset {f.stem} failed: {err}")
            failed.append(f.stem)
            if f.stem in old:
                datasets[f.stem] = old[f.stem]
    return datasets, failed


def stock_file(day, app, fetch):
    """Rebuild stocks.json once a day (the instrument file changes daily; index lists monthly)."""
    have = storage.get_json(STOCKS, store=app)
    if have and have.get("day") == day.isoformat():
        return have.get("failed", [])
    book = stocks.index_lists(storage.get_json(INDICES, store=app), day.strftime("%Y-%m"), fetch=fetch)
    storage.put_json(INDICES, book, store=app)
    gz = fetch("GET", upstox.INSTRUMENTS_URL, timeout=60)
    eq = upstox.parse_instruments(gz)["eq"]
    nse = book["lists"]
    lists = dict(list(nse.items())[:1] + [("Sensex", stocks.sensex(nse))] + list(nse.items())[1:])  # chip order: Nifty 50, Sensex, ...
    storage.put_json(STOCKS, {"day": day.isoformat(), "stocks": stocks.stock_list(eq, lists, stocks.fo_lots(gz, set(eq))),
                              "indices": {k: [r["symbol"] for r in v] for k, v in lists.items()},
                              "failed": book["failed"]}, store=app)
    return book["failed"]


def build(day, app, query=sql.query, fetch=http.request, market_values=markets.fetch_all, trader=None,
          candles=state.upstox_candles):
    previous = storage.get_json(DESK, store=app)
    datasets, failed = run_queries(previous, query=query)
    closes = {r["symbol"]: r.get("close") for r in (datasets.get("eq_day") or {}).get("rows", []) if "symbol" in r}
    try:  # the pools' holdings and limits, read from the trader's state bucket (read-only here)
        pools = state.pools(trader or storage.backend(), closes)
    except Exception as err:  # noqa: BLE001 - keep the last good copy
        print(f"pools failed: {err}")
        failed.append("pools")
        pools = (previous or {}).get("pools") or {}
    charts = state.trade_charts((datasets.get("decisions") or {}).get("rows", []), candles)
    vals, missing = market_values()
    book = markets.update(storage.get_json(BOOK, store=app), vals)
    storage.put_json(BOOK, book, store=app)
    storage.put_json(f"history/markets/{day.isoformat()}.json", vals, store=app)
    try:
        index_failed = stock_file(day, app, fetch)
    except Exception as err:  # noqa: BLE001 - the stock list keeps yesterday's file
        print(f"stock list failed: {err}")
        index_failed = ["stock list"]
    failed += [f"markets: {m}" for m in missing] + [f"index: {i}" for i in index_failed]
    payload = {"updated_at": datetime.now(IST).isoformat(timespec="seconds"), "datasets": datasets,
               "markets": markets.rows(book), "pools": pools, "charts": charts, "failed": failed}
    storage.put_json(DESK, payload, store=app)
    return {"datasets": len(datasets), "markets": len(payload["markets"]), "failed": failed}


if __name__ == "__main__":
    print(json.dumps(build(datetime.now(IST).date(), storage.S3(os.environ["UPX_APP_BUCKET"]))))
