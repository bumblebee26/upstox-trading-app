"""The paper ledger of one pool (intraday, swing or long-term): cash, open positions and the day's counters.

A pool's state is a plain dict, saved as JSON by the caller. Balance changes only when a position closes:
net P&L = (exit - entry) x quantity for a buy (the reverse for a short), minus Upstox's charges for both orders.
"""
from datetime import timedelta

from trader import risk

SLIPPAGE_PCT = 0.05   # every fill is this much worse than the quoted price (buy higher, sell lower)


def new_pool(pool):
    rules = risk.POOLS[pool]
    return {"pool": pool, "starting_capital": rules["capital"], "balance": float(rules["capital"]),
            "day": None, "day_start_balance": float(rules["capital"]), "day_risk_pct": rules["risk_pct"],
            "realized_today": 0.0, "trades_today": 0, "sector_trades": {}, "positions": {},
            "loss_streak": 0, "cooloff_until": None, "loss_limit_hit": False, "stopped": False, "paused": False,
            "week": {"start": None, "realized": 0.0, "brake": False}}


def new_day(state, day, vix=None):
    """Start a trading day: bank yesterday into the week (a new week on Monday) and reset the day's counters.
    Calling it again on the same day (a restart) changes nothing, so limits and counts are never reset mid-day."""
    if state["day"] == day.isoformat():
        return
    monday = day - timedelta(days=day.weekday())
    week = state["week"]
    if week["start"] != monday.isoformat():
        state["week"] = {"start": monday.isoformat(), "realized": 0.0, "brake": False}
    else:
        week["realized"] += state["realized_today"]
    rules = risk.POOLS[state["pool"]]
    state.update(day=day.isoformat(), day_start_balance=state["balance"], realized_today=0.0, trades_today=0,
                 sector_trades={}, loss_streak=0, cooloff_until=None, loss_limit_hit=False,
                 day_risk_pct=risk.risk_pct_for_vix(vix) if rules["vix_scaled"] else rules["risk_pct"])


def slip(price, side):
    """The fill price for an order on `side` (BUY or SELL)."""
    f = SLIPPAGE_PCT / 100
    return round(price * (1 + f) if side == "BUY" else price * (1 - f), 2)


def margin_used(state):
    leverage = risk.POOLS[state["pool"]]["leverage"]
    return sum(p["qty"] * p["fill_price"] for p in state["positions"].values()) / leverage


def free_margin(state):
    return state["balance"] - margin_used(state)


def open_risk(state):
    """What the open positions lose if every stop is hit (0 for a position whose stop is past its entry)."""
    return sum(max(0.0, (p["fill_price"] - p["stop"]) * (1 if p["side"] == "BUY" else -1) * p["qty"])
               for p in state["positions"].values())


def week_realized(state):
    return state["week"]["realized"] + state["realized_today"]


def open_position(state, symbol, side, qty, fill_price, stop, target, sector, *, charges, now):
    state["positions"][symbol] = {"side": side, "qty": qty, "fill_price": fill_price, "stop": stop,
                                  "target": target, "sector": sector, "entry_charges": charges,
                                  "opened_at": now.isoformat(timespec="seconds")}
    state["trades_today"] += 1
    state["sector_trades"][sector] = state["sector_trades"].get(sector, 0) + 1


def move_stop(state, symbol, new_stop):
    """The AI may tighten or trail a stop; it may never widen one (move it further from the price's wrong side)."""
    p = state["positions"][symbol]
    widens = new_stop < p["stop"] if p["side"] == "BUY" else new_stop > p["stop"]
    if widens:
        raise risk.RuleBroken(f"{symbol}: a stop may only tighten ({p['stop']} -> {new_stop} would widen it)")
    p["stop"] = new_stop


def close_position(state, symbol, exit_price, *, charges, now, reason):
    """Close a position at exit_price (already slipped); return the net P&L in rupees."""
    p = state["positions"].pop(symbol)
    direction = 1 if p["side"] == "BUY" else -1
    net = round((exit_price - p["fill_price"]) * direction * p["qty"] - p["entry_charges"] - charges, 2)
    state["balance"] = round(state["balance"] + net, 2)
    state["realized_today"] = round(state["realized_today"] + net, 2)
    rules = risk.POOLS[state["pool"]]
    if net < 0:
        state["loss_streak"] += 1
        if rules["cooloff_after"] and state["loss_streak"] % rules["cooloff_after"] == 0:
            state["cooloff_until"] = (now + timedelta(minutes=rules["cooloff_min"])).isoformat(timespec="seconds")
    else:
        state["loss_streak"] = 0
    if rules["weekly_limit_r"] and -week_realized(state) >= rules["weekly_limit_r"] * risk.one_r(state):
        state["week"]["brake"] = True
    state["loss_limit_hit"] = risk.loss_limit_reached(state)
    return net


def reconciles(state, journal_events):
    """This pool's exits in the day's journal and the ledger agree within ₹1 (the two records must match).
    The journal holds every pool, so only events with this pool's name count."""
    journal_net = sum(e.get("net_rs", 0.0) for e in journal_events
                      if e.get("event") == "exit" and e.get("pool") == state["pool"])
    return abs(journal_net - state["realized_today"]) < 1.0
