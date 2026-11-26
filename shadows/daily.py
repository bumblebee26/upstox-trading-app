"""The daily swing, long-term and benchmark shadows, after the intraday ones (16:10 IST job).

Every trading day: today's bar for each liquid Nifty 500 stock (daily history up to yesterday plus today's
quote), then each swing shadow (₹60,000), long-term shadow (₹1,00,000) and NIFTYBEES benchmark takes one step
on its paper ledger. Long-term fundamentals are fetched once a month, on the first trading day, and kept in
the state bucket. Last, every shadow (intraday ones included) is judged by its family's luck line
(shadows/families.py) and the table is saved for the app.

  python -m shadows.daily
"""
import json
import logging
from datetime import datetime, timedelta

from core import costs, storage, upstox
from shadows import families
from shadows import longterm as lt
from shadows import portfolio as pf
from shadows import run as intraday_run
from shadows import swing
from trader import messages, telegram, universe

log = logging.getLogger("upx")
LEDGERS = "shadows/ledgers.json"
SUMMARY = "shadows/summary-intraday.json"
FAMILIES = "shadows/families.json"
SWING_CAPITAL, LONG_CAPITAL = 60_000.0, 100_000.0
BENCH = "NIFTYBEES"
BENCHMARKS = {"B01-swing": SWING_CAPITAL, "B02-swing": SWING_CAPITAL, "B01-long": LONG_CAPITAL,
              "B02-long": LONG_CAPITAL}
KINDS = {"ratios": "key-ratios", "income": "income-statement", "cashflow": "cash-flow",
         "holdings": "share-holdings", "actions": "corporate-actions"}
NEWS_DAYS = 2


def _fundamentals(ux, sym, isin, month, store):
    """One stock's five reports, fetched once a month (about 2,500 calls for the Nifty 500, under the limiter).

    shortcut: one file per stock and month in the state bucket; the lakehouse (PR 10) can keep the history.
    """
    key = f"shadows/fundamentals/{month}/{sym}.json"
    saved = storage.get_json(key, store=store)
    if saved is not None:
        return saved
    out = {}
    for name, kind in KINDS.items():
        try:
            out[name] = ux.fundamentals(isin, kind)
        except (RuntimeError, upstox.UpstoxError) as err:
            log.warning("%s for %s failed: %s", kind, sym, err)
            return {}  # not cached: the next run asks again
    storage.put_json(key, out, store=store)
    return out


def _benchmark(name, led, day, bars, keys, charges):
    pool = "swing" if name.endswith("swing") else "long_term"
    pf.fill_and_value(led, day, bars, keys, charges, pool)
    if BENCH not in bars:
        return
    if name.startswith("B01") and not led.get("bought"):
        led["bought"] = True
        pf.order_buy(led, BENCH, amount=led["cash"], stop=0.0)
    if name.startswith("B02") and led.get("month") != day[:7]:
        led["month"] = day[:7]
        pf.order_buy(led, BENCH, amount=min(pf.sip_amount(led), led["cash"]), stop=0.0, top_up=True)


def _from_ledger(led):
    days, prev = {}, led["capital"]
    for d, v in led["equity"]:
        days[d] = round(v - prev, 2)
        prev = v
    return {"days": days, "trades": [c["net_rs"] for c in led["closed"]]}


def run_day(now=None, store=None, ux=upstox, tg=telegram, members=None, charges=costs.order,
            index_list=universe.index_list):
    now = now or datetime.now(intraday_run.IST).replace(tzinfo=None)
    if intraday_run.market_closed(now, ux):
        return {"skipped": "no trading today"}
    store = store or storage.backend()
    day, today = now.date(), now.date().isoformat()
    book = storage.get_json(LEDGERS, {"day": None, "ledgers": {}}, store=store)
    if book["day"] == today:
        return {"skipped": "already ran today"}  # a rerun would fill today's orders at today's open again
    members = universe.nifty500(store=store) if members is None else members
    ins = ux.instruments()
    keys = {s: ins["eq"][s]["key"] for s in list(members) + [BENCH] if s in ins["eq"]}
    start, yesterday = day - timedelta(days=400), day - timedelta(days=1)

    def history(key):
        try:
            return [d for d in ux.historical_candles(key, "days", 1, start, yesterday) if d["ts"][:10] < today]
        except (RuntimeError, upstox.UpstoxError) as err:
            log.warning("daily candles for %s failed: %s", key, err)
            return []

    quotes = ux.quotes(list(keys.values()))
    hist = {}
    for sym, key in keys.items():
        past, q = history(key), quotes.get(key)
        if not past or not q or not q.get("ohlc"):
            continue
        o = q["ohlc"]
        hist[sym] = past + [{"ts": f"{today}T00:00:00+05:30", "open": o["open"], "high": o["high"], "low": o["low"],
                             "close": q["last_price"], "volume": q.get("volume") or 0}]
    liquid = {}
    for sym, d in hist.items():
        base = universe.baseline_row(d[:-1])
        if sym != BENCH and base and base["avg_turnover_cr"] >= intraday_run.MIN_TURNOVER_CR \
                and base["prev_close"] >= intraday_run.MIN_PRICE:
            liquid[sym] = d
    bars = {s: d[-1] for s, d in hist.items()}
    priced = {s: d for s, d in hist.items() if s != BENCH}
    closes = {s: b["close"] for s, b in bars.items()}
    industries = {s: (members.get(s) or {}).get("industry") for s in liquid}
    idx = ins["index"].get("Nifty 50")
    nifty = history(idx) if idx else []
    cutoff = (now - timedelta(days=NEWS_DAYS)).timestamp() * 1000
    try:
        news_raw = ux.news([keys[s] for s in liquid]) if liquid else {}
    except (RuntimeError, upstox.UpstoxError) as err:
        log.warning("news failed: %s", err)
        news_raw = {}
    by_key = {v: k for k, v in keys.items()}
    news = {by_key[k] for k, items in news_raw.items() if k in by_key
            and any((i.get("published_time") or 0) >= cutoff for i in items)}

    priced = {}

    def charge(key, qty, pool, side, price):  # the same order in several shadows is priced once
        k = (key, qty, pool, side, price)
        if k not in priced:
            priced[k] = charges(key, qty, pool, side, price)
        return priced[k]

    led = book["ledgers"]
    week = f"{day.isocalendar()[0]}-{day.isocalendar()[1]:02d}"
    for sid in swing.STRATEGIES:
        swing.step(sid, led.setdefault(sid, pf.new(SWING_CAPITAL)), today, priced, keys, charge, nifty=nifty,
                   industries=industries, news=news, week=week, universe=liquid)

    due = [lid for lid in lt.STRATEGIES if lt.rebalance_due(lid, led.get(lid, {}), today)]
    data, index_members = {}, {}
    if any(lid not in lt.QUARTERLY for lid in due):
        for sym in liquid:
            isin = (members.get(sym) or {}).get("isin") or ins["eq"][sym].get("isin")
            if isin:
                data[sym] = _fundamentals(ux, sym, isin, today[:7], store)
        data = {s: d for s, d in data.items() if d.get("ratios")}
    for lid, name in (("L15", "niftynext50"), ("L16", "nifty50")):
        if lid in due:
            try:
                index_members[lid] = [s for s in index_list(name, store=store) if s in bars]
            except RuntimeError as err:
                log.warning("%s list unavailable, %s waits a day: %s", name, lid, err)
    for lid in lt.STRATEGIES:
        book_l = led.setdefault(lid, pf.new(LONG_CAPITAL))
        pf.fill_and_value(book_l, today, bars, keys, charge, "long_term")
        ready = index_members.get(lid) if lid in lt.QUARTERLY else data
        if lid in due and ready:  # no data today (an outage): keep the holdings and try again tomorrow
            picks = lt.targets(lid, data, liquid, today, index_members=index_members.get(lid), industries=industries)
            pf.rebalance(book_l, picks, lt.weight(lid, len(picks)), closes)
            book_l["month"] = today[:7]

    for name, capital in BENCHMARKS.items():
        _benchmark(name, led.setdefault(name, pf.new(capital)), today, bars, keys, charge)

    summary = storage.get_json(SUMMARY, {}, store=store)
    for name, v in (storage.get_json(f"shadows/intraday/{today}.json", {}, store=store).get("variants") or {}).items():
        s = summary.setdefault(name, {"days": {}, "trades": {}})
        s["days"][today] = v["net_rs"]
        s["trades"][today] = [t["net_rs"] for t in v["trades"]]
    storage.put_json(SUMMARY, summary, store=store)

    series = {n: {"days": s["days"], "trades": [t for ts in s["trades"].values() for t in ts]}
              for n, s in summary.items()}
    series.update({n: _from_ledger(v) for n, v in led.items()})
    fam = storage.get_json(FAMILIES, {"state": {}}, store=store)
    trading_days = sorted({d for s in series.values() for d in s["days"]})
    rows = families.judge(series, state=fam["state"], today=today, trading_days=trading_days)
    storage.put_json(FAMILIES, {"day": today, "rows": rows, "state": fam["state"]}, store=store)
    book["day"] = today
    storage.put_json(LEDGERS, book, store=store)  # last: it marks the day done

    gain = {n: pf.equity_now(v) - v["capital"] for n, v in led.items()}
    best_s = max(swing.STRATEGIES, key=gain.get)
    best_l = max(lt.STRATEGIES, key=gain.get)
    lines = [f"📈 Swing and long-term shadows · {day.day} {day:%b}",
             f"Best swing {best_s} {messages.inr(gain[best_s], sign=True)} · best long-term {best_l} "
             f"{messages.inr(gain[best_l], sign=True)} · NIFTYBEES held {messages.inr(gain['B01-long'], sign=True)}"]
    passed = [r["variant"] for r in rows if r["status"] == "passed"]
    above = [r["variant"] for r in rows if r["status"] == "above luck"]
    if passed or above:
        lines.append(" · ".join(([f"★ passed: {', '.join(passed)}"] if passed else []) +
                                ([f"above luck: {', '.join(above[:5])}"] if above else [])))
    tg.send("\n".join(lines))
    return {"swing": len(swing.STRATEGIES), "long_term": len(lt.STRATEGIES), "rebalanced": due,
            "stocks": len(liquid)}


if __name__ == "__main__":
    print(json.dumps(run_day()))
