"""The screen: every NSE stock's quote (6 Upstox calls) through the guardrails, then a ranked shortlist.

Core universe (Nifty 500): kept if it is liquid (₹50 crore+ a day on average), priced ₹50+, with a tight
bid/ask spread and room to its circuit limits. Any other NSE stock joins only with fresh news or a 3%+ move,
and enough money traded today. Ranking favours unusual volume, a move from the open, a gap and fresh news.
"""
from datetime import datetime

MIN_PRICE = 50.0
MIN_TURNOVER_CR = 50.0     # average a day, crore rupees
MAX_SPREAD_PCT = 0.10
MIN_CIRCUIT_ROOM_PCT = 2.0
BIG_MOVE_PCT = 3.0
SESSION_MIN = 375          # 09:15 to 15:30


def _elapsed(now: datetime):
    """Share of the session gone, at least 2% so the first minutes don't inflate relative volume.

    shortcut: assumes volume builds evenly through the day (it is heavier at the open and close); use each
    stock's same-time volume from the minute history once the lakehouse has it.
    """
    minutes = (now.hour * 60 + now.minute) - (9 * 60 + 15)
    return min(1.0, max(0.02, minutes / SESSION_MIN))


def _spread_pct(q):
    buy, sell = (q.get("depth") or {}).get("buy") or [], (q.get("depth") or {}).get("sell") or []
    bid, ask = (buy[0].get("price") if buy else 0), (sell[0].get("price") if sell else 0)
    if not bid or not ask:
        return None
    return (ask - bid) / ((ask + bid) / 2) * 100


def shortlist(quotes, baseline, core, news, now, top=20):
    """quotes: {symbol: Upstox full quote}; baseline: {symbol: baseline_row}; core: Nifty 500 symbols;
    news: symbols with fresh news. Returns up to `top` rows, best first, each with the reasons."""
    f = _elapsed(now)
    rows = []
    for sym, q in quotes.items():
        price = q.get("last_price") or 0
        prev = price - (q.get("net_change") or 0)
        open_ = (q.get("ohlc") or {}).get("open") or price
        spread = _spread_pct(q)
        up, low = q.get("upper_circuit_limit"), q.get("lower_circuit_limit")
        if price < MIN_PRICE or spread is None or spread > MAX_SPREAD_PCT:
            continue
        if not up or not low or (up / price - 1) * 100 < MIN_CIRCUIT_ROOM_PCT or (1 - low / price) * 100 < MIN_CIRCUIT_ROOM_PCT:
            continue
        change = (price / prev - 1) * 100 if prev else 0.0
        base = baseline.get(sym) or {}
        has_news = sym in news
        if sym in core:
            if (base.get("avg_turnover_cr") or 0) < MIN_TURNOVER_CR:
                continue
        else:
            today_cr = (q.get("volume") or 0) * (q.get("average_price") or price) / 1e7
            if not (has_news or abs(change) >= BIG_MOVE_PCT) or today_cr < MIN_TURNOVER_CR * f:
                continue
        rvol = (q.get("volume") or 0) / (base["avg_volume"] * f) if base.get("avg_volume") else None
        move = (price / open_ - 1) * 100
        gap = (open_ / prev - 1) * 100 if prev else 0.0
        score = min(rvol or 0, 5) + min(abs(move), 5) + 0.5 * min(abs(gap), 5) + (2 if has_news else 0) \
            + (1 if abs(change) >= BIG_MOVE_PCT else 0)
        why = [w for w, on in ((f"{rvol:.1f}x volume" if rvol else "", rvol and rvol >= 1.5),
                               (f"{move:+.1f}% from open", abs(move) >= 1), (f"gap {gap:+.1f}%", abs(gap) >= 1),
                               ("news", has_news), ("outside Nifty 500", sym not in core)) if on]
        rows.append({"symbol": sym, "price": price, "change_pct": round(change, 2), "move_pct": round(move, 2),
                     "gap_pct": round(gap, 2), "rvol": round(rvol, 2) if rvol else None,
                     "spread_pct": round(spread, 3), "score": round(score, 2), "why": why})
    return sorted(rows, key=lambda r: -r["score"])[:top]
