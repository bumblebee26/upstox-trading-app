"""Trading costs. The only source is Upstox's charges API (the owner's rule): brokerage, STT, exchange,
SEBI, GST, stamp duty and the rest, exactly as Upstox would charge this account. There is no estimate of
our own: when Upstox can't answer, the result is None and the caller blocks new entries.

One addition, also from Upstox's own reply: on a delivery sell Upstox's total leaves out the DP charge
(checked 26 Nov 2026: a ₹10,000 sell totalled ₹33.98 with GST on brokerage only). The DP charge is the
reply's dp_plan.min_expense (₹20 a stock a sell day on plan DP4A) plus 18% GST.

shortcut: the DP charge is added to every delivery sell order; Upstox charges it once per stock per day,
so two sells of one stock on one day would count it twice. Fine while each position is sold in one order.
"""
import logging

from core import upstox

log = logging.getLogger("upx")

PRODUCT = {"intraday": "I", "swing": "D", "long_term": "D"}
GST = 0.18


def order(key, qty, pool, side, price):
    """Upstox's charges in rupees for one order, or None if Upstox can't be reached."""
    try:
        reply = upstox.charges(key, qty, PRODUCT[pool], side, price)
    except (upstox.UpstoxError, RuntimeError) as err:
        log.warning("charges unavailable for %s: %s", key, err)
        return None
    total = reply["total"]
    if PRODUCT[pool] == "D" and side == "SELL":
        total += reply["dp_plan"]["min_expense"] * (1 + GST)
    return round(total, 2)


def round_trip(key, qty, pool, side, entry, exit_price):
    """Charges for opening (side) and closing (the opposite side) a position, or None."""
    close_side = "SELL" if side == "BUY" else "BUY"
    first = order(key, qty, pool, side, entry)
    if first is None:
        return None
    second = order(key, qty, pool, close_side, exit_price)
    return None if second is None else round(first + second, 2)
