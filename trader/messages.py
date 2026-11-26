"""Telegram message text: short, plain, no "[MOCK]" prefix (the bot's name says paper trading)."""


def _group(n):
    """Indian digit grouping: 12345678 -> 1,23,45,678."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + parts) + "," + tail


def inr(x, sign=False):
    """₹ with Indian grouping; paise only below ₹1,000 when there are any."""
    neg = x < 0
    v = abs(x)
    body = f"{v:.2f}" if v < 1000 and round(v, 2) != int(v) else _group(int(round(v)))
    return ("-" if neg else "+" if sign and x > 0 else "") + "₹" + body


def proposal(*, side, symbol, setup, qty, entry, target, stop, risk_rs, rr, pros, cons, council, decision):
    head = "🟢 BUY" if side == "BUY" else "🔴 SHORT"
    score = f" · council {council['yes_pct']:.0f}%" if council else ""
    lines = [f"{head} {symbol} · {setup}{score}",
             f"{qty} @ {inr(entry)} · 🎯 {inr(target)} · 🛑 {inr(stop)} · risk {inr(risk_rs)} · {rr:.1f}R"]
    if pros:
        lines.append(f"➕ {pros}")
    if cons:
        lines.append(f"➖ {cons}")
    if council:
        m = council["members"]
        bits = [f"{name} {m[key]['yes_pct']:.0f}" for key, name in (("skeptic", "skeptic"), ("tape", "tape"),
                                                                    ("base_rate", "base")) if "yes_pct" in m.get(key, {})]
        n = m.get("base_rate", {}).get("n")
        lines.append("🤖 " + " · ".join(bits) + (f" ({n} earlier)" if n else ""))
    lines.append(f"Decision: {decision}")
    return "\n".join(lines)


def exit_note(symbol, qty, price, net_rs, reason):
    icon = "✅" if net_rs >= 0 else "❌"
    return f"{icon} {symbol} closed · {qty} @ {inr(price)} · {inr(net_rs, sign=True)} after charges · {reason}"


def ledger(state):
    held = ", ".join(f"{s} {p['qty']} @ {inr(p['fill_price'])} (🛑 {inr(p['stop'])})" for s, p in state["positions"].items())
    return (f"Intraday {inr(state['balance'])} · today {inr(state['realized_today'], sign=True)} · "
            f"{state['trades_today']} trades\nOpen: {held or 'none'}")
