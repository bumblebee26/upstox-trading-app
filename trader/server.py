"""The MCP server the trading session's Claude uses. Claude has only these tools: no shell, files or web.

  python -m trader.server     run as an MCP server (the session workflow starts it)
"""
import logging
from datetime import datetime

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
except ImportError:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server

from core import upstox
from trader import engine

log = logging.getLogger("upx")
mcp = _Server("upx-trader")
_engine = None


def _e():
    global _engine
    if _engine is None:
        _engine = engine.Engine()
    return _engine


def _safe(fn, *args, **kwargs):
    """A failing call returns its error to Claude instead of ending the session."""
    try:
        return fn(*args, **kwargs)
    except Exception as err:  # noqa: BLE001
        log.exception("tool failed")
        return {"error": f"{type(err).__name__}: {str(err)[:300]}"}


@mcp.tool()
def start_day() -> dict:
    """Start (or resume) today's intraday session: loads the paper ledger, sets today's risk per trade from
    India VIX, and returns the account plus yesterday's FII and DII cash flows. Call once, first."""
    def run():
        view = _e().start_day()
        flows = {}
        for who in ("fii", "dii"):
            try:
                flows[who] = upstox.latest_flow(upstox.flows(who, "NSE_EQ|CASH"))  # {day, buy_cr, sell_cr, net_cr}
            except Exception as err:  # noqa: BLE001 - flows are context only
                flows[who] = f"unavailable: {err}"
        return {"account": view, "flows_previous_day": flows}
    return _safe(run)


@mcp.tool()
def wait_for_open() -> dict:
    """Wait until 09:15 IST (answers Telegram meanwhile). Returns the account."""
    return _safe(lambda: _e().wait_until(_e().now().replace(hour=9, minute=15, second=0, microsecond=0)))


@mcp.tool()
def screen(top: int = 20) -> list:
    """Every NSE stock through the guardrails (₹50+, liquid, tight spread, room to the circuit limits),
    ranked by unusual volume, move from the open, gap and fresh news. Nifty 500 stocks plus any other stock
    with news or a 3%+ move. Returns up to `top` rows with the reasons. Call once per cycle."""
    return _safe(_e().screen, top=top)


@mcp.tool()
def get_facts(symbol: str) -> dict:
    """The facts packet for one stock: day (VWAP, opening ranges, value area, relative volume), 5-minute,
    15-minute and daily indicators and patterns, levels, the quote (spread, circuit room), market context and
    the stock's NSE filings of the last 2 days (results, orders, board outcomes)."""
    return _safe(_e().get_facts, symbol.upper())


@mcp.tool()
def company_news(symbol: str) -> list:
    """Latest news headlines for one stock (Upstox), newest first."""
    def run():
        key = _e()._key(symbol.upper())
        items = upstox.news([key]).get(key, [])
        return [{"heading": i.get("heading"), "summary": (i.get("summary") or "")[:300],
                 "published": datetime.fromtimestamp(i["published_time"] / 1000).strftime("%d %b %H:%M")}
                for i in items[:8] if i.get("published_time")]
    return _safe(run)


@mcp.tool()
def account_status() -> dict:
    """The intraday paper account: balance, today's net P&L after charges, trades, open positions, risk %."""
    return _safe(lambda: engine.ledger_view(_e().state))


@mcp.tool()
def review_trade(symbol: str, side: str, setup: str, entry: float, stop: float, target: float, pros: str,
                 cons: str, agent_yes_pct: int, invalid_if: str) -> dict:
    """Check a trade idea: the risk gate (size from your stop, every limit) and then the quick council
    (skeptic, tape reader, base rate; they see the facts, not your reasons). Returns review_id, qty, risk
    and the council's view, or the reason it is blocked. Then decide with place_trade or skip_trade."""
    return _safe(_e().review_trade, symbol.upper(), side, setup, entry, stop, target, pros, cons, agent_yes_pct,
                 invalid_if)


@mcp.tool()
def place_trade(review_id: str, why: str) -> dict:
    """Place a reviewed trade at the live price (only if still within 0.3% of your entry and the stop isn't hit).
    In human mode it first waits up to 3 minutes for the owner's YES."""
    return _safe(_e().place_trade, review_id, why)


@mcp.tool()
def skip_trade(review_id: str, why: str) -> dict:
    """Decide not to place a reviewed trade, and say why (recorded for the replay)."""
    return _safe(_e().skip_trade, review_id, why)


@mcp.tool()
def adjust_stop(symbol: str, new_stop: float, why: str) -> dict:
    """Tighten or trail an open position's stop. Widening is refused by code."""
    return _safe(_e().adjust_stop, symbol.upper(), new_stop, why)


@mcp.tool()
def exit_position(symbol: str, why: str) -> dict:
    """Close an open position at the live price now."""
    return _safe(_e().exit_position, symbol.upper(), why)


@mcp.tool()
def wait_for_next_candle() -> dict:
    """Wait until 3 s after the next 5-minute candle closes. Meanwhile code checks stops every minute,
    squares off at 15:10 and answers the owner on Telegram. Returns the account. One per cycle."""
    return _safe(_e().wait_for_next_candle)


@mcp.tool()
def end_of_day_report() -> dict:
    """After 15:10: send the day report and check that the ledger and the journal agree within ₹1."""
    return _safe(_e().report)


if __name__ == "__main__":
    mcp.run()
