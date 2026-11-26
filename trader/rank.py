"""Code-ranked candidates for the swing and long-term AI. The AI chooses from these (and its holdings);
code only narrows 500 stocks to a short list with the numbers that matter.
"""
from core import indicators as ind

MIN_HISTORY = 210  # trading days, enough for the 200-day average


def swing(daily_by_symbol, top=15):
    """Uptrend momentum: close above a rising 50-day and the 200-day average, RSI(14) under 80; ranked by
    3-month and 1-month return and closeness to the 52-week high."""
    rows = []
    for sym, d in daily_by_symbol.items():
        if len(d) < MIN_HISTORY:
            continue
        closes = [c["close"] for c in d]
        e50, e200 = ind.ema(closes, 50), ind.ema(closes, 200)
        rsi = ind.rsi(closes, 14)
        close = closes[-1]
        if not (close > e50[-1] > e200[-1] and e50[-1] > e50[-6] and rsi is not None and rsi < 80):
            continue
        high = ind.range_52w(d)["high"]
        r1, r3 = (close / closes[-22] - 1) * 100, (close / closes[-64] - 1) * 100
        from_high = (close / high - 1) * 100
        rows.append({"symbol": sym, "close": close, "ret_1m_pct": round(r1, 1), "ret_3m_pct": round(r3, 1),
                     "from_52w_high_pct": round(from_high, 1), "rsi14": rsi, "atr": ind.atr(d),
                     "score": round(0.5 * r3 + 0.3 * r1 + 0.2 * from_high, 2)})
    return sorted(rows, key=lambda r: -r["score"])[:top]


def num(value):
    """'21.0%' -> 21.0, '1,234.5' -> 1234.5, '-' or None -> None."""
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def long_term(ratios_by_symbol, top=15):
    """Quality at a fair price from Upstox key ratios: ROCE at least 15% (ROE when ROCE is missing, as for
    banks), a positive P/E; ranked by ROCE, ROE and how cheap the P/E is against its sector."""
    rows = []
    for sym, ratios in ratios_by_symbol.items():
        r = {x.get("name"): x for x in ratios or []}
        pe, sector_pe = num(r.get("P/E", {}).get("company_value")), num(r.get("P/E", {}).get("sector_value"))
        roce, roe = num(r.get("ROCE", {}).get("company_value")), num(r.get("ROE", {}).get("company_value"))
        quality = roce if roce is not None else roe
        if pe is None or pe <= 0 or quality is None or quality < 15:
            continue
        cheapness = min(sector_pe / pe, 2.0) if sector_pe else 1.0
        rows.append({"symbol": sym, "pe": pe, "sector_pe": sector_pe, "roce_pct": roce, "roe_pct": roe,
                     "pb": num(r.get("P/B", {}).get("company_value")),
                     "score": round(min(quality, 40) + min(roe or 0, 40) / 2 + 20 * cheapness, 2)})
    return sorted(rows, key=lambda x: -x["score"])[:top]
