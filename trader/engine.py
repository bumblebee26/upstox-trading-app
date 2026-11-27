"""The intraday engine: what each MCP tool does. The AI decides; this code checks, fills, guards and records.

Flow for a trade: review_trade (risk gate, then the quick council) -> the AI decides -> place_trade (or
skip_trade). Stops: the AI may tighten them (adjust_stop); code fires them (monitor_once, every minute)
and squares everything off at 15:10. Every decision is journaled with its facts packet, so it can be replayed.
"""
import logging
import time
from datetime import date, datetime, timedelta, timezone

from core import costs, journal, nse, storage, upstox
from trader import council, facts, ledger, messages, risk, screen, telegram, universe

log = logging.getLogger("upx")
IST = timezone(timedelta(hours=5, minutes=30))
POOL = "intraday"
STATE_KEY = "state/intraday.json"
TRACK_KEY = "state/track.json"
HEARTBEAT_KEY = "state/heartbeat-intraday.json"  # the session's "still alive" mark, read by the AWS guardian
HEARTBEAT_EVERY_MIN = 4
ENTRY_TOLERANCE_PCT = 0.3
REVIEW_EXPIRY_MIN = 10  # a review older than this must be done again before placing
STALE_MIN = 15          # no new entry when the stock's last 1-minute candle is older than this
BREAKER_PCT = 12.0      # no new entry once the pool is this far below its best balance (until /resume)
SQUARE_OFF = (15, 10)
APPROVAL_WAIT_SEC = 180


class Engine:
    def __init__(self, store=None, data_dir=None, now=None, ux=upstox, tg=telegram, council_fn=council.review,
                 charges=costs.order, sleep=time.sleep, members=None, filings=nse.filings):
        self.store = store or storage.backend()
        self.data_dir = data_dir
        self.now = now or (lambda: datetime.now(IST).replace(tzinfo=None))
        self.ux, self.tg, self.council_fn, self.charges, self.sleep = ux, tg, council_fn, charges, sleep
        self.members, self.filings = members, filings
        self._daily, self._market, self._answers = {}, {}, {}
        self._beat = None
        self._warm = {}

    # ---- state ---------------------------------------------------------------------------------------------
    def _day(self):
        return self.now().date().isoformat()

    def _save(self):
        storage.put_json(STATE_KEY, self.state, store=self.store)

    def _journal(self, event, **fields):
        return journal.append(self._day(), event, base_dir=self.data_dir, mirror=self.store, pool=POOL, **fields)

    def load(self):
        """The pool's saved state, today's journal and the track record; no market calls (the AWS responder
        and guardian use this too). The journal must be restored before anything is appended to it."""
        self.state = storage.get_json(STATE_KEY, store=self.store) or ledger.new_pool(POOL)
        for k, v in (("auto", True), ("reviews", {}), ("msg_index", {}), ("tg_offset", 0)):
            self.state.setdefault(k, v)
        journal.restore(self._day(), base_dir=self.data_dir, mirror=self.store)
        self.track = storage.get_json(TRACK_KEY, [], store=self.store)

    def start_day(self):
        """Load the pool (or start it), restore today's journal, set today's risk from India VIX.
        On an NSE trading holiday it says so on Telegram and returns {"holiday": name}: no session."""
        day = self.now().date()
        closed = [h for h in self.ux.holidays() if h.get("date") == day.isoformat()
                  and h.get("holiday_type") == "TRADING_HOLIDAY" and "NSE" in (h.get("closed_exchanges") or [])]
        late = (self.now().hour, self.now().minute) >= (15, 20)
        if closed or day.weekday() >= 5 or late:
            name = (closed[0].get("description", "NSE holiday") if closed else "weekend" if day.weekday() >= 5
                    else "market closed for the day")
            self.tg.send(f"🏖 No session today: {name}." if name != "market closed for the day" else "🏖 No session: the market has closed for the day.")
            return {"holiday": name}
        self.load()
        self.ins = self.ux.instruments()
        if self.members is None:
            self.members = universe.nifty500(store=self.store)
        new = self.state["day"] != day.isoformat()
        vix_key = self.ins["index"].get("India VIX")
        vix = self.ux.quotes([vix_key]).get(vix_key, {}).get("last_price") if vix_key else None
        ledger.new_day(self.state, day, vix=vix)
        if new:
            self.state.update(reviews={}, msg_index={})
        self.monitor_once()  # stops touched while no session was running (between morning and afternoon)
        for sym, p in list(self.state["positions"].items()):
            if p["opened_at"][:10] < day.isoformat():  # an afternoon session that never ran: never hold overnight
                self.exit_position(sym, why="carried overnight; intraday positions close at the next start",
                                   reason="carried_over")
        self._save()
        self.tg.send(f"☀️ {day:%a %d %b} · intraday {messages.inr(self.state['balance'])} · "
                     f"risk {self.state['day_risk_pct']}% a trade (India VIX {vix if vix is not None else 'unknown'})")
        return ledger_view(self.state)

    # ---- market data -------------------------------------------------------------------------------------------
    def _key(self, symbol):
        info = self.ins["eq"].get(symbol)
        if not info:
            raise KeyError(f"{symbol} is not an NSE stock in today's instrument list")
        return info["key"]

    def _sector(self, symbol):
        return (self.members.get(symbol) or {}).get("industry", "Other")

    def _daily_candles(self, symbol):
        if symbol not in self._daily:
            today = self.now().date()
            self._daily[symbol] = self.ux.historical_candles(self._key(symbol), "days", 1, today - timedelta(days=400),
                                                             today - timedelta(days=1))
        return self._daily[symbol]

    def _warm_1m(self, symbol, daily):
        """The previous trading day's 1-minute candles (one call per stock per day), so the 5m and 15m indicators
        are ready at 09:15. A failure gives [] and the indicators simply warm up later in the day."""
        if symbol not in self._warm:
            day = date.fromisoformat(daily[-1]["ts"][:10]) if daily else None
            try:
                self._warm[symbol] = self.ux.historical_candles(self._key(symbol), "minutes", 1, day, day) if day else []
            except (RuntimeError, upstox.UpstoxError) as err:
                log.warning("warm-up candles for %s failed: %s", symbol, err)
                self._warm[symbol] = []
        return self._warm[symbol]

    def _index_1m(self, name):
        slot = (name, self.now().strftime("%H%M")[:3] + str(self.now().minute // 5))  # refreshed each 5 minutes
        if slot not in self._market:
            key = self.ins["index"].get(name)
            self._market[slot] = self.ux.intraday_candles(key, 1) if key else None
        return self._market[slot]

    def get_facts(self, symbol, quote=None):
        key = self._key(symbol)
        quote = quote or self.ux.quotes([key])[key]
        daily = self._daily_candles(symbol)
        packet = facts.packet(symbol, self.ux.intraday_candles(key, 1), daily, quote,
                              nifty_1m=self._index_1m("Nifty 50"),
                              sector_1m=self._index_1m(universe.sector_index(self._sector(symbol))),
                              warm_1m=self._warm_1m(symbol, daily))
        packet["filings"] = self.filings(symbol)  # NSE filings of the last 2 days (results, orders, board outcomes)
        return packet

    def screen(self, top=20):
        """Every NSE stock through the guardrails; the best `top`, with fresh news counted."""
        self.monitor_once()
        eq = self.ins["eq"]
        by_key = {v["key"]: s for s, v in eq.items()}
        quotes = {by_key[k]: q for k, q in self.ux.quotes(list(by_key)).items() if k in by_key}
        base = self._baseline()
        core = set(self.members)
        first = screen.shortlist(quotes, base, core, set(), self.now(), top=30)
        cutoff = (self.now() - timedelta(hours=1)).timestamp() * 1000
        news = self.ux.news([eq[r["symbol"]]["key"] for r in first]) if first else {}
        fresh = {by_key[k] for k, items in news.items() if k in by_key and
                 any((i.get("published_time") or 0) >= cutoff for i in items)}
        rows = screen.shortlist(quotes, base, core, fresh, self.now(), top=top)
        self._journal("screen", top=[r["symbol"] for r in rows])
        return rows

    def _baseline(self):
        """Average volume and turnover of the Nifty 500, from daily candles, built once a day (about 500 calls)."""
        key = f"baseline/{self._day()}.json"
        base = storage.get_json(key, store=self.store)
        if base is None:
            base = {}
            for sym in self.members:
                if sym in self.ins["eq"]:
                    try:
                        base[sym] = universe.baseline_row(self._daily_candles(sym))
                    except (RuntimeError, upstox.UpstoxError) as err:
                        log.warning("baseline for %s failed: %s", sym, err)
            storage.put_json(key, base, store=self.store)
        return base

    # ---- decisions -----------------------------------------------------------------------------------------------
    def _round_trip(self, key, qty, side, entry, exit_price):
        first = self.charges(key, qty, POOL, side, entry)
        second = self.charges(key, qty, POOL, "SELL" if side == "BUY" else "BUY", exit_price)
        return None if first is None or second is None else first + second

    def _gate(self, symbol, side, entry, stop, target, quote, stale):
        """The risk gate with today's flags: the screen's guardrails (for a stock the AI names itself), the
        circuit breaker and stale prices. Run at review and again just before placing."""
        key, now = self._key(symbol), self.now()
        tradable = bool(screen.shortlist({symbol: quote}, self._baseline(), set(self.members), {symbol}, now))
        peak = self.state.setdefault("peak_balance", self.state["balance"])
        breaker = self.state["balance"] < peak * (1 - BREAKER_PCT / 100)
        return risk.gate(self.state, symbol=symbol, side=side, entry=entry, stop=stop, target=target,
                         sector=self._sector(symbol), now=now,
                         round_trip_charges=lambda q: self._round_trip(key, q, side, entry, target),
                         tradable=tradable, breaker_on=breaker, data_stale=stale)

    def review_trade(self, symbol, side, setup, entry, stop, target, pros, cons, agent_yes_pct, invalid_if):
        key, side = self._key(symbol), side.upper()
        sector = self._sector(symbol)
        quote = self.ux.quotes([key])[key]
        packet = self.get_facts(symbol, quote=quote)
        now = self.now()
        last = packet["time"]
        stale = last is None or (now.hour * 60 + now.minute) - (int(last[:2]) * 60 + int(last[3:])) > STALE_MIN
        g = self._gate(symbol, side, entry, stop, target, quote, stale)
        if not g.allowed:
            self._journal("blocked_by_risk_gate", symbol=symbol, side=side, setup=setup, reason=g.reason)
            return {"allowed": False, "reason": g.reason}
        case = {"symbol": symbol, "side": side, "setup": setup, "entry": entry, "stop": stop, "target": target,
                "gate": {"qty": g.qty, "risk_rs": g.risk_rs, "rr": g.rr}, "facts": packet}
        verdict = self.council_fn(case, self.track)  # members see facts and numbers only, not the AI's reasons
        rid = f"{symbol}-{self.now():%H%M%S}"
        self.state["reviews"][rid] = dict(case, key=key, sector=sector, qty=g.qty, risk_rs=g.risk_rs, rr=g.rr,
                                          at=now.isoformat(timespec="seconds"),
                                          pros=pros, cons=cons, agent_yes_pct=agent_yes_pct, invalid_if=invalid_if,
                                          council=verdict)
        self._journal("review", review_id=rid, **{k: v for k, v in self.state["reviews"][rid].items()})
        self._save()
        return {"allowed": True, "review_id": rid, "qty": g.qty, "risk_rs": g.risk_rs, "rr": g.rr, "council": verdict}

    def _await_owner(self, rid, wait_sec):
        """Human mode: YES/NO buttons; no answer in time means no trade."""
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            self.handle_updates(wait=min(5, max(0, int(deadline - time.monotonic()))))
            if rid in self._answers:
                return self._answers.pop(rid)
        return None

    def place_trade(self, review_id, why, approval_wait_sec=APPROVAL_WAIT_SEC):
        r = self.state["reviews"].pop(review_id, None)  # a review can be placed once
        if not r:
            return {"status": "unknown review"}
        self._save()
        if (self.now() - datetime.fromisoformat(r["at"])).total_seconds() > REVIEW_EXPIRY_MIN * 60:
            self._journal("expired", review_id=review_id)
            return {"status": "expired", "reason": f"reviewed more than {REVIEW_EXPIRY_MIN} minutes ago; review again"}
        args = dict(side=r["side"], symbol=r["symbol"], setup=r["setup"], qty=r["qty"], entry=r["entry"],
                    target=r["target"], stop=r["stop"], risk_rs=r["risk_rs"], rr=r["rr"], pros=r["pros"],
                    cons=r["cons"], council=r["council"])
        decision = "placed by the AI"
        if not self.state["auto"]:
            mid = self.tg.send(messages.proposal(decision="waiting for your YES (3 min)", **args),
                               buttons=[[("✅ YES", f"yes:{review_id}"), ("❌ NO", f"no:{review_id}")]])
            answer = self._await_owner(review_id, approval_wait_sec)
            if answer != "yes":
                self.tg.edit(mid, messages.proposal(decision="not placed (no YES)", **args))
                self._journal("not_approved", review_id=review_id, answer=answer)
                return {"status": "not approved"}
            decision = "placed (you said YES)"
        quote = self.ux.quotes([r["key"]])[r["key"]]
        live = quote["last_price"]
        stop_hit = live <= r["stop"] if r["side"] == "BUY" else live >= r["stop"]
        if abs(live / r["entry"] - 1) * 100 > ENTRY_TOLERANCE_PCT or stop_hit:
            self._journal("missed", review_id=review_id, live=live)
            return {"status": "missed", "live": live}
        traded = quote.get("last_trade_time")
        stale = bool(traded) and (self.now() - datetime.fromtimestamp(int(traded) / 1000, IST).replace(tzinfo=None)
                                  ).total_seconds() > STALE_MIN * 60
        g = self._gate(r["symbol"], r["side"], r["entry"], r["stop"], r["target"], quote, stale)  # limits may have changed
        if not g.allowed:
            self._journal("blocked_by_risk_gate", review_id=review_id, symbol=r["symbol"], reason=g.reason, at="place")
            return {"status": "blocked", "reason": g.reason}
        r["qty"] = min(r["qty"], g.qty)
        args["qty"] = r["qty"]
        fill = ledger.slip(live, r["side"])
        charges = self.charges(r["key"], r["qty"], POOL, r["side"], fill)
        if charges is None:
            self._journal("missed", review_id=review_id, reason="charges unavailable")
            return {"status": "charges unavailable"}
        ledger.open_position(self.state, r["symbol"], r["side"], r["qty"], fill, r["stop"], r["target"], r["sector"],
                             charges=charges, now=self.now())
        mid = self.tg.send(messages.proposal(decision=decision, **dict(args, entry=fill)),
                           buttons=[[("👍", f"rate:{review_id}:up"), ("👎", f"rate:{review_id}:down")],
                                    [("EXIT", f"exit:{r['symbol']}"), ("ℹ️ Full reasons", f"info:{review_id}")]])
        self.state["positions"][r["symbol"]].update(setup=r["setup"], review_id=review_id, msg_id=mid,
                                                    key=r["key"], invalid_if=r["invalid_if"])
        self.state["msg_index"][str(mid)] = review_id
        self._journal("fill", review_id=review_id, symbol=r["symbol"], side=r["side"], qty=r["qty"], price=fill,
                      at=self.now().isoformat(timespec="seconds"),
                      charges_rs=charges, why=why, facts=r["facts"], council=r["council"], pros=r["pros"],
                      cons=r["cons"], agent_yes_pct=r["agent_yes_pct"])
        self._save()
        return {"status": "placed", "fill": fill, "qty": r["qty"], "charges_rs": charges}

    def skip_trade(self, review_id, why):
        r = self.state["reviews"].pop(review_id, None)
        self._journal("skipped", review_id=review_id, symbol=(r or {}).get("symbol"), why=why)
        self._save()
        return {"status": "skipped"}

    def adjust_stop(self, symbol, new_stop, why):
        self.monitor_once()  # finished minutes are judged against the stop that was in force then
        if symbol not in self.state["positions"]:
            return {"ok": False, "reason": f"{symbol} is no longer open (its stop was hit or it was closed)"}
        try:
            ledger.move_stop(self.state, symbol, new_stop)
        except risk.RuleBroken as err:
            return {"ok": False, "reason": str(err)}
        p = self.state["positions"][symbol]
        # The new stop applies from the next minute on; earlier minutes are never judged against it.
        p["checked_until"] = self.now().strftime("%Y-%m-%dT%H:%M")
        self._journal("stop_moved", symbol=symbol, stop=new_stop, why=why)
        self.tg.send(f"🛑 {symbol} stop now {messages.inr(new_stop)} · {why}", reply_to=p.get("msg_id"))
        self._save()
        return {"ok": True, "stop": new_stop}

    def exit_position(self, symbol, why, reason="ai_exit", price=None):
        p = self.state["positions"].get(symbol)
        if not p:
            return {"ok": False, "reason": f"not holding {symbol}"}
        key = p.get("key") or self._key(symbol)
        live = price if price is not None else self.ux.quotes([key])[key]["last_price"]
        side = "SELL" if p["side"] == "BUY" else "BUY"
        fill = ledger.slip(live, side)
        charges = self.charges(key, p["qty"], POOL, side, fill)  # an exit is never blocked by missing charges
        net = ledger.close_position(self.state, symbol, fill, charges=charges or 0.0, now=self.now(), reason=reason)
        self.state["peak_balance"] = max(self.state.get("peak_balance", self.state["balance"]), self.state["balance"])
        self.track.append({"setup": p.get("setup"), "won": net > 0, "day": self._day()})
        storage.put_json(TRACK_KEY, self.track, store=self.store)
        self._journal("exit", symbol=symbol, qty=p["qty"], price=fill, net_rs=net, reason=reason, why=why,
                      charges_rs=charges, charges_pending=charges is None, review_id=p.get("review_id"))
        self.tg.send(messages.exit_note(symbol, p["qty"], fill, net, why or reason), reply_to=p.get("msg_id"))
        self._save()
        return {"ok": True, "net_rs": net, "fill": fill}

    # ---- guarding ---------------------------------------------------------------------------------------------
    def monitor_once(self):
        """Fire stops on the latest 1-minute candle; square everything off from 15:10."""
        now = self.now()
        if self._beat is None or (now - self._beat).total_seconds() >= HEARTBEAT_EVERY_MIN * 60:
            storage.put_json(HEARTBEAT_KEY, {"at": now.isoformat(timespec="seconds")}, store=self.store)
            self._beat = now
        if (now.hour, now.minute) >= SQUARE_OFF:
            for sym in list(self.state["positions"]):
                self.exit_position(sym, why="15:10 square-off", reason="square_off")
            return
        minute = now.strftime("%Y-%m-%dT%H:%M")
        for sym, p in list(self.state["positions"].items()):
            done = p.get("checked_until") or p["opened_at"][:16]  # the fill's own minute is never counted
            for c in self.ux.intraday_candles(p.get("key") or self._key(sym), 1):
                ts = c["ts"][:16]
                if ts <= done:
                    continue
                if p["side"] == "BUY" and c["low"] <= p["stop"]:
                    self.exit_position(sym, why="stop hit", reason="stop", price=min(p["stop"], c["open"]))
                    break
                if p["side"] == "SELL" and c["high"] >= p["stop"]:
                    self.exit_position(sym, why="stop hit", reason="stop", price=max(p["stop"], c["open"]))
                    break
                if ts < minute:  # a finished minute; the one still forming is checked again next time
                    p["checked_until"] = ts
        if self.state["positions"]:
            self._save()  # so the next session starts checking where this one stopped

    def handle_updates(self, wait=0):
        updates, self.state["tg_offset"] = self.tg.poll(self.state["tg_offset"], wait=wait)
        for u in updates:
            if u["kind"] == "command":
                self._command(u["text"])
            elif u["kind"] == "button":
                self._button(u)
            elif u["kind"] == "reaction" and u.get("emoji") in ("👍", "👎"):
                rid = self.state["msg_index"].get(str(u["message_id"]))
                if rid:
                    self._journal("rating", review_id=rid, rating="up" if u["emoji"] == "👍" else "down", via="reaction")
        if updates:
            self._save()
        return len(updates)

    def _command(self, text):
        cmd, *rest = text.split()
        cmd = cmd.lower().split("@")[0]
        if cmd in ("/pause", "/stop"):
            self.state["paused" if cmd == "/pause" else "stopped"] = True
            self.tg.send("⏸ No new entries until /resume. Open positions are still managed.")
        elif cmd == "/resume":  # also resets the circuit breaker's peak to today's balance
            self.state.update(paused=False, stopped=False, peak_balance=self.state["balance"])
            self.tg.send("▶️ New entries allowed again.")
        elif cmd == "/auto" and rest:
            self.state["auto"] = rest[0].lower() == "on"
            self.tg.send("Auto mode " + ("ON: the AI places trades itself." if self.state["auto"] else
                                         "OFF: each trade waits for your YES."))
        elif cmd in ("/ledger", "/balance", "/status"):
            self.tg.send(messages.ledger(self.state))
        elif cmd == "/exit" and rest:
            self.exit_position(rest[0].upper(), why="you asked", reason="owner_exit")
        else:
            self.tg.send("/ledger · /exit SYMBOL · /pause · /resume · /stop · /auto on|off")

    def _button(self, u):
        kind, _, rest = u["data"].partition(":")
        self.tg.answer_button(u["id"])
        if kind == "exit":
            self.exit_position(rest, why="you asked", reason="owner_exit")
        elif kind == "rate":
            rid, _, rating = rest.rpartition(":")
            self._journal("rating", review_id=rid, rating=rating, via="button")
        elif kind in ("yes", "no"):
            self._answers[rest] = kind
        elif kind == "info":
            r = self.state["reviews"].get(rest)
            if r:
                members = r["council"]["members"]
                self.tg.send("\n".join([f"ℹ️ {r['symbol']} {r['setup']}", f"➕ {r['pros']}", f"➖ {r['cons']}",
                                        f"Exit early if: {r['invalid_if']}"] +
                                       [f"{n}: {m.get('yes_pct', '-')} {m.get('why', m.get('error', ''))}"
                                        for n, m in members.items()]))

    def wait_for_next_candle(self):
        """Until 3 s after the next 5-minute candle closes: answer Telegram, check stops every minute."""
        now = self.now()
        return self.wait_until(now.replace(second=0, microsecond=0) + timedelta(minutes=5 - now.minute % 5, seconds=3))

    def wait_until(self, nxt):
        """Answer Telegram and check stops every minute until the time `nxt` (IST, no time zone)."""
        last_check = None
        while self.now() < nxt:
            if last_check is None or (self.now() - last_check).total_seconds() >= 60:
                self.monitor_once()
                last_check = self.now()
            left = (nxt - self.now()).total_seconds()
            if self.handle_updates(wait=int(max(0, min(25, left)))) == 0 and left > 0:
                self.sleep(min(1, left))
        self.monitor_once()  # once more at the end, so the 15:10 square-off can't fall between checks
        return ledger_view(self.state)

    def report(self):
        if (self.now().hour, self.now().minute) >= SQUARE_OFF:
            self.monitor_once()  # nothing intraday stays open overnight
        events = journal.read(self._day(), base_dir=self.data_dir)
        exits = [e for e in events if e["event"] == "exit" and e.get("pool") == POOL]
        ok = ledger.reconciles(self.state, events)
        wins = sum(1 for e in exits if e["net_rs"] > 0)
        text = (f"📒 Day report · {len(exits)} trades · {wins} won · {messages.inr(self.state['realized_today'], sign=True)}"
                f" after charges\nBalance {messages.inr(self.state['balance'])} · ledger and journal "
                + ("agree ✅" if ok else "DISAGREE ⚠️"))
        self.tg.send(text)
        self._journal("report", trades=len(exits), net_rs=self.state["realized_today"], reconciled=ok)
        self._save()
        return {"trades": len(exits), "net_rs": self.state["realized_today"], "reconciled": ok}


def heartbeat_age_min(store, now):
    """Whole minutes since a session last said it was alive, or None if none ever did."""
    beat = storage.get_json(HEARTBEAT_KEY, store=store)
    if not beat:
        return None
    return int((now - datetime.fromisoformat(beat["at"])).total_seconds() // 60)


def ledger_view(state):
    return {"balance": state["balance"], "realized_today": state["realized_today"],
            "trades_today": state["trades_today"], "risk_pct": state["day_risk_pct"],
            "open": {s: {k: p[k] for k in ("side", "qty", "fill_price", "stop", "target")}
                     for s, p in state["positions"].items()},
            "paused": state["paused"] or state["stopped"], "auto": state.get("auto", True)}
