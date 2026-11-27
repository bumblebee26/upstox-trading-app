"""The morning brief, 08:40 IST on trading days: a few lines before the session starts (dummy money; context only,
never advice). Yesterday's FII and DII cash flows (Upstox), Nifty and India VIX, today's results (NSE calendar)
and yesterday's biggest bulk and block deals (saved by the 19:30 NSE job).

  python -m trader.brief
"""
import json
import logging
from datetime import datetime, timedelta

from core import http, nse, storage, upstox
from trader import telegram

log = logging.getLogger("upx")
MIN_DEAL_RS = 1e7  # deals under ₹1 crore are left out
SHOW = 5


def _cr(rupees, sign=True):
    return _crore(round(rupees / 1e7), sign)


def _crore(v, sign=True):
    return ("-" if v < 0 else "+" if sign and v > 0 else "") + f"₹{abs(v):,} cr"


def _flows(ux):
    parts, day = [], None
    for who in ("fii", "dii"):
        try:
            f = upstox.latest_flow(ux.flows(who, "NSE_EQ|CASH"))
        except (RuntimeError, upstox.UpstoxError) as err:
            log.warning("%s flows unavailable: %s", who, err)
            f = None
        if f:
            parts.append(f"{who.upper()} {_crore(f['net_cr'])}")
            day = f["day"]
    if not parts:
        return ""
    d = datetime.fromisoformat(day)
    return " · ".join(parts) + f" ({d.day} {d:%b})"


def _deals(store, today):
    for back in range(1, 8):  # the last trading day with saved deals
        d = (today - timedelta(days=back)).isoformat()
        bulk = storage.get_json(f"nse/{d}/bulk.json", store=store)
        if bulk is not None:
            rows = bulk + (storage.get_json(f"nse/{d}/block.json", [], store=store) or [])
            big = [r for r in rows if (r.get("qty") or 0) * (r.get("price") or 0) >= MIN_DEAL_RS]
            big.sort(key=lambda r: -(r["qty"] * r["price"]))
            return [f"{r['symbol']}: {r['client']} {'bought' if r['side'] == 'BUY' else 'sold'} "
                    f"{_cr(r['qty'] * r['price'], sign=False)}" for r in big[:3]]
    return []


def run(now=None, store=None, ux=upstox, tg=telegram, fetch=nse.fetch):
    now = now or datetime.now(nse.IST).replace(tzinfo=None)
    today = now.date()
    if today.weekday() >= 5 or any(h.get("date") == today.isoformat() and h.get("holiday_type") == "TRADING_HOLIDAY"
                                   and "NSE" in (h.get("closed_exchanges") or []) for h in ux.holidays()):
        return {"skipped": "no trading today"}
    store = store or storage.backend()
    lines = [f"🌅 {today:%a} {today.day} {today:%b}"]
    flows = _flows(ux)
    if flows:
        lines.append(flows)
    idx = ux.instruments()["index"]
    keys = [idx[n] for n in ("Nifty 50", "India VIX") if n in idx]
    q = ux.quotes(keys) if keys else {}
    nifty, vix = q.get(idx.get("Nifty 50")), q.get(idx.get("India VIX"))
    if nifty and vix:
        prev = nifty["last_price"] - nifty["net_change"]
        lines.append(f"Nifty {nifty['last_price']:,.0f} ({nifty['net_change'] / prev * 100:+.2f}%) · "
                     f"India VIX {vix['last_price']:.2f}")
    try:
        results = [r["symbol"] for r in nse.parse_calendar(json.loads(fetch(nse.CALENDAR_URL)))
                   if r["day"] == today.isoformat() and "result" in (r.get("purpose") or "").lower()]
    except (http.NotFound, RuntimeError, ValueError) as err:
        log.warning("results calendar unavailable: %s", err)
        results = []
    if results:
        more = f" +{len(results) - SHOW} more" if len(results) > SHOW else ""
        lines.append(f"Results today ({len(results)}): {', '.join(results[:SHOW])}{more}")
    lines += _deals(store, today)
    tg.send("\n".join(lines))
    return {"lines": len(lines), "results_today": len(results)}


if __name__ == "__main__":
    print(json.dumps(run()))
