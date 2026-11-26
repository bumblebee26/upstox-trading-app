"""Families, the luck line and the pass bar: is any shadow genuinely better, or just the luckiest of many?

- A family is a group of variants tested side by side (intraday entries, exits, overlays; swing; long-term...).
- The luck line: assume no variant has an edge (each one's daily results shifted to average zero), resample
  the days 2,000 times, and take the 95th percentile of the BEST variant's total. Beating it means beating the
  luck of running many tests at once.
- Status: "too early" under 100 trades; "kill" at 200+ trades when even the upper 95% bound of the average
  trade is below zero; "above luck" at 200+ trades over the luck line; "passed" once it has stayed above for
  20 more trading days; otherwise "watching". Benchmarks are shown for reference, never judged.
"""
import math
import random

TOO_EARLY, PASS_TRADES, STAY_DAYS, RESAMPLES = 100, 200, 20, 2000


def family(variant):
    if variant.startswith("B"):
        return "benchmarks"
    if variant.startswith("A"):
        return "AI vs rules"
    if variant.startswith("L"):
        return "long-term"
    if variant.startswith("S"):
        return "swing exits" if "-" in variant else "swing"
    if "-O" in variant:
        return "intraday overlays"
    return "intraday entries" if variant.endswith("-X1") else "intraday exits"


def luck_line(series, n=RESAMPLES, seed=0, q=0.95):
    """series: {variant: {day: rupees}}. The q-th percentile of the best variant's total under no edge.

    shortcut: plain Python, about variants x days x 2,000 additions; fine for a few hundred days, move to numpy
    in the lakehouse when the history gets long.
    """
    day_list = sorted({d for s in series.values() for d in s})
    if not day_list or not series:
        return 0.0
    rows = []
    for s in series.values():
        vals = [s.get(d, 0.0) for d in day_list]
        mean = sum(vals) / len(vals)
        rows.append([v - mean for v in vals])
    rnd, k = random.Random(seed), len(day_list)
    best = []
    for _ in range(n):
        pick = [rnd.randrange(k) for _ in range(k)]
        best.append(max(sum(r[i] for i in pick) for r in rows))
    best.sort()
    return round(best[min(n - 1, int(q * n))], 2)


def _upper_bound(trades):
    n = len(trades)
    mean = sum(trades) / n
    sd = math.sqrt(sum((t - mean) ** 2 for t in trades) / (n - 1)) if n > 1 else 0.0
    return mean + 1.96 * sd / math.sqrt(n)


def judge(variants, state, today, trading_days=None):
    """variants: {name: {"days": {day: rupees}, "trades": [net rupees per trade]}} for ONE family or several;
    state: {name: {"first_above": day}} carried between runs (updated here). Returns rows, best total first."""
    by_family = {}
    for name, v in variants.items():
        by_family.setdefault(family(name), {})[name] = v
    rows = []
    for fam_name, members in by_family.items():
        line = None if fam_name == "benchmarks" else luck_line({n: v["days"] for n, v in members.items()})
        for name, v in members.items():
            trades, total = v["trades"], round(sum(v["days"].values()), 2)
            n = len(trades)
            mine = state.setdefault(name, {})
            if line is None:
                status = "benchmark"
            elif n < TOO_EARLY:
                status = "too early"
            elif n >= PASS_TRADES and _upper_bound(trades) < 0:
                status = "kill"
            elif n >= PASS_TRADES and total > line:
                mine.setdefault("first_above", today)
                held = [d for d in (trading_days or []) if mine["first_above"] <= d <= today]
                status = "passed" if len(held) > STAY_DAYS else "above luck"
            else:
                status = "watching"
            if status not in ("above luck", "passed"):
                mine.pop("first_above", None)  # it must stay above without a break
            rows.append({"variant": name, "family": fam_name, "trades": n, "net_rs": total,
                         "avg_trade_rs": round(total / n, 2) if n else None, "luck_line": line, "status": status})
    return sorted(rows, key=lambda r: -r["net_rs"])
