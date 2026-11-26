"""Trading costs. The only source is Upstox's charges API (the owner's rule): brokerage, STT, exchange,
SEBI, GST, stamp duty and the rest, exactly as Upstox would charge this account. There is no estimate of
our own: when Upstox can't answer, the result is None and the caller blocks new entries.

shortcut: the DP charge on delivery sells is not added (Upstox lists it separately under dp_plan); add it
once the first delivery fill shows whether the total already includes it.
"""
import logging

from core import upstox

log = logging.getLogger("upx")

PRODUCT = {"intraday": "I", "swing": "D", "long_term": "D"}


def order(key, qty, pool, side, price):
    """Upstox's charges in rupees for one order, or None if Upstox can't be reached."""
    try:
        return upstox.charges(key, qty, PRODUCT[pool], side, price)["total"]
    except (upstox.UpstoxError, RuntimeError) as err:
        log.warning("charges unavailable for %s: %s", key, err)
        return None


def round_trip(key, qty, pool, side, entry, exit_price):
    """Charges for opening (side) and closing (the opposite side) a position, or None."""
    close_side = "SELL" if side == "BUY" else "BUY"
    first = order(key, qty, pool, side, entry)
    if first is None:
        return None
    second = order(key, qty, pool, close_side, exit_price)
    return None if second is None else round(first + second, 2)
