"""For the app: the pools' holdings and code limits (from the trader's saved state), and a 5-minute candle chart
of each trade the intraday AI reviewed on the last trading day, with what a skipped idea would have done.
"""

from datetime import date, time

from core import storage, upstox
from trader import risk

POOLS = ("intraday", "swing", "long_term")


def _plain(v):
    if isinstance(v, tuple) and all(isinstance(x, time) for x in v):
        return "–".join(x.strftime("%H:%M") for x in v)
    return v


def pools(store, closes, limits=risk.POOLS):
    """{pool: {auto, positions, limits}} for each pool with saved state; positions carry today's close."""
    out = {}
    for pool in POOLS:
        st = storage.get_json(f"state/{pool}.json", store=store)
        if not st:
            continue
        held = [{"symbol": sym, "qty": p.get("qty"), "avg": p.get("fill_price"), "now": closes.get(sym),
                 "stop": p.get("stop"), "target": p.get("target"), "since": (p.get("opened_at") or "")[:10]}
                for sym, p in sorted((st.get("positions") or {}).items())]
        out[pool] = {"auto": bool(st.get("auto")), "positions": held,
                     "limits": {k: _plain(v) for k, v in (limits.get(pool) or {}).items()}}
    return out


def first_hit(candles, side, stop, target, after):
    """Which the price reached first after the review: "stop", "target" or "neither". A bar that touches both
    counts as the stop (the cautious reading)."""
    for c in candles:
        if c["ts"][:19] < after[:19]:
            continue
        hit_stop = c["low"] <= stop if side == "BUY" else c["high"] >= stop
        hit_target = c["high"] >= target if side == "BUY" else c["low"] <= target
        if hit_stop:
            return "stop"
        if hit_target:
            return "target"
    return "neither"


def trade_charts(rows, candles):
    """[{review_id, symbol, side, entry, stop, target, at, skipped, would_have, candles}] for the intraday reviews
    of the last trading day in rows; candles(symbol, day) gives that day's 5-minute bars."""
    reviews = [r for r in rows if r.get("event") == "review" and r.get("pool") == "intraday"]
    if not reviews:
        return []
    day = max(r["trade_date"] for r in reviews)
    skipped = {r.get("review_id") for r in rows if r.get("event") in ("skipped", "not_approved")}
    out, bars = [], {}
    for r in (x for x in reviews if x["trade_date"] == day and x.get("entry")):
        try:
            if r["symbol"] not in bars:
                bars[r["symbol"]] = candles(r["symbol"], day)
        except Exception:  # noqa: BLE001 - one stock's candles failing leaves the other charts
            continue
        cs = bars[r["symbol"]]
        out.append({"review_id": r["review_id"], "symbol": r["symbol"], "side": r.get("side") or "BUY",
                    "entry": r["entry"], "stop": r["stop"], "target": r["target"], "at": (r.get("at_ist") or "")[11:16],
                    "skipped": r["review_id"] in skipped,
                    "would_have": first_hit(cs, r.get("side") or "BUY", r["stop"], r["target"], r.get("at_ist") or day),
                    "candles": [[c["ts"][11:16], c["low"], c["high"], c.get("open"), c.get("close")] for c in cs]})
    return out


def upstox_candles(symbol, day):
    """5-minute bars of one NSE stock for one day, from Upstox."""
    key, d = upstox.instruments()["eq"][symbol]["key"], date.fromisoformat(day)
    return upstox.historical_candles(key, "minutes", 5, d, d)
