"""A daily-bar paper ledger for the swing and long-term shadows and the NIFTYBEES benchmarks.

Orders placed after a close fill at the next open (+0.05% slippage on buys, -0.05% on sells); exits decided
on a close fill at that close (as the real pools' stops do). Costs are Upstox's charges (delivery, with the DP
charge on sells, via core.costs). Each ledger keeps its cash, holdings, closed trades and daily value.
"""
SLIPPAGE = 0.0005


def new(capital):
    return {"capital": float(capital), "cash": float(capital), "holdings": {}, "pending": [], "closed": [],
            "equity": [], "invested_so_far": 0.0}


def _slip(price, side):
    return round(price * (1 + SLIPPAGE) if side == "BUY" else price * (1 - SLIPPAGE), 2)


def order_buy(p, symbol, amount, stop, top_up=False, **extra):
    """A buy for the next open. top_up=True adds to a holding (the SIP benchmark); otherwise one per stock."""
    if (top_up or symbol not in p["holdings"]) and not any(o["symbol"] == symbol for o in p["pending"]):
        p["pending"].append({"side": "BUY", "symbol": symbol, "amount": amount, "stop": stop, "top_up": top_up,
                             **extra})


def order_sell(p, symbol, reason):
    if symbol in p["holdings"] and not any(o["symbol"] == symbol and o["side"] == "SELL" for o in p["pending"]):
        p["pending"].append({"side": "SELL", "symbol": symbol, "reason": reason})


def _close(p, symbol, price, day, reason, keys, charges, pool):
    h = p["holdings"].pop(symbol)
    fill = _slip(price, "SELL")
    cost = charges(keys[symbol], h["qty"], pool, "SELL", fill) or 0.0
    p["cash"] = round(p["cash"] + fill * h["qty"] - cost, 2)
    net = round((fill - h["entry"]) * h["qty"] - h["charges"] - cost, 2)
    p["closed"].append({"symbol": symbol, "entry_day": h["day"], "exit_day": day, "entry": h["entry"], "exit": fill,
                        "qty": h["qty"], "net_rs": net, "reason": reason})


def exit_on_close(p, symbol, close, day, reason, keys, charges, pool):
    if symbol in p["holdings"]:
        _close(p, symbol, close, day, reason, keys, charges, pool)


def fill_and_value(p, day, bars, keys, charges, pool):
    """Fill yesterday's orders at today's open (sells first, to free cash), then value the ledger at the close."""
    for o in sorted(p["pending"], key=lambda o: o["side"] != "SELL"):
        b = bars.get(o["symbol"])
        if not b:
            continue  # no price today: the order lapses
        if o["side"] == "SELL":
            if o["symbol"] in p["holdings"]:
                _close(p, o["symbol"], b["open"], day, o.get("reason", "rule"), keys, charges, pool)
            continue
        price = _slip(b["open"], "BUY")
        qty = int(min(o["amount"], p["cash"]) // price)
        while qty > 0:
            cost = charges(keys[o["symbol"]], qty, pool, "BUY", price)
            if cost is None:
                qty = 0
                break
            if qty * price + cost <= p["cash"]:
                break
            qty -= 1
        if qty < 1:
            continue
        p["cash"] = round(p["cash"] - qty * price - cost, 2)
        p["invested_so_far"] = round(p["invested_so_far"] + qty * price, 2)
        held = p["holdings"].get(o["symbol"])
        if held and o.get("top_up"):
            qty_all = held["qty"] + qty
            held.update(entry=round((held["entry"] * held["qty"] + price * qty) / qty_all, 4), qty=qty_all,
                        charges=round(held["charges"] + cost, 2))
            continue
        extra = {k: v for k, v in o.items() if k not in ("side", "symbol", "amount", "stop", "top_up")}
        p["holdings"][o["symbol"]] = {"qty": qty, "entry": price, "charges": cost, "day": day, "stop": o["stop"],
                                      "high_close": b["close"], "high_high": b["high"], **extra}
    p["pending"] = []
    for sym, h in p["holdings"].items():
        b = bars.get(sym)
        if b:
            h["bars"] = h.get("bars", 0) + 1  # trading days held, the fill day counting as the first
            h["last"] = b["close"]
            h["high_close"] = max(h["high_close"], b["close"])
            h["high_high"] = max(h["high_high"], b["high"])
    value = p["cash"] + sum(h["qty"] * h.get("last", h["entry"]) for h in p["holdings"].values())
    p["equity"] = [e for e in p["equity"] if e[0] != day] + [[day, round(value, 2)]]
    return value


def revalue(p, day):
    """Today's value again after exits on the close (prices already set by fill_and_value)."""
    value = p["cash"] + sum(h["qty"] * h.get("last", h["entry"]) for h in p["holdings"].values())
    p["equity"] = [e for e in p["equity"] if e[0] != day] + [[day, round(value, 2)]]
    return value


def equity_now(p):
    return p["equity"][-1][1] if p["equity"] else p["capital"]


def rebalance(p, targets, weight, closes):
    """Hold exactly `targets` (equal weight of the ledger's value each): sell the rest, buy the new ones."""
    for sym in list(p["holdings"]):
        if sym not in targets:
            order_sell(p, sym, "rebalance")
    for sym in targets:
        if sym not in p["holdings"] and closes.get(sym):
            order_buy(p, sym, amount=equity_now(p) * weight, stop=0.0)


def sip_amount(p, months=12):
    """Monthly SIP instalment: the pool's capital spread over `months` months."""
    return round(p["capital"] / months, 2)
