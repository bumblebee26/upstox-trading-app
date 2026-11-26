"""lakehouse.sync: the state bucket's files as JSON lines in the Databricks landing volume, only when changed."""
import json
import tempfile
import unittest
from datetime import date

from core import storage
from lakehouse import sync

DAY = "2026-12-14"


def lines(body):
    return [json.loads(x) for x in body.decode().splitlines()]


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.store = storage.Local(tempfile.mkdtemp())
        s = self.store
        s.put(f"journal/{DAY}.jsonl", b'{"event": "fill", "event_id": "a"}\n{"event": "exit", "event_id": "b"}\n')
        s.put(f"journal/{DAY}-swing.jsonl", b'{"event": "decision", "event_id": "c"}\n')
        storage.put_json(f"feed/{DAY}/101500-7.json", {"ts": f"{DAY}T10:15:00", "id": 7, "text": "hi"}, store=s)
        storage.put_json(f"shadows/intraday/{DAY}.json", {"day": DAY, "variants": {
            "E01-X1": {"trades": [{"symbol": "ABC", "net_rs": 12.5}], "net_rs": 12.5}, "E02-X1": {"trades": []}}}, store=s)
        storage.put_json("shadows/families.json", {"day": DAY, "rows": [{"variant": "S03", "status": "too early"}]}, store=s)
        storage.put_json("shadows/ledgers.json", {"day": DAY, "ledgers": {"S03": {
            "capital": 60000.0, "cash": 1000.0, "holdings": {"X": {}}, "closed": [{}], "equity": [[DAY, 60500.0]]}}},
            store=s)
        storage.put_json("state/intraday.json", {"pool": "intraday", "day": DAY, "balance": 40100.0,
                                                 "starting_capital": 40000, "realized_today": 100.0, "positions": {}},
                         store=s)
        storage.put_json(f"nse/{DAY}/bhav.json", {"ABC": {"close": 10.0, "deliv_pct": 55.0}}, store=s)
        storage.put_json(f"nse/{DAY}/bulk.json", [{"symbol": "ABC", "side": "BUY"}], store=s)

    def test_files_become_json_lines(self):
        out = sync.landing_files(self.store, date(2026, 12, 14), back_days=0)
        self.assertEqual(len(lines(out[f"journal/{DAY}.jsonl"])), 2)
        self.assertIn(f"journal/{DAY}-swing.jsonl", out)
        self.assertEqual(lines(out[f"feed/{DAY}.jsonl"])[0]["text"], "hi")
        self.assertEqual(lines(out[f"shadow_trades/{DAY}.jsonl"]), [{"day": DAY, "variant": "E01-X1", "symbol": "ABC",
                                                                      "net_rs": 12.5}])
        self.assertEqual(lines(out[f"shadow_status/{DAY}.jsonl"])[0], {"day": DAY, "variant": "S03", "status": "too early"})
        led = lines(out[f"shadow_ledgers/{DAY}.jsonl"])[0]
        self.assertEqual((led["id"], led["value"], led["holdings"], led["closed"]), ("S03", 60500.0, 1, 1))
        self.assertEqual(lines(out[f"pools/{DAY}-intraday.jsonl"])[0]["balance"], 40100.0)
        self.assertEqual(lines(out[f"nse_bhav/{DAY}.jsonl"]), [{"day": DAY, "symbol": "ABC", "close": 10.0, "deliv_pct": 55.0}])
        self.assertEqual(lines(out[f"nse_deals/{DAY}-bulk.jsonl"])[0]["kind"], "bulk")

    def test_uploads_only_what_changed(self):
        sent = []
        put = lambda path, body: sent.append(path)  # noqa: E731
        sync.run(date(2026, 12, 14), store=self.store, put=put, back_days=0)
        first = len(sent)
        self.assertGreater(first, 5)
        self.assertTrue(all(p.startswith("/Volumes/upx/bronze/landing/") for p in sent))
        sync.run(date(2026, 12, 14), store=self.store, put=put, back_days=0)
        self.assertEqual(len(sent), first)  # nothing new
        self.store.put(f"journal/{DAY}.jsonl", b'{"event": "fill", "event_id": "a"}\n')
        sync.run(date(2026, 12, 14), store=self.store, put=put, back_days=0)
        self.assertEqual(sent[first:], [f"/Volumes/upx/bronze/landing/journal/{DAY}.jsonl"])

    def test_a_failed_upload_is_tried_again_next_time(self):
        def broken(path, body):
            raise RuntimeError("Databricks said 503")
        with self.assertRaises(RuntimeError):
            sync.run(date(2026, 12, 14), store=self.store, put=broken, back_days=0)
        sent = []
        sync.run(date(2026, 12, 14), store=self.store, put=lambda p, b: sent.append(p), back_days=0)
        self.assertGreater(len(sent), 5)


class WaitTest(unittest.TestCase):
    def test_waits_for_the_update_and_reports_errors(self):
        import os
        from unittest import mock
        states = iter(["RUNNING", "FAILED"])

        def fake(method, url, **kw):
            if "/events" in url:
                return json.dumps({"events": [{"level": "ERROR", "message": "Flow 'trades' failed",
                                               "error": {"exceptions": [{"message": "column x not found"}]}}]}).encode()
            return json.dumps({"update": {"state": next(states)}}).encode()

        with mock.patch.dict(os.environ, {"DATABRICKS_HOST": "https://h", "DATABRICKS_TOKEN": "t"}), \
                mock.patch.object(sync.http, "request", side_effect=fake):
            state, errors = sync.wait("p1", "u1", sleep=lambda s: None)
        self.assertEqual(state, "FAILED")
        self.assertIn("column x not found", errors[0])


if __name__ == "__main__":
    unittest.main()
