"""AWS Lambda, every 5 minutes from 09:10 to 15:20 on weekdays: the safety net for the intraday session.

- No session started by 09:10: one Telegram alert.
- A session started but has been silent for 15 minutes (no heartbeat): one alert per silence.
- From 15:12, if the session is silent and intraday positions are still open: close them on paper at the
  last price (reason guardian_square_off) and say so. Intraday positions never stay open overnight.
A live session is never touched. Dummy money only.
"""
import tempfile
from datetime import datetime

from core import costs, storage, upstox
from trader import engine, telegram

STALE_MIN = 15
CLOSE_FROM = (15, 12)
WATCH = ((9, 10), (15, 20))


def run(now=None, store=None, data_dir=None, ux=upstox, tg=telegram, charges=costs.order):
    now = now or datetime.now(engine.IST).replace(tzinfo=None)
    store = store or storage.backend()
    day = now.date().isoformat()
    if not WATCH[0] <= (now.hour, now.minute) <= WATCH[1]:
        return {"skipped": "outside 09:10-15:20"}
    if now.weekday() >= 5 or any(h.get("date") == day and h.get("holiday_type") == "TRADING_HOLIDAY"
                                 and "NSE" in (h.get("closed_exchanges") or []) for h in ux.holidays()):
        return {"skipped": "no trading today"}
    seen_key = f"guardian/{day}.json"
    seen = storage.get_json(seen_key, {}, store=store)
    started = any(store.get(f"claims/{day}-{phase}") is not None for phase in ("morning", "afternoon"))
    if not started:
        if not seen.get("no_session"):
            tg.send("⚠️ No trading session started today by 09:10. Check the AWS kicker and the Actions tab; "
                    "start it by hand from Actions → Trading session if needed.")
            seen["no_session"] = True
            storage.put_json(seen_key, seen, store=store)
        return {"alert": "no session"}
    age = engine.heartbeat_age_min(store, now)
    beat = (storage.get_json(engine.HEARTBEAT_KEY, store=store) or {}).get("at", "")
    if age is not None and beat[:10] == day and age <= STALE_MIN:
        return {"ok": "session alive"}
    if (now.hour, now.minute) >= CLOSE_FROM:
        with tempfile.TemporaryDirectory() as fresh:  # never a warm container's old journal copy
            e = engine.Engine(store=store, data_dir=data_dir or fresh, now=lambda: now, ux=ux, tg=tg,
                              charges=charges)
            e.load()
            closed = list(e.state["positions"])
            for sym in closed:
                e.exit_position(sym, why="the session had stopped; closed by the guardian",
                                reason="guardian_square_off")
        if closed:
            tg.send(f"⚠️ The session had stopped, so the guardian closed {', '.join(closed)} on paper at "
                    f"{now:%H:%M}.")
        return {"closed": closed}
    if seen.get("stale_since") != beat:
        since = f"since {beat[11:16]}" if beat[:10] == day else "today"
        tg.send(f"⚠️ The trading session looks stopped: no heartbeat {since}. Open positions are guarded by "
                f"nothing until it restarts; the guardian closes them from 15:12. Check the Actions tab.")
        seen["stale_since"] = beat
        storage.put_json(seen_key, seen, store=store)
    return {"alert": "session silent"}


def handler(event, context):
    return run()
