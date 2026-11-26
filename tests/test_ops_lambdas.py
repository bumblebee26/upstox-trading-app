"""lambdas.responder and lambdas.guardian: Telegram while no session runs, and the safety net for a dead session."""
import tempfile
import unittest
from datetime import datetime

from core import journal, storage
from lambdas import guardian, responder
from tests.test_engine import DAY, FakeTg, FakeUx, council_fn
from trader import engine


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store, self.ux, self.tg = storage.Local(self.dir), FakeUx(), FakeTg()
        e = engine.Engine(store=self.store, data_dir=self.dir, now=lambda: datetime(2026, 12, 14, 10, 0), ux=self.ux,
                          tg=self.tg, council_fn=council_fn, charges=lambda *a: 5.0, sleep=lambda s: None,
                          members={"ABC": {"industry": "Information Technology", "isin": "INEABC"}})
        e.start_day()  # writes the state and a 10:00 heartbeat
        r = e.review_trade(symbol="ABC", side="BUY", setup="ORB long", entry=500.0, stop=495.0, target=510.0,
                           pros="-", cons="-", agent_yes_pct=60, invalid_if="-")
        e.place_trade(r["review_id"], why="-")
        self.local = tempfile.mkdtemp()  # the Lambda's own empty /tmp: the journal comes from the bucket
        self.store.put(f"claims/{DAY}-morning", b"")

    def state(self):
        return storage.get_json(engine.STATE_KEY, store=self.store)


class ResponderTest(Base):
    def run_at(self, hh, mm, day=14):
        return responder.run(now=datetime(2026, 12, day, hh, mm), store=self.store, data_dir=self.local, ux=self.ux,
                             tg=self.tg, charges=lambda *a: 5.0)

    def test_skips_while_a_session_runs(self):
        self.tg.updates = [{"kind": "command", "text": "/pause"}]
        self.assertIn("skipped", self.run_at(10, 5))   # heartbeat 5 minutes old
        self.assertIn("skipped", self.run_at(12, 30))  # sessions hand over around 12:25-12:27
        self.assertFalse(self.state()["paused"])

    def test_answers_when_no_session_runs(self):
        self.tg.updates = [{"kind": "command", "text": "/pause"}]
        before = self.state()["tg_offset"]
        self.assertEqual(self.run_at(20, 0)["updates"], 1)
        self.assertTrue(self.state()["paused"])
        self.assertEqual(self.state()["tg_offset"], before + 1)
        self.assertIn("No new entries", self.tg.sent[-1]["text"])
        self.assertEqual(len(journal.read(DAY, base_dir=self.local)), len(journal.read(DAY, base_dir=self.dir)))


class GuardianTest(Base):
    def run_at(self, hh, mm, day=14):
        return guardian.run(now=datetime(2026, 12, day, hh, mm), store=self.store, data_dir=self.local, ux=self.ux,
                            tg=self.tg, charges=lambda *a: 5.0)

    def alerts(self):
        return [m["text"] for m in self.tg.sent if m["text"].startswith("⚠️")]

    def test_alerts_once_when_the_session_goes_quiet(self):
        self.assertEqual(self.run_at(10, 10), {"ok": "session alive"})
        self.run_at(10, 20)
        self.run_at(10, 25)
        self.assertEqual(len(self.alerts()), 1)
        self.assertIn("no heartbeat since 10:00", self.alerts()[0])

    def test_alerts_when_no_session_started(self):
        self.run_at(9, 15, day=15)
        self.run_at(9, 20, day=15)
        self.assertEqual(len([a for a in self.alerts() if "No trading session started" in a]), 1)

    def test_closes_positions_a_dead_session_left_open(self):
        out = self.run_at(15, 12)
        self.assertEqual(out["closed"], ["ABC"])
        self.assertEqual(self.state()["positions"], {})
        exits = [e for e in journal.read(DAY, base_dir=self.local) if e["event"] == "exit"]
        self.assertEqual(exits[0]["reason"], "guardian_square_off")
        mirrored = self.store.get(f"journal/{DAY}.jsonl").decode()
        self.assertIn('"review"', mirrored)  # the earlier events survived the guardian's write

    def test_leaves_a_live_session_alone_and_skips_closed_days(self):
        storage.put_json(engine.HEARTBEAT_KEY, {"at": "2026-12-14T15:10:00"}, store=self.store)
        self.assertEqual(self.run_at(15, 12), {"ok": "session alive"})
        self.assertIn("ABC", self.state()["positions"])
        self.assertIn("skipped", self.run_at(11, 0, day=19))  # Saturday
        self.assertIn("skipped", self.run_at(9, 5, day=15))   # before 09:10 a session may still be starting
        self.ux.holiday_list = [{"date": "2026-12-25", "holiday_type": "TRADING_HOLIDAY", "closed_exchanges": ["NSE"]}]
        self.assertIn("skipped", self.run_at(11, 0, day=25))


if __name__ == "__main__":
    unittest.main()
