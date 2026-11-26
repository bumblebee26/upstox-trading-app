"""The intraday shadow simulator: one strategy's paper day, run on 1-minute candles after the close.

Rules (docs/STRATEGIES.md section 1): fill at the next 1-minute open after the 5-minute signal plus 0.05%
slippage; stops checked on every 1-minute candle (stop first if a candle touches stop and target); exits other
than a target are slipped too; everything closes at the 15:10 open; ₹400 risk a trade on a ₹40,000 pool, at
most 30% of the pool as margin (5x), 5 open and 10 trades a day, one entry per stock; Upstox charges.

shortcut: shadows ignore the daily loss limit and cool-off of the real gate; they compare entries and exits,
not the day's brakes. Add them if a variant ever comes close to the pass bar.
"""
from dataclasses import dataclass

CAPITAL = 40_000.0
RISK_RS = 400.0
LEVERAGE = 5.0
MAX_POSITION_PCT = 30.0
MAX_OPEN = 5
MAX_TRADES = 10
SLIPPAGE = 0.0005
SQUARE_OFF = "15:10"
TIME_STOP_MIN = 60


@dataclass
class Signal:
    symbol: str
    key: str
    side: str            # BUY or SELL
    signal_time: str     # end of the 5-minute bar, "YYYY-MM-DDTHH:MM"
    stop: float
    target: float = None  # None: the exit rule sets it (2R or 1.5R)


def _slip(price, side):
    return round(price * (1 + SLIPPAGE) if side == "BUY" else price * (1 - SLIPPAGE), 2)


def _minutes(ts):
    return int(ts[11:13]) * 60 + int(ts[14:16])


def simulate_trade(sig, candles, exit_rule, five_vwap=None):
    """Walk one trade through the day's 1-minute candles. Returns the trade or None (no fill, or the fill is
    already past the stop). five_vwap: {"HH:MM" bar end: vwap} for exit X7."""
    long = sig.side == "BUY"
    after = [c for c in candles if c["ts"][:16] >= sig.signal_time]
    if not after or after[0]["ts"][11:16] >= SQUARE_OFF:
        return None
    entry = _slip(after[0]["open"], "BUY" if long else "SELL")
    risk = (entry - sig.stop) if long else (sig.stop - entry)
    if risk <= 0:
        return None
    target = sig.target
    if target is None and exit_rule not in ("X3", "X6", "X7"):
        target = entry + (1.5 if exit_rule == "X2" else 2.0) * risk * (1 if long else -1)
    stop, best, reason = sig.stop, entry, "stop"
    entry_min = _minutes(after[0]["ts"])
    for c in after:
        hhmm = c["ts"][11:16]
        if hhmm >= SQUARE_OFF:
            return _done(sig, after[0], entry, c, _slip(c["open"], "SELL" if long else "BUY"), "square_off", risk)
        if exit_rule == "X5" and _minutes(c["ts"]) - entry_min >= TIME_STOP_MIN:
            return _done(sig, after[0], entry, c, _slip(c["open"], "SELL" if long else "BUY"), "time", risk)
        hit_stop = c["low"] <= stop if long else c["high"] >= stop
        if hit_stop:
            price = min(stop, c["open"]) if long else max(stop, c["open"])
            return _done(sig, after[0], entry, c, _slip(price, "SELL" if long else "BUY"), reason, risk)
        if target is not None and (c["high"] >= target if long else c["low"] <= target):
            price = max(target, c["open"]) if long else min(target, c["open"])
            return _done(sig, after[0], entry, c, round(price, 2), "target", risk)
        best = max(best, c["high"]) if long else min(best, c["low"])
        moved = (best - entry) if long else (entry - best)
        if exit_rule == "X3" and moved >= risk:
            new = best - risk if long else best + risk
            if (new > stop) if long else (new < stop):
                stop, reason = new, "trail"
        if exit_rule == "X4" and moved >= risk and ((stop < entry) if long else (stop > entry)):
            stop, reason = entry, "breakeven"
        if exit_rule == "X7" and five_vwap and (_minutes(c["ts"]) + 1 - 555) % 5 == 0:  # the last minute of a 5-minute bar
            h, mi = divmod(_minutes(c["ts"]) + 1, 60)
            vwap = five_vwap.get(f"{h:02d}:{mi:02d}")
            if vwap is not None and ((c["close"] < vwap) if long else (c["close"] > vwap)):
                nxt = next((x for x in after if x["ts"] > c["ts"]), None)
                if nxt is not None and nxt["ts"][11:16] < SQUARE_OFF:
                    return _done(sig, after[0], entry, nxt, _slip(nxt["open"], "SELL" if long else "BUY"), "vwap",
                                 risk)
    last = after[-1]
    return _done(sig, after[0], entry, last, _slip(last["close"], "SELL" if long else "BUY"), "close", risk)


def _done(sig, fill_candle, entry, exit_candle, exit_price, reason, risk):
    return {"symbol": sig.symbol, "key": sig.key, "side": sig.side, "entry_time": fill_candle["ts"][:16],
            "entry": entry, "exit_time": exit_candle["ts"][:16], "exit": exit_price, "exit_reason": reason,
            "risk_per_share": round(risk, 4)}


def run_day(signals, candles_by_key, exit_rule, charges, five_vwap):
    """One strategy's day: take signals in time order within the caps, size, simulate, and cost each trade.
    charges(key, qty, side, price) -> rupees or None (then the trade is skipped, as for the real pools)."""
    trades, open_until, used = [], [], set()  # open_until: (exit time, margin) of positions still open
    for sig in sorted(signals, key=lambda s: s.signal_time):
        if sig.symbol in used or len(trades) >= MAX_TRADES:
            continue
        open_until = [(t, mg) for t, mg in open_until if t > sig.signal_time]
        if len(open_until) >= MAX_OPEN:
            continue
        t = simulate_trade(sig, candles_by_key.get(sig.key) or [], exit_rule, (five_vwap or {}).get(sig.key))
        if t is None:
            continue
        free = CAPITAL - sum(mg for _, mg in open_until)
        qty = int(min(RISK_RS / t["risk_per_share"], CAPITAL * MAX_POSITION_PCT / 100 * LEVERAGE / t["entry"],
                      free * LEVERAGE / t["entry"]))
        if qty < 1:
            continue
        close_side = "SELL" if sig.side == "BUY" else "BUY"
        a, b = charges(sig.key, qty, sig.side, t["entry"]), charges(sig.key, qty, close_side, t["exit"])
        if a is None or b is None:
            continue
        gross = (t["exit"] - t["entry"]) * qty * (1 if sig.side == "BUY" else -1)
        t.update(qty=qty, charges_rs=round(a + b, 2), net_rs=round(gross - a - b, 2),
                 r=round((gross - a - b) / (t["risk_per_share"] * qty), 2))
        trades.append(t)
        used.add(sig.symbol)
        open_until.append((t["exit_time"], qty * t["entry"] / LEVERAGE))
    return trades
