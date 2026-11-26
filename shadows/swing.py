"""Swing shadows (docs/STRATEGIES.md section 2): rule-based paper ledgers on daily bars, ₹60,000 each,
at most 7 holdings at 25%. Each trading day after the close: fill yesterday's orders at today's open, exits on
today's close (stop, trailing stop, target, rule exit, time), then new orders for tomorrow's open.
"""
from core import indicators as ind
from shadows import portfolio as pf
from trader import rank

MAX_HOLD = 7
WEIGHT = 0.25


def _c(d):
    return [x["close"] for x in d]


def _sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def _atr(d):
    return ind.atr(d[-60:]) or 0.0


def _vol_x(d, x):
    avg = sum(b["volume"] for b in d[-21:-1]) / 20 if len(d) > 21 else None
    return bool(avg) and d[-1]["volume"] >= x * avg


def _ema(d, n, back=0):
    closes = _c(d[-(n * 3 + back):len(d) - back] if back else d[-n * 3:])
    return ind.ema(closes, n)[-1] if len(closes) >= n else None


def _trend(d):
    c, e50, e200 = d[-1]["close"], _ema(d, 50), _ema(d, 200)
    return e50 is not None and e200 is not None and c > e50 > e200


def _psar_up(d, step=0.02, top=0.2):
    """Parabolic SAR on the last 120 bars: True while the trend is up."""
    d = d[-120:]
    if len(d) < 5:
        return True
    up, af, ep, sar = True, step, d[0]["high"], d[0]["low"]
    for b in d[1:]:
        sar = sar + af * (ep - sar)
        if up:
            if b["low"] < sar:
                up, sar, ep, af = False, ep, b["low"], step
            elif b["high"] > ep:
                ep, af = b["high"], min(top, af + step)
        else:
            if b["high"] > sar:
                up, sar, ep, af = True, ep, b["high"], step
            elif b["low"] < ep:
                ep, af = b["low"], min(top, af + step)
    return up


# ---- entries: return (score, stop, target or None) or None, judged on today's close --------------------------------

def s02(d):
    if len(d) < 253 or d[-1]["close"] < max(b["high"] for b in d[-253:-1]) or not _vol_x(d, 1.5):
        return None
    return 1.0, d[-1]["close"] - 2 * _atr(d), None


def _donchian(n):
    def entry(d):
        if len(d) < n + 2 or d[-1]["close"] <= max(b["high"] for b in d[-n - 1:-1]):
            return None
        return 1.0, min(b["low"] for b in d[-11:-1]), None
    return entry


def _pullback(n):
    def entry(d):
        e = _ema(d, n)
        b = d[-1]
        if not _trend(d) or e is None or not (b["low"] <= e < b["close"]) or b["close"] <= b["open"]:
            return None
        return 1.0, min(x["low"] for x in d[-5:]), None
    return entry


def s07(d):
    e200, r2 = _ema(d, 200), ind.rsi(_c(d[-30:]), 2)
    if e200 is None or r2 is None or d[-1]["close"] <= e200 or r2 >= 10:
        return None
    return 10 - r2, d[-1]["close"] - 3 * _atr(d), None


def s08(d):
    e200, bb = _ema(d, 200), ind.bollinger(_c(d[-20:]))
    if e200 is None or bb is None or not (e200 < d[-1]["close"] < bb["lower"]):
        return None
    return 1.0, d[-1]["close"] - 3 * _atr(d), None


def _macd_cross(d):
    now, before = ind.macd(_c(d[-80:])), ind.macd(_c(d[-81:-1]))
    return now and before and before["macd"] <= before["signal"] and now["macd"] > now["signal"]


def s09(d):
    e50 = _ema(d, 50)
    if e50 is None or d[-1]["close"] <= e50 or not _macd_cross(d):
        return None
    return 1.0, d[-1]["close"] - 2 * _atr(d), None


def s10(d):
    if len(d) < 205:
        return None
    a, b, pa, pb = _ema(d, 50), _ema(d, 200), _ema(d, 50, back=1), _ema(d, 200, back=1)
    if None in (a, b, pa, pb) or not (pa <= pb and a > b):
        return None
    return 1.0, d[-1]["close"] - 3 * _atr(d), None


def s11(d):
    if len(d) < 253:
        return None
    c, last20 = d[-1]["close"], d[-21:-1]
    hi20, lo20 = max(b["high"] for b in last20), min(b["low"] for b in last20)
    high52 = max(b["high"] for b in d[-253:-1])
    if (hi20 - lo20) / c > 0.10 or c < 0.95 * high52 or c <= hi20 or not _vol_x(d, 1.5):
        return None
    return 1.0, lo20, None


def s16(d, news=False):
    if not news or len(d) < 60:
        return None
    c, e50 = d[-1]["close"], _ema(d, 50)
    if e50 is None or c <= e50 or c <= max(b["high"] for b in d[-21:-1]) or not _vol_x(d, 2) or c < 1.02 * d[-2]["close"]:
        return None
    stop = max(min(b["low"] for b in d[-5:]), c * 0.92)
    return 1.0, stop, c + 2 * (c - stop)


def s17(d):
    if len(d) < 210:
        return None
    c, closes = d[-1]["close"], _c(d)
    e20, e50, e200, r = _ema(d, 20), _ema(d, 50), _ema(d, 200), ind.rsi(closes[-60:], 14)
    m, a_now, a_then = ind.macd(closes[-80:]), ind.adx(d[-60:]), ind.adx(d[-65:-5])
    if None in (e20, e50, e200, r, m, a_now, a_then) or not (c > e20 and c > e50 and c > e200 and 50 <= r <= 65):
        return None
    if m["macd"] <= m["signal"] or a_now["adx"] <= 20 or a_now["adx"] <= a_then["adx"] or not _vol_x(d, 1.5):
        return None
    stop = min(b["low"] for b in d[-10:])
    return r, stop, c + 2 * (c - stop)


def s20(d):
    if len(d) < 220:
        return None
    closes = _c(d)
    sma, sma_then = _sma(closes, 150), _sma(closes[:-20], 150)
    base = all(abs(x / sma - 1) <= 0.15 for x in closes[-60:-1])
    if not (sma > sma_then and closes[-1] > sma and base and closes[-1] >= max(closes[-60:])):
        return None
    return 1.0, min(b["low"] for b in d[-20:]), None


def _ichimoku(d, back=0):
    d = d[:len(d) - back] if back else d
    if len(d) < 80:
        return None
    mid = lambda xs: (max(b["high"] for b in xs) + min(b["low"] for b in xs)) / 2  # noqa: E731
    tenkan, kijun = mid(d[-9:]), mid(d[-26:])
    past = d[:-26]
    span_a, span_b = (mid(past[-9:]) + mid(past[-26:])) / 2, mid(past[-52:])
    return tenkan, kijun, max(span_a, span_b)


def s21(d):
    now, before = _ichimoku(d), _ichimoku(d, back=1)
    if not now or not before:
        return None
    tenkan, kijun, cloud = now
    if not (d[-1]["close"] > cloud and tenkan > kijun and d[-2]["close"] <= before[2]):
        return None
    return 1.0, kijun if kijun < d[-1]["close"] else d[-1]["close"] - 2 * _atr(d), None


def s22(d):
    if len(d) < 200:
        return None
    weekly = [d[i]["close"] for i in range(len(d) - 1, 0, -5)][::-1]
    now, before = ind.macd(weekly), ind.macd(weekly[:-1])
    r_now, r_then = ind.rsi(_c(d[-60:]), 14), ind.rsi(_c(d[-61:-1]), 14)
    if not (now and before and r_now and r_then) or now["hist"] <= before["hist"] or not (r_then < 30 <= r_now):
        return None
    return 1.0, d[-1]["close"] - 2 * _atr(d), None


# ---- exits: True when the rule says sell on today's close ------------------------------------------------------------

def x_low(n):
    return lambda h, d: len(d) > n + 1 and d[-1]["close"] < min(b["low"] for b in d[-n - 1:-1])


def x_sma5(h, d):
    return d[-1]["close"] > _sma(_c(d), 5)


def x_mid(h, d):
    bb = ind.bollinger(_c(d[-20:]))
    return bool(bb) and d[-1]["close"] >= bb["mid"]


def x_macd_down(h, d):
    now, before = ind.macd(_c(d[-80:])), ind.macd(_c(d[-81:-1]))
    return bool(now and before) and before["macd"] >= before["signal"] and now["macd"] < now["signal"]


def x_death(h, d):
    a, b = _ema(d, 50), _ema(d, 200)
    return a is not None and b is not None and a < b


def x_sma150(h, d):
    return d[-1]["close"] < _sma(_c(d), 150)


def x_kijun(h, d):
    k = _ichimoku(d)
    return bool(k) and d[-1]["close"] < k[1]


def x_psar(h, d):
    return not _psar_up(d)


def _spec(entry, trail=None, exit=None, days=None, kind="signal"):
    return {"entry": entry, "trail": trail, "exit": exit, "days": days, "kind": kind}


STRATEGIES = {
    "S01": _spec(None, trail="atr2", days=20, kind="momentum"),
    "S02": _spec(s02, trail="atr2", days=20),
    "S03": _spec(_donchian(20), exit=x_low(10)),
    "S04": _spec(_donchian(55), exit=x_low(20)),
    "S05": _spec(_pullback(20), trail="atr2", days=20),
    "S06": _spec(_pullback(50), trail="atr2", days=20),
    "S07": _spec(s07, exit=x_sma5),
    "S08": _spec(s08, exit=x_mid),
    "S09": _spec(s09, exit=x_macd_down),
    "S10": _spec(s10, exit=x_death),
    "S11": _spec(s11, trail="atr2", days=20),
    "S14": _spec(None, kind="sector_rotation"),
    "S15": _spec(None, kind="relative_strength"),
    "S16": _spec(s16, days=10, kind="news"),
    "S17": _spec(s17, days=15),
    "S18": _spec(None, trail="atr2", days=20, kind="momentum_top3"),
    "S20": _spec(s20, exit=x_sma150),
    "S21": _spec(s21, exit=x_kijun),
    "S22": _spec(s22, trail="atr2", days=10),
}
for base in ("S01", "S02", "S05"):
    STRATEGIES[f"{base}-CH"] = dict(STRATEGIES[base], trail="chandelier")
    STRATEGIES[f"{base}-SAR"] = dict(STRATEGIES[base], trail=None, exit=x_psar)
    STRATEGIES[f"{base}-T10"] = dict(STRATEGIES[base], days=10)


def _exits(spec, led, day, hist, keys, charges):
    for sym, h in list(led["holdings"].items()):
        d = hist.get(sym)
        if not d:
            continue
        c = d[-1]["close"]
        if spec["trail"] == "atr2":
            h["stop"] = max(h["stop"], h["high_close"] - 2 * _atr(d))
        elif spec["trail"] == "chandelier":
            h["stop"] = max(h["stop"], h["high_high"] - 3 * _atr(d))
        reason = ("stop" if c <= h["stop"] else "target" if h.get("target") and c >= h["target"] else
                  "exit_rule" if spec["exit"] and spec["exit"](h, d) else
                  "time" if spec["days"] and h.get("bars", 0) >= spec["days"] else None)
        if reason:
            pf.exit_on_close(led, sym, c, day, reason, keys, charges, "swing")


def _rank_targets(kind, hist, nifty, industries):
    ret = lambda d, n: d[-1]["close"] / d[-n - 1]["close"] - 1 if len(d) > n else None  # noqa: E731
    if kind == "relative_strength":
        base = ret(nifty, 63) if nifty and len(nifty) > 63 else 0.0
        scored = [(r - base, s) for s, d in hist.items() if (r := ret(d, 63)) is not None]
        return [s for _, s in sorted(scored, reverse=True)[:MAX_HOLD]]
    by_ind = {}
    for s, d in hist.items():
        r = ret(d, 21)
        if r is not None:
            by_ind.setdefault((industries or {}).get(s, "Other"), []).append((r, s))
    best = sorted(by_ind.values(), key=lambda xs: -sum(r for r, _ in xs) / len(xs))[:2]
    return [s for xs in best for _, s in sorted(xs, reverse=True)[:2]]


def step(sid, led, day, hist, keys, charges, nifty=None, industries=None, news=None, week=None):
    """One trading day for swing shadow `sid`. hist: {symbol: daily bars up to and including today}."""
    spec = STRATEGIES[sid]
    pf.fill_and_value(led, day, {s: d[-1] for s, d in hist.items() if d}, keys, charges, "swing")
    _exits(spec, led, day, hist, keys, charges)
    pf.revalue(led, day)
    closes = {s: d[-1]["close"] for s, d in hist.items() if d}
    kind = spec["kind"]
    if kind in ("sector_rotation", "relative_strength"):
        if week is not None and led.get("week") != week:
            led["week"] = week
            targets = _rank_targets(kind, hist, nifty, industries)
            pf.rebalance(led, targets, weight=1 / max(1, len(targets)) if kind == "sector_rotation" else 1 / MAX_HOLD,
                         closes=closes)
        return
    picks = []
    if kind in ("momentum", "momentum_top3"):
        top = rank.swing(hist, top=3 if kind == "momentum_top3" else MAX_HOLD)
        picks = [(r["score"], r["symbol"], r["close"] - 2 * (r["atr"] or 0), None) for r in top]
    else:
        for sym, d in hist.items():
            out = spec["entry"](d, sym in (news or set())) if kind == "news" else spec["entry"](d)
            if out:
                picks.append((out[0], sym, out[1], out[2]))
    room = MAX_HOLD - len(led["holdings"]) - len([o for o in led["pending"] if o["side"] == "BUY"])
    equity = pf.equity_now(led)
    for score, sym, stop, target in sorted(picks, key=lambda x: -x[0]):
        if room <= 0:
            break
        c = closes.get(sym)
        if not c or stop is None or stop >= c or sym in led["holdings"]:
            continue
        amount = equity * WEIGHT
        if kind == "momentum_top3":  # 3% of the pool at risk, at most a third of it in one stock
            amount = min(equity / 3, equity * 0.03 / ((c - stop) / c))
        extra = {"target": target} if target else {}
        pf.order_buy(led, sym, amount=amount, stop=stop, **extra)
        room -= 1
