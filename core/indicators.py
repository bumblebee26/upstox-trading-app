"""Indicators and price levels, standard library only. Code does all the maths, so the AI never has to.

Candles are dicts with ts, open, high, low, close, volume, oldest first (as core/upstox.py returns them).
A function returns None when there aren't enough candles for an honest answer.
"""
import math


def _r(x, nd=2):
    return None if x is None else round(x, nd)


# ---- Moving averages and oscillators ---------------------------------------------------------------------

def ema(values, n):
    """Exponential moving average, seeded with the simple average of the first n values."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def last_ema(values, n):
    return _r(ema(values, n)[-1]) if values else None


def rsi(closes, n=14):
    """Wilder's RSI of the last close (0-100)."""
    if len(closes) <= n:
        return None
    gains = [max(0.0, b - a) for a, b in zip(closes, closes[1:])]
    losses = [max(0.0, a - b) for a, b in zip(closes, closes[1:])]
    g, l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for gi, li in zip(gains[n:], losses[n:]):
        g, l = (g * (n - 1) + gi) / n, (l * (n - 1) + li) / n
    if l == 0:
        return 100.0
    return _r(100 - 100 / (1 + g / l))


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal - 1:
        return None
    f, s = ema(closes, fast), ema(closes, slow)
    line = [a - b for a, b in zip(f, s) if a is not None and b is not None]
    sig = ema(line, signal)[-1]
    return {"macd": _r(line[-1]), "signal": _r(sig), "hist": _r(line[-1] - sig)}


def bollinger(closes, n=20, k=2.0):
    if len(closes) < n:
        return None
    window = closes[-n:]
    mid = sum(window) / n
    sd = math.sqrt(sum((x - mid) ** 2 for x in window) / n)
    return {"mid": _r(mid), "upper": _r(mid + k * sd), "lower": _r(mid - k * sd),
            "width_pct": _r(2 * k * sd / mid * 100 if mid else 0.0)}


# ---- Range and trend -------------------------------------------------------------------------------------

def _true_ranges(candles):
    return [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
            for p, c in zip(candles, candles[1:])]


def _wilder(values, n):
    if len(values) < n:
        return []
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append((out[-1] * (n - 1) + v) / n)
    return out


def atr(candles, n=14):
    s = _wilder(_true_ranges(candles), n)
    return _r(s[-1]) if s else None


def adx(candles, n=14):
    """Trend strength (ADX) with +DI and -DI."""
    if len(candles) < 2 * n + 1:
        return None
    plus = [max(0.0, c["high"] - p["high"]) if c["high"] - p["high"] > p["low"] - c["low"] else 0.0
            for p, c in zip(candles, candles[1:])]
    minus = [max(0.0, p["low"] - c["low"]) if p["low"] - c["low"] > c["high"] - p["high"] else 0.0
             for p, c in zip(candles, candles[1:])]
    tr, pdm, mdm = _wilder(_true_ranges(candles), n), _wilder(plus, n), _wilder(minus, n)
    pdi = [100 * a / t if t else 0.0 for a, t in zip(pdm, tr)]
    mdi = [100 * a / t if t else 0.0 for a, t in zip(mdm, tr)]
    dx = [100 * abs(a - b) / (a + b) if a + b else 0.0 for a, b in zip(pdi, mdi)]
    return {"adx": _r(_wilder(dx, n)[-1]), "plus_di": _r(pdi[-1]), "minus_di": _r(mdi[-1])}


def supertrend(candles, n=10, mult=3.0):
    """Supertrend line and direction ("up" or "down")."""
    if len(candles) < n + 2:
        return None
    trs = _true_ranges(candles)
    atrs = _wilder(trs, n)
    up = down = None
    direction = "up"
    for i, a in enumerate(atrs):
        c = candles[i + n]  # atrs[i] covers candles up to index i + n
        mid = (c["high"] + c["low"]) / 2
        basic_up, basic_down = mid + mult * a, mid - mult * a
        prev_close = candles[i + n - 1]["close"]
        up = basic_up if up is None or basic_up < up or prev_close > up else up
        down = basic_down if down is None or basic_down > down or prev_close < down else down
        if c["close"] > up:
            direction = "up"
        elif c["close"] < down:
            direction = "down"
    return {"direction": direction, "line": _r(down if direction == "up" else up)}


# ---- Intraday --------------------------------------------------------------------------------------------

def vwap(candles):
    """Today's volume-weighted average price, with bands 1 and 2 standard deviations away."""
    vol = sum(c["volume"] for c in candles)
    if not vol:
        return None
    typ = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    v = sum(t * c["volume"] for t, c in zip(typ, candles)) / vol
    sd = math.sqrt(sum(c["volume"] * (t - v) ** 2 for t, c in zip(typ, candles)) / vol)
    return {"vwap": _r(v), "upper1": _r(v + sd), "lower1": _r(v - sd), "upper2": _r(v + 2 * sd),
            "lower2": _r(v - 2 * sd)}


def resample(candles, minutes):
    """Merge 1-minute candles into `minutes`-minute candles aligned to 09:15. Each bar is stamped with its
    slot's start time, even if the slot's first minute had no trade (Upstox leaves such minutes out)."""
    out = {}
    for c in candles:
        slot = _minute_of_session(c) // minutes
        b = out.get(slot)
        if b is None:
            h, m = divmod(9 * 60 + 15 + slot * minutes, 60)
            out[slot] = dict(c, ts=f"{c['ts'][:11]}{h:02d}:{m:02d}{c['ts'][16:]}")
        else:
            b.update(high=max(b["high"], c["high"]), low=min(b["low"], c["low"]), close=c["close"],
                     volume=b["volume"] + c["volume"])
    return [out[k] for k in sorted(out)]


def _minute_of_session(c):
    return int(c["ts"][11:13]) * 60 + int(c["ts"][14:16]) - (9 * 60 + 15)


def opening_range(candles_1m, minutes):
    """High and low of the first `minutes` minutes after the 09:15 open."""
    first = [c for c in candles_1m if 0 <= _minute_of_session(c) < minutes]
    if not first:
        return None
    return {"high": max(c["high"] for c in first), "low": min(c["low"] for c in first)}


def relative_volume(now_volume, same_time_history):
    """Volume so far against the average volume by the same time on earlier days."""
    if not same_time_history:
        return None
    avg = sum(same_time_history) / len(same_time_history)
    return _r(now_volume / avg) if avg else None


# ---- Levels ----------------------------------------------------------------------------------------------

def pivots(high, low, close):
    pp = (high + low + close) / 3
    return {"pp": _r(pp), "r1": _r(2 * pp - low), "s1": _r(2 * pp - high), "r2": _r(pp + high - low),
            "s2": _r(pp - high + low)}


def camarilla(high, low, close):
    r = high - low
    return {"h3": _r(close + r * 1.1 / 4), "l3": _r(close - r * 1.1 / 4), "h4": _r(close + r * 1.1 / 2),
            "l4": _r(close - r * 1.1 / 2)}


def round_levels(price):
    """The round numbers just below and above the price (the step grows with the price)."""
    step = 5 if price < 100 else 50 if price < 1000 else 100 if price < 5000 else 500
    below = math.floor(price / step) * step
    return [below, below + step]


def value_area(candles_1m, share=0.70):
    """Point of control and value area from 1-minute candles.

    shortcut: an estimate; each minute's volume is put at its typical price, since Upstox gives no volume
    at each price. Upgrade if tick data ever becomes available.
    """
    if not candles_1m:
        return None
    step = max(0.05, round(candles_1m[-1]["close"] / 1000, 2))
    by_price = {}
    for c in candles_1m:
        p = round(round((c["high"] + c["low"] + c["close"]) / 3 / step) * step, 2)
        by_price[p] = by_price.get(p, 0) + c["volume"]
    prices = sorted(by_price)
    poc = max(prices, key=lambda p: by_price[p])
    lo = hi = prices.index(poc)
    inside, total = by_price[poc], sum(by_price.values())
    while inside < share * total and (lo > 0 or hi < len(prices) - 1):
        below = by_price[prices[lo - 1]] if lo > 0 else -1
        above = by_price[prices[hi + 1]] if hi < len(prices) - 1 else -1
        if above >= below:
            hi += 1
            inside += above
        else:
            lo -= 1
            inside += below
    return {"poc": poc, "val": prices[lo], "vah": prices[hi], "estimate": True}


def range_52w(daily):
    year = daily[-252:]
    if not year:
        return None
    return {"high": max(c["high"] for c in year), "low": min(c["low"] for c in year)}
