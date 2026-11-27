"""The facts packet: everything the AI reads about one stock before a decision, worked out by code.

packet() is a pure function of the candles and quote, so it can be tested without Upstox; fetch() gets
them from Upstox (one intraday call per stock; daily candles once a day, passed in by the caller).
News, filings, flows and the track record are added by the trader (PR 5).
"""
from core import indicators as ind
from core import patterns as pat
from core import upstox


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b else None


def _since_open(c1m):
    return _pct(c1m[-1]["close"], c1m[0]["open"]) if c1m else None


def _frame(cs, daily=False, warm=()):
    """Indicators over the warm-up bars plus cs (so they are ready from the first bar); patterns over cs only."""
    allc = list(warm) + list(cs)
    closes = [c["close"] for c in allc]
    out = {"close": closes[-1] if closes else None, "ema9": ind.last_ema(closes, 9),
           "ema20": ind.last_ema(closes, 20), "ema50": ind.last_ema(closes, 50), "rsi14": ind.rsi(closes, 14),
           "atr": ind.atr(allc), "adx": ind.adx(allc), "macd": ind.macd(closes), "bollinger": ind.bollinger(closes),
           "supertrend": ind.supertrend(allc), "candles": pat.candles(cs[-6:]), "chart": pat.chart(cs[-40:])}
    if daily:
        out.update(ema200=ind.last_ema(closes, 200), rsi2=ind.rsi(closes, 2))
    return out


def packet(symbol, one_min, daily, quote, nifty_1m=None, sector_1m=None, same_time_volumes=None, warm_1m=None):
    """warm_1m: the previous trading day's 1-minute candles, so the 5m and 15m indicators are ready at 09:15."""
    today = one_min[-1]["ts"][:10] if one_min else None
    past = [d for d in daily if today is None or d["ts"][:10] < today]
    prev = past[-1] if past else None
    price = one_min[-1]["close"] if one_min else quote.get("last_price")
    five, fifteen = ind.resample(one_min, 5), ind.resample(one_min, 15)
    warm5, warm15 = ind.resample(warm_1m or [], 5), ind.resample(warm_1m or [], 15)

    buy = (quote.get("depth") or {}).get("buy") or [{}]
    sell = (quote.get("depth") or {}).get("sell") or [{}]
    bid, ask = buy[0].get("price"), sell[0].get("price")
    up, low = quote.get("upper_circuit_limit"), quote.get("lower_circuit_limit")
    tsell = quote.get("total_sell_quantity")
    stock_open = _since_open(one_min)
    sector_open = _since_open(sector_1m)

    return {
        "symbol": symbol,
        "time": one_min[-1]["ts"][11:16] if one_min else None,
        "price": price,
        "day": {
            "open": one_min[0]["open"] if one_min else None,
            "high": max((c["high"] for c in one_min), default=None),
            "low": min((c["low"] for c in one_min), default=None),
            "change_pct": _pct(price, prev["close"] if prev else None),
            "vwap": ind.vwap(one_min),
            "or5": ind.opening_range(one_min, 5), "or15": ind.opening_range(one_min, 15),
            "or30": ind.opening_range(one_min, 30),
            "value_area": ind.value_area(one_min),
            "rvol": ind.relative_volume(sum(c["volume"] for c in one_min), same_time_volumes or []),
        },
        "tf": {"5m": _frame(five, warm=warm5), "15m": _frame(fifteen, warm=warm15),
               "daily": _frame(past, daily=True)},
        "levels": {
            "prev_day": {k: prev[k] for k in ("high", "low", "close")} if prev else None,
            "pivots": ind.pivots(prev["high"], prev["low"], prev["close"]) if prev else None,
            "camarilla": ind.camarilla(prev["high"], prev["low"], prev["close"]) if prev else None,
            "round": ind.round_levels(price) if price else None,
            "52w": ind.range_52w(past),
        },
        "quote": {
            "bid": bid, "ask": ask,
            "spread_pct": round((ask - bid) / ((ask + bid) / 2) * 100, 3) if bid and ask else None,
            "upper_circuit": up, "lower_circuit": low,
            "to_upper_circuit_pct": _pct(up, price), "to_lower_circuit_pct": _pct(price, low) if low else None,
            "buy_sell_ratio": round(quote.get("total_buy_quantity", 0) / tsell, 2) if tsell else None,
        },
        "market": {
            "nifty_since_open_pct": _since_open(nifty_1m),
            "sector_since_open_pct": sector_open,
            "vs_sector_pct": round(stock_open - sector_open, 2) if stock_open is not None and sector_open is not None
            else None,
        },
    }


def fetch(symbol, key, daily, quote, nifty_key=None, sector_key=None, same_time_volumes=None):
    """Build one stock's packet from Upstox (the caller batches quotes and fetches daily candles once a day)."""
    return packet(symbol, upstox.intraday_candles(key, 1), daily, quote,
                  nifty_1m=upstox.intraday_candles(nifty_key, 1) if nifty_key else None,
                  sector_1m=upstox.intraday_candles(sector_key, 1) if sector_key else None,
                  same_time_volumes=same_time_volumes)
