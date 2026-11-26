"""Long-term shadows (docs/STRATEGIES.md section 3): rule-based picks from Upstox fundamentals and daily bars,
₹1,00,000 each, rebalanced on the first trading day of each month (the equal-weight index ones quarterly),
orders filled at the next open. Data per stock: ratios (key ratios), income, cashflow, holdings (shareholding)
and actions (corporate actions), as core/upstox.fundamentals returns them.
"""
import math
from datetime import date

from trader import rank

TOP = 10
WEIGHT = 0.10
STRATEGIES = {"L01": "quality", "L02": "momentum", "L03": "momentum top 5", "L04": "value", "L05": "GARP",
              "L06": "magic formula", "L07": "dividend yield", "L08": "low volatility", "L09": "quality + momentum",
              "L10": "shareholding up", "L15": "equal-weight Nifty Next 50", "L16": "equal-weight Nifty 50"}
QUARTERLY = {"L15", "L16"}


def _ratio(d, name, field="company_value"):
    for r in d.get("ratios") or []:
        if r.get("name") == name:
            return rank.num(r.get(field))
    return None


def _period_key(p):
    months = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                          "Nov", "Dec"), 1)}
    try:
        mon, year = p.split()
        return int(year), months.get(mon[:3], 0)
    except (AttributeError, ValueError):
        return 0, 0


def _series(rows, category):
    """Values oldest first for one category (history order in the reply is not relied on)."""
    for r in rows or []:
        if r.get("category") == category:
            h = sorted(r.get("history") or [], key=lambda x: _period_key(x.get("period")))
            return [x.get("value") for x in h if isinstance(x.get("value"), (int, float))]
    return []


def _cagr3(values):
    if len(values) < 4 or values[-4] <= 0 or values[-1] <= 0:
        return None
    return ((values[-1] / values[-4]) ** (1 / 3) - 1) * 100


def _quality(d):
    roce, roe = _ratio(d, "ROCE"), _ratio(d, "ROE")
    q = roce if roce is not None else roe
    return q is not None and q >= 15


def _pe(d):
    pe = _ratio(d, "P/E")
    return pe if pe is not None and pe > 0 else None


def _ret(b, n):
    return b[-1]["close"] / b[-n - 1]["close"] - 1 if len(b) > n else None


def _vol(b):
    r = [b[i]["close"] / b[i - 1]["close"] - 1 for i in range(max(1, len(b) - 250), len(b))]
    if len(r) < 20:
        return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / len(r))


def _momentum(data, daily):
    rows = []
    for s, d in data.items():
        b, vol = daily.get(s) or [], _vol(daily.get(s) or [])
        r6, r12 = _ret(b, 126), _ret(b, 250)
        if _pe(d) and vol and r6 is not None and r12 is not None:
            rows.append(((r6 / vol + r12 / vol) / 2, s))
    return [s for _, s in sorted(rows, reverse=True)]


def targets(lid, data, daily, today, index_members=None, industries=None):
    """The stocks strategy `lid` holds after this rebalance, best first: at most 10 (5 for L03) and at most
    2 per industry. The equal-weight index copies hold every member."""
    if lid in QUARTERLY:
        return list(index_members or [])
    picks, count = [], {}
    for s in _ranked(lid, data, daily, today):
        ind = (industries or {}).get(s, s)  # no industry known: the stock counts alone
        if count.get(ind, 0) < 2:
            picks.append(s)
            count[ind] = count.get(ind, 0) + 1
    return picks[:5 if lid == "L03" else TOP]


def _ranked(lid, data, daily, today):
    if lid in ("L02", "L03"):
        return _momentum(data, daily)
    if lid == "L01":
        ok = []
        for s, d in data.items():
            ocf = _series((d.get("cashflow") or {}).get("cash_flow"), "operating")[-4:]
            inc = (d.get("income") or {}).get("income_statement")
            rev, profit = _cagr3(_series(inc, "revenue")), _cagr3(_series(inc, "net_profit"))
            if _quality(d) and _pe(d) and sum(1 for v in ocf if v > 0) >= 3 and (rev or 0) > 10 and (profit or 0) > 10:
                ok.append(s)
        pes = sorted(_pe(data[s]) for s in ok)
        median = pes[len(pes) // 2] if pes else 0
        ranked = rank.long_term({s: data[s]["ratios"] for s in ok if _pe(data[s]) <= median}, top=len(ok))
        return [r["symbol"] for r in ranked]
    if lid == "L04":
        return [s for _, s in sorted((_pe(d), s) for s, d in data.items() if _quality(d) and _pe(d))]
    if lid == "L05":
        rows = []
        for s, d in data.items():
            g = _cagr3(_series((d.get("income") or {}).get("income_statement"), "net_profit"))
            if _pe(d) and g and g >= 15 and _pe(d) / g < 1:
                rows.append((_pe(d) / g, s))
        return [s for _, s in sorted(rows)]
    if lid == "L06":
        rows = [(s, 1 / ev, _ratio(d, "ROCE")) for s, d in data.items()
                if (ev := _ratio(d, "EV/EBITDA")) and ev > 0 and _ratio(d, "ROCE") is not None]
        # rank = how many stocks are strictly better, so equal values share a rank
        ey = {s: sum(1 for r in rows if r[1] > y) for s, y, _ in rows}
        rc = {s: sum(1 for r in rows if r[2] > c) for s, _, c in rows}
        return sorted(ey, key=lambda s: (ey[s] + rc[s], s))
    if lid == "L07":
        day = date.fromisoformat(today)
        rows = []
        for s, d in data.items():
            paid = 0.0
            for a in d.get("actions") or []:
                try:
                    ex = date.fromisoformat(str(a.get("expiry_date"))[:10])
                except ValueError:
                    continue
                if "dividend" in str(a.get("name", "")).lower() and 0 <= (day - ex).days <= 365:
                    paid += float(a.get("amount") or 0)
            close = (daily.get(s) or [{}])[-1].get("close")
            if paid > 0 and close:
                rows.append((paid / close, s))
        return [s for _, s in sorted(rows, reverse=True)]
    if lid == "L08":
        rows = [(v, s) for s, d in data.items() if _quality(d) and (v := _vol(daily.get(s) or []))]
        return [s for _, s in sorted(rows)]
    if lid == "L09":
        quality = _ranked("L01", data, daily, today)  # L01's list, ranked by 6-month return
        rows = [(r, s) for s in quality if (r := _ret(daily.get(s) or [], 126)) is not None]
        return [s for _, s in sorted(rows, reverse=True)]
    if lid == "L10":
        rows = []
        for s, d in data.items():
            ups = [v[-1] - v[-2] for cat in ("promoters", "fii") if len(v := _series(d.get("holdings"), cat)) >= 2]
            if ups and max(ups) >= 1:
                rows.append((max(ups), s))
        return [s for _, s in sorted(rows, reverse=True)]
    raise KeyError(lid)


def weight(lid, n_targets):
    return 0.15 if lid == "L03" else (1 / max(1, n_targets) if lid in QUARTERLY else WEIGHT)


def rebalance_due(lid, led, today):
    """Monthly on the first run of a new month; the index-style ones in Jan, Apr, Jul and Oct (and at the start)."""
    month = today[:7]
    if led.get("month") == month:
        return False
    if lid in QUARTERLY and led.get("month") is not None:
        return int(month[5:]) in (1, 4, 7, 10)
    return True
