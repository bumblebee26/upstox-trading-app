"""The risk gate: ordinary code that every trade must pass, whatever the AI argues.

It checks the trade against the pool's limits and sizes it from the AI's stop, so a wider stop means fewer
shares for the same rupee risk. A refusal says why, in words the owner can read.
Intraday limits are paper-trader's live rules of 26 Nov 2026; swing and long-term caps are the old live pools'.
"""
import math
from dataclasses import dataclass
from datetime import datetime, time

from trader import ledger


class RuleBroken(Exception):
    """A request that the money rules never allow (for example widening a stop)."""


_COMMON = {"min_price": 50.0, "max_cost_share_pct": 30.0, "slippage_pct": 0.05}
POOLS = {
    "intraday": dict(_COMMON, capital=40_000, leverage=5.0, risk_pct=1.0, vix_scaled=True, max_open=5,
                     max_trades_day=10, max_position_pct=30.0, shorts=True, entry_window=(time(9, 30), time(14, 30)),
                     max_open_per_sector=1, max_trades_per_sector=2, cooloff_after=3, cooloff_min=30,
                     daily_limit_r=4.0, weekly_limit_r=8.0, brake_factor=0.5, min_rr=1.5, floor_pct=None),
    "swing": dict(_COMMON, capital=60_000, leverage=1.0, risk_pct=2.0, vix_scaled=False, max_open=7,
                  max_trades_day=None, max_position_pct=25.0, shorts=False, entry_window=None,
                  max_open_per_sector=None, max_trades_per_sector=None, cooloff_after=None, cooloff_min=None,
                  daily_limit_r=None, weekly_limit_r=None, brake_factor=1.0, min_rr=None, floor_pct=None),
    "long_term": dict(_COMMON, capital=100_000, leverage=1.0, risk_pct=None, vix_scaled=False, max_open=10,
                      max_trades_day=None, max_position_pct=15.0, shorts=False, entry_window=None,
                      max_open_per_sector=None, max_trades_per_sector=None, cooloff_after=None, cooloff_min=None,
                      daily_limit_r=None, weekly_limit_r=None, brake_factor=1.0, min_rr=None, floor_pct=25.0),
}


@dataclass
class GateResult:
    allowed: bool
    reason: str
    qty: int = 0
    risk_rs: float = 0.0
    rr: float = 0.0


def risk_pct_for_vix(vix):
    """Intraday risk per trade from India VIX: 1%; 0.75% at 20+ (or when VIX is unknown); 0.5% at 30+."""
    if vix is None:
        return 0.75
    return 0.5 if vix >= 30 else 0.75 if vix >= 20 else 1.0


def one_r(state):
    """1R: one trade's planned risk today (start-of-day balance x today's risk %)."""
    return state["day_start_balance"] * (state["day_risk_pct"] or 0) / 100


def loss_limit_reached(state):
    limit_r = POOLS[state["pool"]]["daily_limit_r"]
    return bool(limit_r) and -state["realized_today"] >= limit_r * one_r(state)


def gate(state, *, symbol, side, entry, stop, target, sector, now: datetime, round_trip_charges,
         tradable=True, breaker_on=False, data_stale=False):
    """Check one proposed trade. round_trip_charges(qty) returns Upstox's charges for the entry and exit orders
    in rupees, or None when Upstox can't be reached (then no new entry)."""
    rules = POOLS[state["pool"]]
    side = side.upper()
    per_share = abs(entry - stop)
    if side not in ("BUY", "SELL") or per_share <= 0:
        return GateResult(False, "side must be BUY or SELL and the stop must differ from the entry")
    if side == "SELL" and not rules["shorts"]:
        return GateResult(False, f"the {state['pool']} pool buys only")
    if (side == "BUY" and not (stop < entry < target)) or (side == "SELL" and not (target < entry < stop)):
        return GateResult(False, "for a buy need stop < entry < target; for a short, target < entry < stop")
    rr = round(abs(target - entry) / per_share, 2)

    def no(reason):
        return GateResult(False, reason, rr=rr)

    if not tradable:
        return no(f"{symbol} isn't on the tradable list")
    if entry < rules["min_price"]:
        return no(f"price under ₹{rules['min_price']:g}: no penny stocks")
    if state["stopped"]:
        return no("stopped by you with /stop (send /resume to restart)")
    if breaker_on:
        return no("portfolio circuit breaker: total value is 12% below its peak; send /resume after reviewing")
    if state["paused"]:
        return no("paused by you on Telegram (send /resume)")
    if data_stale:
        return no("prices look stale right now; no new entries until they're fresh")
    window = rules["entry_window"]
    if window and not (now.weekday() < 5 and window[0] <= now.time() <= window[1]):
        return no(f"outside the entry window {window[0]:%H:%M}-{window[1]:%H:%M} (weekdays)")
    if symbol in state["positions"]:
        return no(f"already holding {symbol}")
    if len(state["positions"]) >= rules["max_open"]:
        return no(f"max {rules['max_open']} open positions reached")
    if rules["max_trades_day"] and state["trades_today"] >= rules["max_trades_day"]:
        return no(f"all {rules['max_trades_day']} trades for today are used")
    if state["cooloff_until"] and now.isoformat(timespec="seconds") < state["cooloff_until"]:
        return no(f"cool-off after {state['loss_streak']} losses in a row, until {state['cooloff_until'][11:16]}")
    if rules["max_open_per_sector"]:
        same = [s for s, p in state["positions"].items() if p["sector"] == sector]
        if len(same) >= rules["max_open_per_sector"]:
            return no(f"already holding {', '.join(same)} in {sector}; at most {rules['max_open_per_sector']} "
                      "open per sector")
    if rules["max_trades_per_sector"] and state["sector_trades"].get(sector, 0) >= rules["max_trades_per_sector"]:
        return no(f"already {rules['max_trades_per_sector']} {sector} trades today")
    if loss_limit_reached(state):
        return no(f"daily loss limit reached (today ₹{state['realized_today']:,.0f}); it lifts if a winning exit "
                  "brings the loss back under")
    if rules["min_rr"] and rr < rules["min_rr"]:
        return no(f"risk-reward {rr} is below the minimum {rules['min_rr']}")
    if rules["floor_pct"] and stop < entry * (1 - rules["floor_pct"] / 100):
        return no(f"the stop is more than {rules['floor_pct']:g}% below the entry (the long-term floor)")

    # Size: risk-based quantity (if the pool sizes by risk), capped by free cash or margin and the position cap.
    leverage = rules["leverage"]
    cap_qty = math.floor(state["balance"] * rules["max_position_pct"] / 100 * leverage / entry)
    free_qty = math.floor(ledger.free_margin(state) * leverage / entry)
    full_qty = cap_qty
    qty = min(cap_qty, free_qty)
    if state["day_risk_pct"]:
        budget = state["balance"] * state["day_risk_pct"] / 100
        full_qty = min(cap_qty, math.floor(budget / per_share))
        if state["week"]["brake"]:
            budget *= rules["brake_factor"]
        if rules["daily_limit_r"]:
            room = rules["daily_limit_r"] * one_r(state) - max(0.0, -state["realized_today"]) - ledger.open_risk(state)
            if room < per_share:
                return no("no room left under the daily loss limit, counting the open positions' risk")
            budget = min(budget, room)
        qty = min(qty, math.floor(budget / per_share))
    if qty < 1:
        return no("not enough free money for even 1 share")

    # Costs judged at full size: a trade shrunk by the brake or the loss room pays the same per-order charges.
    charges = round_trip_charges(max(1, full_qty))
    if charges is None:
        return no("Upstox charges unavailable right now; no new entries until they are")
    costs = charges + 2 * entry * max(1, full_qty) * rules["slippage_pct"] / 100
    share = costs / (max(1, full_qty) * per_share) * 100
    if share > rules["max_cost_share_pct"]:
        return no(f"costs (Upstox charges + slippage) would be {share:.0f}% of the risk "
                  f"(max {rules['max_cost_share_pct']:g}%): the stop is too tight for the costs")
    return GateResult(True, "ok", qty, round(qty * per_share, 2), rr)
