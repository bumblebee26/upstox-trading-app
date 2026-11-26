"""AWS Lambda, every minute: answers Telegram (commands, buttons, 👍/👎) while no trading session is running,
so /ledger, /pause, /resume, /auto and ratings work in the evening, at night and at weekends.

It reuses the session's own handling (trader/engine.py), with the same saved state and Telegram offset. It
stays quiet while a session is alive (its heartbeat is recent) and around the session start and the
morning-to-afternoon handover, so the two never answer the same message or write the state together.

shortcut: the quiet windows are fixed times (08:50-09:10 and 12:20-12:45 on weekdays); a shared lock in the
state bucket would be exact. Upgrade if a session ever starts at another time.
"""
import tempfile
from datetime import datetime

from core import costs, storage, upstox
from trader import engine, telegram

QUIET_AFTER_BEAT_MIN = 15
WINDOWS = (((8, 50), (9, 10)), ((12, 20), (12, 45)))


def session_may_be_running(store, now):
    age = engine.heartbeat_age_min(store, now)
    if age is not None and age <= QUIET_AFTER_BEAT_MIN:
        return True
    hm = (now.hour, now.minute)
    return now.weekday() < 5 and any(a <= hm < b for a, b in WINDOWS)


def run(now=None, store=None, data_dir=None, ux=upstox, tg=telegram, charges=costs.order):
    now = now or datetime.now(engine.IST).replace(tzinfo=None)
    store = store or storage.backend()
    if session_may_be_running(store, now):
        return {"skipped": "a session may be running"}
    with tempfile.TemporaryDirectory() as fresh:  # never a warm container's old journal copy
        e = engine.Engine(store=store, data_dir=data_dir or fresh, now=lambda: now, ux=ux, tg=tg,
                          charges=charges)
        e.load()
        return {"updates": e.handle_updates(wait=0)}


def handler(event, context):
    return run()
