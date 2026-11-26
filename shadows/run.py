"""The daily intraday shadow job (16:10 IST, after the close): every variant in the catalog on today's
1-minute candles of the liquid Nifty 500, with Upstox charges. Results go to the state bucket under
shadows/intraday/<day>.json. A01 and A02 replay the AI's real entries of the day (from its journal) with the
rule exits X1 and X3, to show whether the AI's exits add value. shadows/daily.py runs next.

  python -m shadows.run
"""
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone

from core import costs, journal, storage, upstox
from shadows import intraday as si
from shadows import sim
from trader import messages, telegram, universe

log = logging.getLogger("upx")
IST = timezone(timedelta(hours=5, minutes=30))
MIN_TURNOVER_CR, MIN_PRICE = 50.0, 50.0


AI_SPLITS = {"A01": "X1", "A02": "X3"}


def market_closed(now, ux):
    day = now.date().isoformat()
    return now.weekday() >= 5 or any(h.get("date") == day and h.get("holiday_type") == "TRADING_HOLIDAY"
                                     and "NSE" in (h.get("closed_exchanges") or []) for h in ux.holidays())


def ai_entries(day, store):
    """The AI's filled intraday entries of `day` as signals: the next minute's open after the real fill, the
    stop it reviewed."""
    local = tempfile.mkdtemp()
    journal.restore(day, base_dir=local, mirror=store)
    events = journal.read(day, base_dir=local)
    reviews = {e["review_id"]: e for e in events if e["event"] == "review"}
    out = []
    for f in events:
        r = reviews.get(f.get("review_id"))
        if f["event"] != "fill" or not r or not f.get("at"):
            continue
        start = datetime.fromisoformat(f["at"]).replace(second=0) + timedelta(minutes=1)
        out.append(sim.Signal(r["symbol"], r["key"], r["side"], start.isoformat()[:16], float(r["stop"])))
    return out


def run_day(now=None, store=None, ux=upstox, tg=telegram, members=None, charges=costs.order):
    now = now or datetime.now(IST).replace(tzinfo=None)
    day = now.date()
    if market_closed(now, ux):
        return {"skipped": "no trading today"}
    store = store or storage.backend()
    members = universe.nifty500(store=store) if members is None else members
    ins = ux.instruments()
    start, yesterday = day - timedelta(days=400), day - timedelta(days=1)

    def history(key):
        try:
            return [d for d in ux.historical_candles(key, "days", 1, start, yesterday) if d["ts"][:10] < day.isoformat()]
        except (RuntimeError, upstox.UpstoxError) as err:
            log.warning("daily candles for %s failed: %s", key, err)
            return []

    def today_1m(key):
        try:
            return ux.intraday_candles(key, 1)
        except (RuntimeError, upstox.UpstoxError) as err:
            log.warning("1-minute candles for %s failed: %s", key, err)
            return []

    # The universe: yesterday's guardrails (price, average turnover), as for the live screen.
    daily, liquid = {}, []
    for sym in members:
        info = ins["eq"].get(sym)
        if not info:
            continue
        d = history(info["key"])
        base = universe.baseline_row(d)
        if base and base["avg_turnover_cr"] >= MIN_TURNOVER_CR and base["prev_close"] >= MIN_PRICE:
            daily[sym], liquid = d, liquid + [sym]

    idx = ins["index"]
    nifty_daily = history(idx["Nifty 50"]) if "Nifty 50" in idx else []
    closes = [d["close"] for d in nifty_daily]
    ema200 = (sum(closes[-200:]) / 200) if len(closes) >= 200 else None  # shortcut: a simple 200-day average
    above = closes[-1] > ema200 if ema200 else None
    vix_daily = history(idx["India VIX"]) if "India VIX" in idx else []
    vix_prev = vix_daily[-1]["close"] if vix_daily else None
    nifty_one = today_1m(idx["Nifty 50"]) if "Nifty 50" in idx else []
    sector_one = {}
    contexts, candles = [], {}
    for sym in liquid:
        key = ins["eq"][sym]["key"]
        one = today_1m(key)
        if not one:
            continue
        sector = universe.sector_index((members.get(sym) or {}).get("industry"))
        if sector not in sector_one:
            sector_one[sector] = today_1m(idx[sector]) if sector in idx else []
        c = si.build_context(sym, key, one, daily[sym], nifty_one=nifty_one, sector_one=sector_one[sector],
                             vix_prev=vix_prev, nifty_above_200=above)
        contexts.append(c)
        candles[key] = one
    five_vwap = {c.key: {e[11:16]: v for e, v in zip(c.end, c.vwap)} for c in contexts}

    priced = {}

    def charge(key, qty, side, price):  # the same order in several variants is priced once
        k = (key, qty, side, price)
        if k not in priced:
            priced[k] = charges(key, qty, "intraday", side, price)
        return priced[k]

    results, total, found = {}, 0, {}
    for name, (rule, exit_rule, overlay) in si.VARIANTS.items():
        if (rule, overlay) not in found:  # exit variants share their entry's signals
            found[(rule, overlay)] = [s for c in contexts for s in si.signals(c, rule, overlay)]
        sigs = found[(rule, overlay)]
        trades = sim.run_day(sigs, candles, exit_rule, charge, five_vwap)
        results[name] = {"trades": trades, "net_rs": round(sum(t["net_rs"] for t in trades), 2),
                         "wins": sum(1 for t in trades if t["net_rs"] > 0)}
        total += len(trades)
    ai = ai_entries(day.isoformat(), store)
    for sig in ai:
        if sig.key not in candles:  # the AI may trade a stock outside the shadows' universe
            candles[sig.key] = today_1m(sig.key)
    for name, exit_rule in AI_SPLITS.items():
        trades = sim.run_day(ai, candles, exit_rule, charge, five_vwap)
        results[name] = {"trades": trades, "net_rs": round(sum(t["net_rs"] for t in trades), 2),
                         "wins": sum(1 for t in trades if t["net_rs"] > 0)}
        total += len(trades)
    storage.put_json(f"shadows/intraday/{day.isoformat()}.json",
                     {"day": day.isoformat(), "universe": liquid, "vix_prev": vix_prev, "nifty_above_200": above,
                      "variants": results}, store=store)
    ranked = sorted(results.items(), key=lambda kv: -kv[1]["net_rs"])
    traded = [(n, r) for n, r in ranked if r["trades"]]
    lines = [f"🧪 Shadows · {day.day} {day:%b} · {len(results)} variants · {total} paper trades · {len(liquid)} stocks"]
    if traded:
        best, worst = traded[0], traded[-1]
        lines.append(f"Best {best[0]} {messages.inr(best[1]['net_rs'], sign=True)} · "
                     f"worst {worst[0]} {messages.inr(worst[1]['net_rs'], sign=True)} (one day says little)")
    tg.send("\n".join(lines))
    return {"trades": total, "variants": len(results), "universe": len(liquid)}


if __name__ == "__main__":
    print(json.dumps(run_day()))
