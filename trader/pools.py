"""The swing and long-term pools: one job a day after the close (15:50 IST), and Saturdays for long-term.

Each run, for one pool:
1. Fill yesterday's decisions at today's open (with slippage and Upstox charges; the risk gate runs again).
2. Fire stops on today's close.
3. Decide (swing every trading day; long-term on Saturdays, or on a weekday when a holding has news):
   code ranks candidates, the AI makes a first plan, the full council reviews it and the AI as chair decides.
4. The final plan becomes tomorrow's orders: buys sized by the risk gate, sells, stops (tighten only).

  python -m trader.pools swing|long_term
"""
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from core import costs, journal, storage, upstox
from trader import facts, ledger, llm_council, messages, rank, risk, telegram, universe
from trader.council import run_claude

log = logging.getLogger("upx")
IST = timezone(timedelta(hours=5, minutes=30))
NAMES = {"swing": "📈 Swing", "long_term": "🌳 Long-term"}
OBJECTIVE = {"swing": "the highest profit per position over a hold of days to a few weeks",
             "long_term": "the highest profit per position over months to years, buying quality at a fair price"}

_DECIDE = """You are the trader for a PAPER {pool} stock pool on NSE (dummy money). Objective: {objective}, after
costs. Code enforces the limits: {limits}. Stops may only be tightened, never widened.
From the holdings and the candidates below, give your plan as one JSON object and nothing else:
{{"buys": [{{"symbol", "stop", "target", "why"}}], "sells": [{{"symbol", "why"}}],
"stops": [{{"symbol", "new_stop", "why"}}], "notes": "<one sentence>"}}
Buy only from the candidates; every buy needs a stop below today's close and a target above it.
CONTEXT: {context}"""


def ai_plan(pool, context):
    rules = risk.POOLS[pool]
    limits = (f"at most {rules['max_open']} holdings, {rules['max_position_pct']:g}% of the pool per stock"
              + (f", stop no more than {rules['floor_pct']:g}% below the entry" if rules["floor_pct"] else ""))
    text = run_claude(_DECIDE.format(pool=pool, objective=OBJECTIVE[pool], limits=limits,
                                     context=json.dumps(context, separators=(",", ":"))), 240, "opus")
    return llm_council._json(text)


class DeliveryPool:
    def __init__(self, pool, store=None, data_dir=None, now=None, ux=upstox, tg=telegram, decide_fn=ai_plan,
                 council_fn=llm_council.review, charges=costs.order, members=None):
        self.pool, self.key = pool, f"state/{pool}.json"
        self.store = store or storage.backend()
        self.data_dir = data_dir
        self.now = now or (lambda: datetime.now(IST).replace(tzinfo=None))
        self.ux, self.tg, self.decide_fn, self.council_fn, self.charges = ux, tg, decide_fn, council_fn, charges
        self.members = members
        self.notes = []

    def _journal(self, event, **fields):
        journal.append(self.day, event, base_dir=self.data_dir, mirror=self.store, name=self.pool, pool=self.pool,
                       **fields)

    def _gate(self, sym, entry, stop, target):
        key = self.ins["eq"][sym]["key"]
        return risk.gate(self.state, symbol=sym, side="BUY", entry=entry, stop=stop, target=target,
                         sector=self.members.get(sym, {}).get("industry", "Other"), now=self.now(),
                         round_trip_charges=lambda q: self._round_trip(key, q, entry, target),
                         tradable=sym in self.members)

    def _round_trip(self, key, qty, entry, exit_price):
        a = self.charges(key, qty, self.pool, "BUY", entry)
        b = self.charges(key, qty, self.pool, "SELL", exit_price)
        return None if a is None or b is None else a + b

    def _exit(self, sym, price, reason, why):
        p = self.state["positions"][sym]
        fill = ledger.slip(price, "SELL")
        charges = self.charges(p["key"], p["qty"], self.pool, "SELL", fill)
        net = ledger.close_position(self.state, sym, fill, charges=charges or 0.0, now=self.now(), reason=reason)
        self._journal("exit", symbol=sym, qty=p["qty"], price=fill, net_rs=net, reason=reason, why=why,
                      charges_rs=charges, charges_pending=charges is None)
        self.notes.append(messages.exit_note(sym, p["qty"], fill, net, why))

    def run_day(self):
        now = self.now()
        self.day = now.date().isoformat()
        closed = [h for h in self.ux.holidays() if h.get("date") == self.day and h.get("holiday_type") ==
                  "TRADING_HOLIDAY" and "NSE" in (h.get("closed_exchanges") or [])]
        weekend = now.weekday() >= 5
        if closed and not weekend:
            return {"skipped": closed[0].get("description", "NSE holiday")}
        if weekend and not (self.pool == "long_term" and now.weekday() == 5):
            return {"skipped": "weekend"}
        trading_day = not weekend
        self.ins = self.ux.instruments()
        if self.members is None:
            self.members = universe.nifty500(store=self.store)
        journal.restore(self.day, base_dir=self.data_dir, mirror=self.store, name=self.pool)
        self.state = storage.get_json(self.key, store=self.store) or ledger.new_pool(self.pool)
        self.state.setdefault("pending", [])
        if trading_day:
            ledger.new_day(self.state, now.date())
        held = {s: p for s, p in self.state["positions"].items()}
        keys = {s: self.ins["eq"][s]["key"] for s in set(held) | {o["symbol"] for o in self.state["pending"]}
                if s in self.ins["eq"]}
        quotes = {s: q for s, q in ((s, self.ux.quotes([k]).get(k)) for s, k in keys.items()) if q}

        if trading_day:
            self._fill_pending(quotes)
            for sym, p in list(self.state["positions"].items()):  # stops on today's close
                close = (quotes.get(sym) or {}).get("last_price")
                if close is not None and close <= p["stop"]:
                    self._exit(sym, close, "stop", "closed under its stop")
        storage.put_json(self.key, self.state, store=self.store)  # fills and stops are saved before any decision
        decided = None
        try:
            if self._decision_day(now, trading_day):
                decided = self._decide(quotes, trading_day)
        except Exception as err:  # noqa: BLE001 - a failed decision must never lose the day's fills
            log.exception("decision failed")
            self.state["pending"] = []
            self.notes.append(f"⚠️ decision failed ({type(err).__name__}: {str(err)[:120]}); no new orders today")
            self._journal("decision_failed", error=str(err)[:300])
        storage.put_json(self.key, self.state, store=self.store)
        self._report(decided)
        return {"pending": self.state["pending"], "notes": self.notes, "decided": decided is not None}

    def _fill_pending(self, quotes):
        for order in self.state["pending"]:
            sym, q = order["symbol"], quotes.get(order["symbol"])
            if not q:
                self.notes.append(f"{sym}: no price today, order dropped")
                continue
            open_ = (q.get("ohlc") or {}).get("open") or q["last_price"]
            if order["side"] == "SELL":
                if sym in self.state["positions"]:
                    self._exit(sym, open_, "ai_sell", order["why"])
                continue
            fill = ledger.slip(open_, "BUY")
            g = self._gate(sym, fill, order["stop"], order["target"])  # the limits may have changed overnight
            if not g.allowed:
                self.notes.append(f"{sym}: buy not filled ({g.reason})")
                self._journal("blocked_by_risk_gate", symbol=sym, reason=g.reason, at="fill")
                continue
            qty = min(order["qty"], g.qty)
            key = self.ins["eq"][sym]["key"]
            charges = self.charges(key, qty, self.pool, "BUY", fill)
            if charges is None:
                self.notes.append(f"{sym}: buy not filled (Upstox charges unavailable)")
                continue
            ledger.open_position(self.state, sym, "BUY", qty, fill, order["stop"], order["target"],
                                 self.members.get(sym, {}).get("industry", "Other"), charges=charges, now=self.now())
            self.state["positions"][sym]["key"] = key
            self._journal("fill", symbol=sym, side="BUY", qty=qty, price=fill, charges_rs=charges, why=order["why"])
            self.notes.append(f"Bought {sym} {qty} @ {messages.inr(fill)} (🛑 {messages.inr(order['stop'])})")
        self.state["pending"] = []

    def _decision_day(self, now, trading_day):
        if self.pool == "swing":
            return trading_day
        if now.weekday() == 5:
            return True
        keys = [p["key"] for p in self.state["positions"].values() if p.get("key")]
        cutoff = (now - timedelta(days=1)).timestamp() * 1000
        news = self.ux.news(keys) if keys else {}
        return any((i.get("published_time") or 0) >= cutoff for items in news.values() for i in items)

    def _candidates(self):
        today = self.now().date()
        if self.pool == "swing":
            daily = {}
            for sym in self.members:
                if sym in self.ins["eq"]:
                    try:
                        daily[sym] = self.ux.historical_candles(self.ins["eq"][sym]["key"], "days", 1,
                                                                today - timedelta(days=400), today)
                    except (RuntimeError, upstox.UpstoxError) as err:
                        log.warning("daily candles for %s failed: %s", sym, err)
            return rank.swing(daily, top=10), daily
        ratios = {}
        for sym in self.members:
            info = self.ins["eq"].get(sym)
            if info and info.get("isin"):
                try:
                    ratios[sym] = self.ux.fundamentals(info["isin"], "key-ratios")
                except (RuntimeError, upstox.UpstoxError) as err:
                    log.warning("key ratios for %s failed: %s", sym, err)
        return rank.long_term(ratios, top=10), {}

    def _decide(self, quotes, trading_day):
        cands, daily = self._candidates()
        close = {s: q["last_price"] for s, q in quotes.items()}
        for c in cands:
            close.setdefault(c["symbol"], c.get("close"))
        missing = [c["symbol"] for c in cands if close.get(c["symbol"]) is None]
        for sym, q in self.ux.quotes([self.ins["eq"][s]["key"] for s in missing]).items() if missing else []:
            close[next(s for s in missing if self.ins["eq"][s]["key"] == sym)] = q["last_price"]
        held = {s: {"qty": p["qty"], "entry": p["fill_price"], "stop": p["stop"], "target": p["target"],
                    "close": close.get(s), "since": p["opened_at"][:10]} for s, p in self.state["positions"].items()}
        context = {"pool": self.pool, "date": self.day, "balance": self.state["balance"],
                   "free_cash": round(ledger.free_margin(self.state), 2), "holdings": held, "candidates": cands,
                   "daily": {s: facts.packet(s, [], d, {"last_price": close.get(s)})["tf"]["daily"]
                             for s, d in daily.items() if s in held or s in {c["symbol"] for c in cands}}}
        plan = self.decide_fn(self.pool, context)
        verdict = self.council_fn(self.pool, context, plan)
        final = verdict["final"]
        self._journal("decision", plan=plan, final=final, council=verdict, context=context)

        for s in final.get("stops") or []:
            sym = s.get("symbol")
            try:
                ledger.move_stop(self.state, sym, float(s["new_stop"]))
                self.notes.append(f"{sym} 🛑 now {messages.inr(float(s['new_stop']))}")
            except risk.RuleBroken:
                self.notes.append(f"{sym}: stop move refused (stops never widen)")
            except (KeyError, TypeError, ValueError):
                self.notes.append(f"{sym}: stop move ignored (not held or no price)")
        pending = [{"side": "SELL", "symbol": s["symbol"], "why": s.get("why", "")} for s in final.get("sells") or []
                   if s.get("symbol") in self.state["positions"]]
        for b in final.get("buys") or []:
            sym = b.get("symbol")
            try:
                stop, target, price = float(b["stop"]), float(b["target"]), close[sym]
            except (KeyError, TypeError, ValueError):
                self.notes.append(f"{sym}: buy ignored (needs a stop, a target and a price)")
                continue
            g = self._gate(sym, price, stop, target)
            if not g.allowed:
                self.notes.append(f"{sym}: buy refused by the risk gate ({g.reason})")
                continue
            pending.append({"side": "BUY", "symbol": sym, "qty": g.qty, "stop": stop, "target": target,
                            "why": b.get("why", "")})
        self.state["pending"] = pending
        if final.get("notes"):
            self.notes.append(f"Council: {final['notes']}")
        return final

    def _report(self, decided):
        lines = [f"{NAMES[self.pool]} · {self.now():%d %b} · {messages.inr(self.state['balance'])} · "
                 f"today {messages.inr(self.state['realized_today'], sign=True)}"]
        lines += self.notes
        orders = [f"{o['side']} {o['symbol']}" + (f" {o['qty']} (🛑 {messages.inr(o['stop'])})" if o["side"] == "BUY"
                                                    else "") for o in self.state["pending"]]
        if decided is not None:
            lines.append("Next open: " + (", ".join(orders) if orders else "no orders"))
        held = ", ".join(f"{s} {p['qty']}" for s, p in self.state["positions"].items())
        lines.append(f"Holding: {held or 'cash only'}")
        rid = f"{self.pool}-{self.day}"
        self.tg.send("\n".join(lines), buttons=[[("👍", f"rate:{rid}:up"), ("👎", f"rate:{rid}:down")]])


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in ("swing", "long_term"):
        sys.exit("usage: python -m trader.pools swing|long_term")
    print(json.dumps(DeliveryPool(name).run_day(), default=str)[:2000])
