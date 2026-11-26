"""Candle patterns and simple chart patterns on the latest candles. Information for the AI, not signals.

Each function returns the names of the patterns that the last candle (or the last few) completes.
Reversal patterns count only after a move into them: the three closes before the pattern rise or fall.
"""


def _body(c):
    return abs(c["close"] - c["open"])


def _range(c):
    return c["high"] - c["low"]


def _bull(c):
    return c["close"] > c["open"]


def _bear(c):
    return c["close"] < c["open"]


def _upper(c):
    return c["high"] - max(c["open"], c["close"])


def _lower(c):
    return min(c["open"], c["close"]) - c["low"]


def _fell_before(candles, i):
    closes = [c["close"] for c in candles[max(0, i - 3):i]]
    return len(closes) == 3 and closes[0] > closes[1] > closes[2]


def _rose_before(candles, i):
    closes = [c["close"] for c in candles[max(0, i - 3):i]]
    return len(closes) == 3 and closes[0] < closes[1] < closes[2]


def candles(cs):
    """Candle patterns completed by the last candle."""
    if len(cs) < 2:
        return []
    found = []
    last, prev = cs[-1], cs[-2]
    n = len(cs) - 1
    rng = _range(last) or 1e-9
    fell, rose = _fell_before(cs, n), _rose_before(cs, n)

    if _body(last) <= 0.1 * rng:
        found.append("doji")
    if _body(last) <= rng / 3 and _lower(last) >= 2 * max(_body(last), 1e-9) and _upper(last) <= 0.1 * rng:
        found.append("hammer" if fell else "pin_bar_bottom")
    if _body(last) <= rng / 3 and _upper(last) >= 2 * max(_body(last), 1e-9) and _lower(last) <= 0.1 * rng:
        found.append("shooting_star" if rose else "pin_bar_top")
    if _body(last) >= 0.9 * rng:
        found.append("bullish_marubozu" if _bull(last) else "bearish_marubozu")

    if fell and _bear(prev) and _bull(last) and last["open"] <= prev["close"] and last["close"] >= prev["open"]:
        found.append("bullish_engulfing")
    if rose and _bull(prev) and _bear(last) and last["open"] >= prev["close"] and last["close"] <= prev["open"]:
        found.append("bearish_engulfing")
    inside_body = (max(last["open"], last["close"]) <= max(prev["open"], prev["close"])
                   and min(last["open"], last["close"]) >= min(prev["open"], prev["close"]))
    if inside_body and _body(last) < 0.5 * _body(prev):
        if _bear(prev) and _bull(last) and fell:
            found.append("bullish_harami")
        if _bull(prev) and _bear(last) and rose:
            found.append("bearish_harami")
    if abs(last["high"] - prev["high"]) <= 0.001 * last["high"] and rose:
        found.append("tweezer_top")
    if abs(last["low"] - prev["low"]) <= 0.001 * last["low"] and fell:
        found.append("tweezer_bottom")

    if len(cs) >= 3:
        a, b = cs[-3], cs[-2]
        big = _body(a) >= 0.6 * (_range(a) or 1e-9)
        small = _body(b) <= 0.3 * _body(a)
        mid_a = (a["open"] + a["close"]) / 2
        if big and small and _bear(a) and _bull(last) and last["close"] > mid_a:
            found.append("morning_star")
        if big and small and _bull(a) and _bear(last) and last["close"] < mid_a:
            found.append("evening_star")
        three = cs[-3:]
        strong = all(_body(x) >= 0.6 * (_range(x) or 1e-9) for x in three)
        if strong and all(map(_bull, three)) and all(
                y["close"] > x["close"] and x["open"] <= y["open"] <= x["close"] for x, y in zip(three, three[1:])):
            found.append("three_white_soldiers")
        if strong and all(map(_bear, three)) and all(
                y["close"] < x["close"] and x["close"] <= y["open"] <= x["open"] for x, y in zip(three, three[1:])):
            found.append("three_black_crows")
    return found


def chart(cs):
    """Simple chart patterns ending at the last candle: inside bar, NR7, bull or bear flag, triangle."""
    found = []
    if len(cs) >= 2 and cs[-1]["high"] <= cs[-2]["high"] and cs[-1]["low"] >= cs[-2]["low"]:
        found.append("inside_bar")
    if len(cs) >= 7 and _range(cs[-1]) < min(_range(c) for c in cs[-7:-1]):
        found.append("nr7")
    for k in range(3, 9):  # flag: a sharp 5-candle move, then k quiet candles that give back under half of it
        if len(cs) < k + 10:
            break
        flag, pole, base = cs[-k:], cs[-k - 5:-k], cs[:-k - 5]
        usual = sum(_range(c) for c in base[-20:]) / len(base[-20:])
        move = pole[-1]["close"] - pole[0]["open"]
        hi, lo = max(c["high"] for c in flag), min(c["low"] for c in flag)
        quiet = hi - lo <= 0.5 * abs(move)
        if move >= 4 * usual and quiet and lo >= pole[-1]["close"] - 0.5 * move:
            found.append("bull_flag")
            break
        if -move >= 4 * usual and quiet and hi <= pole[-1]["close"] - 0.5 * move:
            found.append("bear_flag")
            break
    if len(cs) >= 8:
        w = cs[-8:]
        highs, lows = [c["high"] for c in w], [c["low"] for c in w]
        narrowing = all(b <= a for a, b in zip(highs, highs[1:])) and all(b >= a for a, b in zip(lows, lows[1:]))
        if narrowing and highs[-1] < highs[0] and lows[-1] > lows[0] and _range(w[-1]) <= 0.6 * _range(w[0]):
            found.append("triangle")
    return found
