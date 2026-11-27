"""trader.engine end to end with fake Upstox, Telegram and council (no network, no Claude)."""
import tempfile
import unittest
from datetime import datetime

from core import journal, storage
from trader import engine

DAY = "2026-12-14"


class Clock:
    def __init__(self, hh=10, mm=0):
        self.t = datetime(2026, 12, 14, hh, mm)

    def __call__(self):
        return self.t


def candle(ts, o, h, l, c, v=10000):
    return {"ts": f"{DAY}T{ts}:00+05:30", "open": o, "high": h, "low": l, "close": c, "volume": v}


class FakeUx:
    def __init__(self):
        self.price = {"NSE_EQ|ABC": 500.0, "NSE_INDEX|India VIX": 14.0}
        self.last_1m = {}

    def instruments(self):
        return {"eq": {"ABC": {"key": "NSE_EQ|ABC", "isin": "INEABC"}, "XYZ": {"key": "NSE_EQ|XYZ", "isin": "INEXYZ"}},
                "index": {"India VIX": "NSE_INDEX|India VIX", "Nifty 50": "NSE_INDEX|Nifty 50",
                          "Nifty IT": "NSE_INDEX|Nifty IT", "Nifty 500": "NSE_INDEX|Nifty 500"}}

    def quotes(self, keys):
        return {k: {"instrument_token": k, "last_price": self.price.get(k, 500.0), "net_change": 5.0,
                    "ohlc": {"open": 495.0}, "volume": 10 ** 6, "average_price": 500.0,
                    "upper_circuit_limit": 600, "lower_circuit_limit": 400,
                    "depth": {"buy": [{"price": self.price.get(k, 500.0) - 0.05}],
                              "sell": [{"price": self.price.get(k, 500.0) + 0.05}]}} for k in keys}

    def intraday_candles(self, key, minutes=5):
        return self.last_1m.get(key) or [candle("09:15", 495, 501, 494, 500), candle("09:59", 499, 501, 498, 500)]

    def historical_candles(self, key, unit, interval, start, end):
        self.__dict__.setdefault("hist_calls", []).append((key, unit, start, end))
        if unit == "minutes":  # a full previous session, 09:15-15:29
            return [{"ts": f"{start.isoformat()}T{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00+05:30", "open": 495,
                     "high": 496, "low": 494, "close": 495 + (i % 3) * 0.1, "volume": 5000} for i in range(375)]
        return [{"ts": f"2026-11-{d:02d}T00:00:00+05:30", "open": 490, "high": 500, "low": 480, "close": 495,
                 "volume": 2 * 10 ** 6} for d in range(1, 29)]

    def news(self, keys):
        return {}

    def holidays(self):
        return self.holiday_list if hasattr(self, "holiday_list") else []


class FakeTg:
    def __init__(self):
        self.sent, self.edits, self.updates, self.next_id = [], [], [], 100

    def send(self, text, buttons=None, reply_to=None, now_ist=None):
        self.next_id += 1
        self.sent.append({"id": self.next_id, "text": text, "buttons": buttons})
        return self.next_id

    def edit(self, message_id, text, buttons=None):
        self.edits.append((message_id, text))

    def answer_button(self, callback_id, text=""):
        pass

    def poll(self, offset, wait=25):
        out, self.updates = self.updates, []
        return out, offset + len(out)


def fake_filings(symbol):
    return [{"when": "14 Dec 09:05", "what": "Press Release", "detail": "New order"}] if symbol == "ABC" else []


def council_fn(case, track):
    council_fn.cases.append(case)
    return {"yes_pct": 60.0, "members": {"skeptic": {"yes_pct": 50, "why": "-"}, "tape": {"yes_pct": 70, "why": "-"},
                                          "base_rate": {"yes_pct": 50.0, "n": 0}}, "for": 1, "against": 0, "seconds": 2.0}


council_fn.cases = []


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = storage.Local(self.dir)
        self.clock = Clock()
        self.ux, self.tg = FakeUx(), FakeTg()
        council_fn.cases.clear()
        self.e = engine.Engine(store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                               council_fn=council_fn, filings=fake_filings, charges=lambda key, qty, pool, side, price: 5.0,
                               sleep=lambda s: None, members={"ABC": {"industry": "Information Technology",
                                                                      "isin": "INEABC"}})
        self.e.start_day()

    def review(self, **kw):
        args = dict(symbol="ABC", side="BUY", setup="ORB long", entry=500.0, stop=495.0, target=510.0,
                    pros="broke the 15-minute high", cons="Nifty flat", agent_yes_pct=65, invalid_if="back under 497")
        args.update(kw)
        return self.e.review_trade(**args)

    def events(self, name):
        return [e for e in journal.read(DAY, base_dir=self.dir) if e["event"] == name]

    def test_blocked_by_the_gate_is_journaled_and_not_sent(self):
        r = self.review(stop=505.0)
        self.assertFalse(r["allowed"])
        self.assertEqual(len(self.events("blocked_by_risk_gate")), 1)
        self.assertEqual(self.tg.sent[1:], [])  # only the start-of-day message

    def test_review_then_place_fills_at_live_price_with_slippage(self):
        r = self.review()
        self.assertTrue(r["allowed"])
        self.assertNotIn("broke the 15-minute high", str(council_fn.cases[0].get("facts")))
        self.assertEqual(council_fn.cases[0]["facts"]["filings"][0]["what"], "Press Release")  # NSE filings, 2 days
        minutes = [c for c in self.ux.hist_calls if c[1] == "minutes"]       # yesterday's 1m: indicators warm at 09:15
        self.assertEqual(minutes[0][2], minutes[0][3])
        self.assertEqual(minutes[0][2].isoformat(), "2026-11-28")             # the last daily candle's day
        self.assertIsNotNone(council_fn.cases[0]["facts"]["tf"]["5m"]["ema20"])
        placed = self.e.place_trade(r["review_id"], why="council and tape agree")
        self.assertEqual(placed["status"], "placed")
        pos = self.e.state["positions"]["ABC"]
        self.assertEqual((pos["fill_price"], pos["entry_charges"], pos["setup"]), (500.25, 5.0, "ORB long"))
        self.assertIn("🟢 BUY ABC · ORB long · council 60%", self.tg.sent[-1]["text"])
        fill = self.events("fill")[0]
        self.assertIn("facts", fill)
        self.assertEqual(fill["pool"], "intraday")
        self.assertIn("at", fill)  # IST fill time, replayed by the A01/A02 shadows

    def test_place_refused_if_price_ran_away(self):
        r = self.review()
        self.ux.price["NSE_EQ|ABC"] = 502.0  # 0.4% above the proposed entry
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "missed")
        self.assertNotIn("ABC", self.e.state["positions"])

    def test_skip_is_recorded(self):
        r = self.review()
        self.e.skip_trade(r["review_id"], why="council against")
        self.assertEqual(self.events("skipped")[0]["why"], "council against")

    def test_stop_can_tighten_never_widen(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.assertTrue(self.e.adjust_stop("ABC", 497.0, why="trail")["ok"])
        self.assertFalse(self.e.adjust_stop("ABC", 490.0, why="hope")["ok"])
        self.assertEqual(self.e.state["positions"]["ABC"]["stop"], 497.0)

    def test_monitor_fires_the_stop_and_the_ledger_reconciles(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.ux.last_1m["NSE_EQ|ABC"] = [candle("10:01", 498, 498.5, 494.0, 494.5)]
        self.e.monitor_once()
        self.assertNotIn("ABC", self.e.state["positions"])
        ex = self.events("exit")[0]
        self.assertEqual(ex["reason"], "stop")
        self.assertAlmostEqual(ex["net_rs"], round((494.75 - 500.25) * ex["qty"] - 10.0, 2))
        self.assertTrue(self.e.report()["reconciled"])

    def test_heartbeat_every_few_minutes_while_guarding(self):
        self.e.monitor_once()
        self.assertEqual(engine.heartbeat_age_min(self.store, self.clock()), 0)
        self.clock.t = self.clock.t.replace(minute=2)
        self.e.monitor_once()
        self.assertEqual(engine.heartbeat_age_min(self.store, self.clock()), 2)  # not written again yet
        self.clock.t = self.clock.t.replace(minute=5)
        self.e.monitor_once()
        self.assertEqual(engine.heartbeat_age_min(self.store, self.clock()), 0)
        self.assertIsNone(engine.heartbeat_age_min(storage.Local(tempfile.mkdtemp()), self.clock()))

    def test_square_off_at_1510(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.clock.t = self.clock.t.replace(hour=15, minute=10)
        self.e.monitor_once()
        self.assertEqual(self.events("exit")[0]["reason"], "square_off")

    def test_owner_commands_exit_pause_and_ratings(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        msg_id = self.e.state["positions"]["ABC"]["msg_id"]
        self.tg.updates = [{"kind": "reaction", "message_id": msg_id, "emoji": "👍"},
                           {"kind": "command", "text": "/pause"},
                           {"kind": "button", "id": "b1", "data": "exit:ABC"}]
        self.e.handle_updates()
        self.assertTrue(self.e.state["paused"])
        self.assertNotIn("ABC", self.e.state["positions"])
        self.assertEqual(self.events("rating")[0]["rating"], "up")

    def test_human_mode_waits_for_yes(self):
        self.e.state["auto"] = False
        r = self.review()
        self.tg.updates = [{"kind": "button", "id": "b", "data": f"yes:{r['review_id']}"}]
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "placed")
        r2 = self.review(symbol="ABC")  # already held: blocked
        self.assertFalse(r2["allowed"])

    def test_human_mode_no_answer_means_no_trade(self):
        self.e.state["auto"] = False
        r = self.review()
        self.assertEqual(self.e.place_trade(r["review_id"], why="-", approval_wait_sec=0)["status"], "not approved")

    def test_a_review_is_placed_at_most_once(self):
        r = self.review()
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "placed")
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "unknown review")
        self.assertEqual(self.e.state["trades_today"], 1)

    def test_the_gate_runs_again_at_placing(self):
        self.e.members["XYZ"] = {"industry": "Information Technology", "isin": "INEXYZ"}
        first, second = self.review(), self.review(symbol="XYZ")  # same sector: each passes alone, not both
        self.assertEqual(self.e.place_trade(first["review_id"], why="-")["status"], "placed")
        out = self.e.place_trade(second["review_id"], why="-")
        self.assertEqual(out["status"], "blocked")
        self.assertIn("per sector", out["reason"])

    def test_pause_between_review_and_place_blocks(self):
        r = self.review()
        self.e.state["paused"] = True
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "blocked")

    def test_an_old_review_expires(self):
        r = self.review()
        self.clock.t = self.clock.t.replace(minute=11)
        self.assertEqual(self.e.place_trade(r["review_id"], why="-")["status"], "expired")

    def test_a_stop_touched_between_checks_still_fires(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.ux.last_1m["NSE_EQ|ABC"] = [candle("10:00", 500, 500.5, 499, 500), candle("10:01", 498, 498.5, 494.0, 497),
                                         candle("10:02", 497, 499, 496.5, 498.5)]  # touched at 10:01, recovered
        self.clock.t = self.clock.t.replace(minute=3)
        self.e.monitor_once()
        self.assertEqual(self.events("exit")[0]["reason"], "stop")

    def test_a_tightened_stop_never_judges_minutes_before_the_move(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.ux.last_1m["NSE_EQ|ABC"] = [candle("10:01", 503, 506, 502, 505)]  # low 502: fine under the old stop 495
        self.clock.t = self.clock.t.replace(minute=2)
        self.assertTrue(self.e.adjust_stop("ABC", 503.0, why="breakeven plus costs")["ok"])
        self.ux.last_1m["NSE_EQ|ABC"] = [candle("10:01", 503, 506, 502, 505), candle("10:02", 505, 511, 504, 510),
                                         candle("10:03", 510, 511, 509, 510)]
        self.clock.t = self.clock.t.replace(minute=4)
        self.e.monitor_once()
        self.assertIn("ABC", self.e.state["positions"])

    def test_report_squares_off_anything_still_open(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.clock.t = self.clock.t.replace(hour=15, minute=11)
        out = self.e.report()
        self.assertEqual(self.e.state["positions"], {})
        self.assertTrue(out["reconciled"])

    def test_a_position_left_from_an_earlier_day_is_closed_at_the_next_start(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        self.clock.t = datetime(2026, 12, 15, 9, 0)  # the afternoon session never ran
        again = engine.Engine(store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                              council_fn=council_fn, filings=fake_filings, charges=lambda *a: 5.0, sleep=lambda s: None, members={})
        again.start_day()
        self.assertEqual(again.state["positions"], {})
        self.assertIn("carried", self.tg.sent[-2]["text"] + self.tg.sent[-1]["text"])

    def test_stale_prices_block_new_entries(self):
        self.clock.t = self.clock.t.replace(hour=10, minute=30)  # the last 1-minute candle is from 09:15
        r = self.review()
        self.assertFalse(r["allowed"])
        self.assertIn("stale", r["reason"])

    def test_circuit_breaker_at_12pct_below_the_peak(self):
        self.e.state["peak_balance"] = 50_000.0  # balance ₹40,000 is 20% below
        r = self.review()
        self.assertFalse(r["allowed"])
        self.assertIn("circuit breaker", r["reason"])

    def test_a_stock_failing_the_guardrails_is_not_tradable(self):
        self.ux.price["NSE_EQ|ABC"] = 40.0
        r = self.review(entry=40.0, stop=39.0, target=42.0)
        self.assertFalse(r["allowed"])
        self.assertIn("tradable", r["reason"])

    def test_started_after_the_close_means_no_session(self):
        self.clock.t = self.clock.t.replace(hour=21, minute=45)
        e = engine.Engine(store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                          council_fn=council_fn, filings=fake_filings, charges=lambda *a: 5.0, sleep=lambda s: None, members={})
        self.assertIn("closed", e.start_day()["holiday"])

    def test_nse_holiday_means_no_session(self):
        self.ux.holiday_list = [{"date": DAY, "description": "Some festival", "holiday_type": "TRADING_HOLIDAY",
                                 "closed_exchanges": ["NSE", "BSE"]}]
        e = engine.Engine(store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                          council_fn=council_fn, filings=fake_filings, charges=lambda *a: 5.0, sleep=lambda s: None, members={})
        self.assertEqual(e.start_day()["holiday"], "Some festival")
        self.assertIn("No session today: Some festival", self.tg.sent[-1]["text"])

    def test_restart_same_day_keeps_the_ledger(self):
        self.e.place_trade(self.review()["review_id"], why="-")
        again = engine.Engine(store=self.store, data_dir=self.dir, now=self.clock, ux=self.ux, tg=self.tg,
                              council_fn=council_fn, filings=fake_filings, charges=lambda *a: 5.0, sleep=lambda s: None, members={})
        again.start_day()
        self.assertIn("ABC", again.state["positions"])
        self.assertEqual(again.state["trades_today"], 1)


if __name__ == "__main__":
    unittest.main()
