"""The intraday shadow catalog (docs/STRATEGIES.md section 1): 30 entry rules, exit variants, regime overlays.

Each entry rule looks at one stock's day on 5-minute bars (built from 1-minute candles) and returns
(side, stop, target or None) at bar i, or None. Rules see only bars up to i, never later ones.
"""
from datetime import datetime, timedelta

from core import indicators as ind
from core import patterns as pat
from shadows.sim import Signal

FIRST_SIGNAL, LAST_SIGNAL = "09:30", "14:30"


class Context:
    """One stock's day, with per-bar series worked out once."""

    def __init__(self, symbol, key, one, daily_past, nifty_one=None, sector_one=None, vix_prev=None,
                 nifty_above_200=None):
        self.symbol, self.key, self.one = symbol, key, one
        self.five = ind.resample(one, 5)
        f = self.five
        self.open = [b["open"] for b in f]
        self.high = [b["high"] for b in f]
        self.low = [b["low"] for b in f]
        self.close = [b["close"] for b in f]
        self.vol = [b["volume"] for b in f]
        self.end = [(datetime.fromisoformat(b["ts"][:16]) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M") for b in f]
        self.ema9, self.ema20 = ind.ema(self.close, 9), ind.ema(self.close, 20)
        typ = [(h + l + c) / 3 for h, l, c in zip(self.high, self.low, self.close)]
        self.vwap, self.vwap_lo, self.vwap_hi, cv, cvv, cvol = [], [], [], 0.0, 0.0, 0
        for t, v in zip(typ, self.vol):
            cv, cvv, cvol = cv + t * v, cvv + t * t * v, cvol + v
            mean = cv / cvol if cvol else t
            sd = max(0.0, cvv / cvol - mean * mean) ** 0.5 if cvol else 0.0
            self.vwap.append(mean)
            self.vwap_lo.append(mean - sd)
            self.vwap_hi.append(mean + sd)
        trs = [h - l if i == 0 else max(h - l, abs(h - self.close[i - 1]), abs(l - self.close[i - 1]))
               for i, (h, l) in enumerate(zip(self.high, self.low))]
        self.atr = [sum(trs[:i + 1]) / (i + 1) if i < 14 else None for i in range(len(trs))]
        for i in range(14, len(trs)):
            self.atr[i] = (self.atr[i - 1] * 13 + trs[i]) / 14
        self.prev = daily_past[-1] if daily_past else None
        self.daily_ema20 = ind.last_ema([d["close"] for d in daily_past], 20) if len(daily_past) >= 20 else None
        ranges = [d["high"] - d["low"] for d in daily_past[-7:]]
        self.nr7 = len(ranges) == 7 and ranges[-1] < min(ranges[:-1])
        p = self.prev
        self.piv = ind.pivots(p["high"], p["low"], p["close"]) if p else None
        self.cam = ind.camarilla(p["high"], p["low"], p["close"]) if p else None
        self.orng = {n: ind.opening_range(one, n) for n in (5, 15, 30)}
        self.gap = (self.open[0] / p["close"] - 1) * 100 if p and f else 0.0
        self.nifty_one, self.sector_one = nifty_one or [], sector_one or []
        self.vix_prev, self.nifty_above_200 = vix_prev, nifty_above_200
        ha_c = [(o + h + l + c) / 4 for o, h, l, c in zip(self.open, self.high, self.low, self.close)]
        ha_o = []
        for i in range(len(f)):
            ha_o.append((self.open[0] + self.close[0]) / 2 if i == 0 else (ha_o[-1] + ha_c[i - 1]) / 2)
        self.ha = list(zip(ha_o, ha_c, [max(h, o, c) for h, o, c in zip(self.high, ha_o, ha_c)],
                           [min(l, o, c) for l, o, c in zip(self.low, ha_o, ha_c)]))
        self._cache = {}

    def index_of(self, end_time):
        return self.end.index(end_time)

    def vol_up(self, i, x=1.5):
        return i > 0 and self.vol[i] >= x * (sum(self.vol[:i]) / i)

    def since_open(self, one, i):
        """% move of an index from its first open to its last close before bar i ends."""
        upto = [c for c in one if c["ts"][:16] < self.end[i]]
        return (upto[-1]["close"] / upto[0]["open"] - 1) * 100 if upto else None

    def stock_since_open(self, i):
        return (self.close[i] / self.open[0] - 1) * 100

    def value_area(self, i):
        if ("va", i) not in self._cache:
            self._cache[("va", i)] = ind.value_area([c for c in self.one if c["ts"][:16] < self.end[i]])
        return self._cache[("va", i)]

    def supertrend(self, i):
        if ("st", i) not in self._cache:
            self._cache[("st", i)] = ind.supertrend(self.five[:i + 1])
        return self._cache[("st", i)]

    def adx(self, i):
        a = ind.adx(self.five[:i + 1])
        return a["adx"] if a else None


def build_context(symbol, key, one, daily_past, **kw):
    return Context(symbol, key, one, daily_past, **kw)


def _cross_up(c, i, level):
    return level is not None and i > 0 and c.close[i - 1] <= level < c.close[i]


def _cross_down(c, i, level):
    return level is not None and i > 0 and c.close[i - 1] >= level > c.close[i]


# ---- entry rules: each returns (side, stop, target or None) or None ---------------------------------------------

def _orb(n):
    def rule(c, i):
        r, atr = c.orng[n], c.atr[i]
        if not r or c.end[i] <= c.one[0]["ts"][:11] + f"{(555 + n) // 60:02d}:{(555 + n) % 60:02d}" or not c.vol_up(i):
            return None
        if _cross_up(c, i, r["high"]):
            return "BUY", max(r["low"], c.close[i] - 1.5 * atr), None
        if _cross_down(c, i, r["low"]):
            return "SELL", min(r["high"], c.close[i] + 1.5 * atr), None
    return rule


def e04(c, i):
    if i < 2 or not c.vol_up(i):
        return None
    if c.close[i - 1] < c.vwap[i - 1] and c.close[i] > c.vwap[i]:
        return "BUY", min(c.low[i - 2:i + 1]), None
    if c.close[i - 1] > c.vwap[i - 1] and c.close[i] < c.vwap[i]:
        return "SELL", max(c.high[i - 2:i + 1]), None


def e05(c, i):
    if not c.prev:
        return None
    if _cross_up(c, i, c.prev["high"]):
        return "BUY", c.low[i], None
    if _cross_down(c, i, c.prev["low"]):
        return "SELL", c.high[i], None


def e06(c, i):
    r = c.orng[15]
    if not r or c.end[i][11:] <= "09:30":
        return None
    if c.gap >= 1 and _cross_up(c, i, r["high"]):
        return "BUY", r["low"], None
    if c.gap <= -1 and _cross_down(c, i, r["low"]):
        return "SELL", r["high"], None


def e07(c, i):
    r = c.orng[15]
    if not r or not ("09:30" < c.end[i][11:] <= "11:00"):
        return None
    if c.gap <= -3 and _cross_up(c, i, r["high"]):
        return "BUY", min(c.low[:i + 1]), None
    if c.gap >= 3 and _cross_down(c, i, r["low"]):
        return "SELL", max(c.high[:i + 1]), None


def e08(c, i):
    r = c.orng[15]
    if c.end[i][11:] != "09:30" or not r:
        return None
    move, span = (c.close[i] / c.open[0] - 1) * 100, r["high"] - r["low"]
    mid = (r["high"] + r["low"]) / 2
    if move >= 1 and c.close[i] >= r["high"] - 0.2 * span:
        return "BUY", mid, None
    if move <= -1 and c.close[i] <= r["low"] + 0.2 * span:
        return "SELL", mid, None


def e09(c, i):
    if i < 3 or c.ema20[i] is None or c.ema20[i - 3] is None:
        return None
    e9, e20, near = c.ema9[i], c.ema20[i], max(c.ema9[i], c.vwap[i])
    if c.close[i] > e20 and e9 > e20 and e20 > c.ema20[i - 3] and c.low[i] <= near * 1.0005 \
            and c.close[i] > c.open[i] and c.close[i] > e9:
        return "BUY", c.low[i], None
    near = min(c.ema9[i], c.vwap[i])
    if c.close[i] < e20 and e9 < e20 and e20 < c.ema20[i - 3] and c.high[i] >= near * 0.9995 \
            and c.close[i] < c.open[i] and c.close[i] < e9:
        return "SELL", c.high[i], None


def e10(c, i):
    if i < 4 or c.ema20[i] is None or c.ema20[i - 3] is None:
        return None
    mh, ml = c.high[i - 2], c.low[i - 2]
    inside = c.high[i - 1] <= mh and c.low[i - 1] >= ml
    if inside and c.close[i] > mh and c.ema20[i] > c.ema20[i - 3]:
        return "BUY", ml, None
    if inside and c.close[i] < ml and c.ema20[i] < c.ema20[i - 3]:
        return "SELL", mh, None


def e11(c, i):
    if not (c.prev and c.nr7):
        return None
    mid = (c.prev["high"] + c.prev["low"]) / 2
    if _cross_up(c, i, c.prev["high"]):
        return "BUY", mid, None
    if _cross_down(c, i, c.prev["low"]):
        return "SELL", mid, None


def e12(c, i):
    if not c.cam:
        return None
    if c.low[i] < c.cam["l3"] < c.close[i]:
        return "BUY", c.cam["l4"], None
    if c.high[i] > c.cam["h3"] > c.close[i]:
        return "SELL", c.cam["h4"], None


def e13(c, i):
    if not c.cam:
        return None
    if _cross_up(c, i, c.cam["h4"]):
        return "BUY", c.cam["h3"], None
    if _cross_down(c, i, c.cam["l4"]):
        return "SELL", c.cam["l3"], None


def e14(c, i):
    if not c.piv:
        return None
    s1, r1 = c.piv["s1"], c.piv["r1"]
    if c.low[i] <= s1 * 1.001 and c.close[i] > s1:
        return "BUY", s1 * 0.997, None
    if c.high[i] >= r1 * 0.999 and c.close[i] < r1:
        return "SELL", r1 * 1.003, None


def e15(c, i):
    r2, atr = ind.rsi(c.close[:i + 1], 2), c.atr[i]
    if r2 is None or c.daily_ema20 is None:
        return None
    if r2 < 5 and c.close[i] > c.daily_ema20 and c.vwap[i] > c.close[i]:
        return "BUY", c.close[i] - atr, c.vwap[i]
    if r2 > 95 and c.close[i] < c.daily_ema20 and c.vwap[i] < c.close[i]:
        return "SELL", c.close[i] + atr, c.vwap[i]


def e16(c, i):
    if i < 1 or c.ema20[i - 1] is None:
        return None
    up = c.ema9[i - 1] <= c.ema20[i - 1] and c.ema9[i] > c.ema20[i]
    down = c.ema9[i - 1] >= c.ema20[i - 1] and c.ema9[i] < c.ema20[i]
    if (up or down) and (c.adx(i) or 0) > 20:
        return ("BUY", c.low[i], None) if up else ("SELL", c.high[i], None)


def e17(c, i):
    now, before = c.supertrend(i), c.supertrend(i - 1) if i else None
    if not (now and before) or now["direction"] == before["direction"]:
        return None
    return ("BUY", now["line"], None) if now["direction"] == "up" else ("SELL", now["line"], None)


def e18(c, i):
    if i < 25:
        return None
    widths = [ind.bollinger(c.close[:k + 1])["width_pct"] for k in range(19, i)]
    b = ind.bollinger(c.close[:i + 1])
    if widths[-1] > sorted(widths)[max(0, len(widths) // 5 - 1)]:
        return None
    if c.close[i] > b["upper"]:
        return "BUY", b["mid"], None
    if c.close[i] < b["lower"]:
        return "SELL", b["mid"], None


def e19(c, i):
    rng = c.high[i] - c.low[i]
    if not rng or not c.vol_up(i, 3):
        return None
    move = (c.close[i] / c.open[i] - 1) * 100
    if move >= 0.5 and c.close[i] >= c.high[i] - 0.25 * rng:
        return "BUY", c.low[i], None
    if move <= -0.5 and c.close[i] <= c.low[i] + 0.25 * rng:
        return "SELL", c.high[i], None


def e20(c, i):
    sector = c.since_open(c.sector_one, i)
    if sector is None or c.end[i][11:] < "10:00":
        return None
    lead = c.stock_since_open(i) - sector
    if lead >= 1 and c.close[i] > c.vwap[i]:
        return "BUY", c.vwap[i] * 0.998, None
    if lead <= -1 and c.close[i] < c.vwap[i]:
        return "SELL", c.vwap[i] * 1.002, None


def e21(c, i):
    if i < 3 or not c.prev:
        return None
    found = set(pat.candles(c.five[max(0, i - 5):i + 1]))
    va = c.value_area(i)
    supports = [c.prev["low"], c.vwap_lo[i], c.piv["s1"], c.cam["l3"], va["val"] if va else None]
    resist = [c.prev["high"], c.vwap_hi[i], c.piv["r1"], c.cam["h3"], va["vah"] if va else None]
    near = lambda levels, x: any(lv and abs(x / lv - 1) <= 0.003 for lv in levels)  # noqa: E731
    if found & {"bullish_engulfing", "hammer", "morning_star"} and near(supports, c.low[i]):
        return "BUY", min(c.low[i - 2:i + 1]), None
    if found & {"bearish_engulfing", "shooting_star", "evening_star"} and near(resist, c.high[i]):
        return "SELL", max(c.high[i - 2:i + 1]), None


def e22(c, i):
    if i < 1 or not c.vol_up(i):
        return None
    for level in ind.round_levels(c.close[i - 1]):
        if _cross_up(c, i, level):
            return "BUY", c.low[i], None
        if _cross_down(c, i, level):
            return "SELL", c.high[i], None


def e23(c, i):
    if c.end[i][11:] < "10:30":
        return None
    va = c.value_area(i)
    if not va:
        return None
    if _cross_up(c, i, va["vah"]) and va["poc"] < c.close[i]:
        return "BUY", va["poc"], None
    if _cross_down(c, i, va["val"]) and va["poc"] > c.close[i]:
        return "SELL", va["poc"], None


def e24(c, i):
    nifty = c.since_open(c.nifty_one, i)
    if nifty is None or i < 1:
        return None
    mine = c.stock_since_open(i)
    if nifty >= 0.5 and mine <= 0 and c.close[i] > c.vwap[i] and c.close[i] > c.high[i - 1]:
        return "BUY", min(c.low[:i + 1]), None
    if nifty <= -0.5 and mine >= 0 and c.close[i] < c.vwap[i] and c.close[i] < c.low[i - 1]:
        return "SELL", max(c.high[:i + 1]), None


def e25(c, i):
    if i < 3:
        return None
    o, hi, lo = c.open[0], max(c.high[:i]), min(c.low[:i])
    if hi >= o * 1.01 and c.high[:i].index(hi) < i - 1:
        level, stop = hi - 0.618 * (hi - o), hi - 0.786 * (hi - o)
        if c.low[i] <= level < c.close[i] and c.close[i] > c.open[i]:
            return "BUY", stop, None
    if lo <= o * 0.99 and c.low[:i].index(lo) < i - 1:
        level, stop = lo + 0.618 * (o - lo), lo + 0.786 * (o - lo)
        if c.high[i] >= level > c.close[i] and c.close[i] < c.open[i]:
            return "SELL", stop, None


def e26(c, i):
    if i < 3 or c.ema20[i] is None:
        return None
    last = c.ha[i - 2:i + 1]
    if all(hc > ho and abs(hl - min(ho, hc)) < 1e-9 for ho, hc, hh, hl in last) and c.close[i] > c.ema20[i]:
        return "BUY", c.low[i - 2], None
    if all(hc < ho and abs(hh - max(ho, hc)) < 1e-9 for ho, hc, hh, hl in last) and c.close[i] < c.ema20[i]:
        return "SELL", c.high[i - 2], None


def e27(c, i):
    if i < 15:
        return None
    found = pat.chart(c.five[max(0, i - 40):i])
    if "bull_flag" in found and c.close[i] > max(c.high[i - 4:i]):
        return "BUY", min(c.low[i - 4:i]), None
    if "bear_flag" in found and c.close[i] < min(c.low[i - 4:i]):
        return "SELL", max(c.high[i - 4:i]), None


def e28(c, i):
    if i < 15 or not c.vol_up(i):
        return None
    if "triangle" in pat.chart(c.five[max(0, i - 40):i]):
        if c.close[i] > max(c.high[i - 8:i]):
            return "BUY", min(c.low[i - 8:i]), None
        if c.close[i] < min(c.low[i - 8:i]):
            return "SELL", max(c.high[i - 8:i]), None


def e29(c, i):
    if not c.vol_up(i):
        return None
    found = pat.candles(c.five[max(0, i - 5):i + 1])
    mid = (c.high[i] + c.low[i]) / 2
    if "bullish_marubozu" in found and c.close[i] > c.vwap[i]:
        return "BUY", mid, None
    if "bearish_marubozu" in found and c.close[i] < c.vwap[i]:
        return "SELL", mid, None


def e30(c, i):
    if i < 3 or c.ema20[i] is None:
        return None
    found = pat.candles(c.five[max(0, i - 5):i + 1])
    if "three_white_soldiers" in found and c.close[i] > c.ema20[i]:
        return "BUY", c.low[i - 2], None
    if "three_black_crows" in found and c.close[i] < c.ema20[i]:
        return "SELL", c.high[i - 2], None


ENTRIES = {"E01": _orb(5), "E02": _orb(15), "E03": _orb(30), "E04": e04, "E05": e05, "E06": e06, "E07": e07,
           "E08": e08, "E09": e09, "E10": e10, "E11": e11, "E12": e12, "E13": e13, "E14": e14, "E15": e15,
           "E16": e16, "E17": e17, "E18": e18, "E19": e19, "E20": e20, "E21": e21, "E22": e22, "E23": e23,
           "E24": e24, "E25": e25, "E26": e26, "E27": e27, "E28": e28, "E29": e29, "E30": e30}


# ---- overlays and variants ----------------------------------------------------------------------------------------

def o1(c, i, side):
    return c.vix_prev is not None and c.vix_prev < 20


def o2(c, i, side):
    return c.nifty_above_200 is not None and c.nifty_above_200 == (side == "BUY")


def o3(c, i, side):
    move = c.since_open(c.nifty_one, i)
    return move is not None and (move > 0 if side == "BUY" else move < 0)


OVERLAYS = {"O1": o1, "O2": o2, "O3": o3}
CORE = ("E02", "E04", "E05", "E09")
VARIANTS = {f"{e}-X1": (fn, "X1", None) for e, fn in ENTRIES.items()}
VARIANTS.update({f"{e}-{x}": (ENTRIES[e], x, None) for e in CORE for x in ("X2", "X3", "X4", "X5", "X6", "X7")})
VARIANTS.update({f"{e}-{o}": (ENTRIES[e], "X1", OVERLAYS[o]) for e in CORE for o in OVERLAYS})


def signals(c, rule, overlay=None):
    """The first signal of the day for this stock (one entry per stock per strategy)."""
    for i in range(len(c.five)):
        if not (FIRST_SIGNAL <= c.end[i][11:] <= LAST_SIGNAL):
            continue
        out = rule(c, i)
        if not out:
            continue
        side, stop, target = out
        close = c.close[i]
        if stop is None or not ((stop < close) if side == "BUY" else (stop > close)):
            continue
        if target is not None and not ((target > close) if side == "BUY" else (target < close)):
            target = None
        if overlay and not overlay(c, i, side):
            continue
        return [Signal(symbol=c.symbol, key=c.key, side=side, signal_time=c.end[i], stop=round(stop, 2),
                       target=round(target, 2) if target else None)]
    return []
