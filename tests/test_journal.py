"""core.journal: append-only events, one file a day; a re-written event (same event_id) is counted once."""
import tempfile
import threading
import unittest

from core import journal


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_append_and_read_back(self):
        eid = journal.append("2026-12-14", "exit", base_dir=self.dir, symbol="ABC", net_rs=12.5)
        rows = journal.read("2026-12-14", base_dir=self.dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["event"], rows[0]["symbol"], rows[0]["net_rs"], rows[0]["event_id"]),
                         ("exit", "ABC", 12.5, eid))

    def test_same_event_id_counts_once_newest_wins(self):
        journal.append("2026-12-14", "exit", base_dir=self.dir, event_id="t1", net_rs=10.0)
        journal.append("2026-12-14", "exit", base_dir=self.dir, event_id="t1", net_rs=11.0)
        rows = journal.read("2026-12-14", base_dir=self.dir)
        self.assertEqual([r["net_rs"] for r in rows], [11.0])

    def test_parallel_appends_are_not_lost_or_mixed(self):
        def write(n):
            for i in range(50):
                journal.append("2026-12-14", "tick", base_dir=self.dir, n=n, i=i)
        threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(journal.read("2026-12-14", base_dir=self.dir)), 400)

    def test_half_written_last_line_after_a_crash_is_skipped(self):
        journal.append("2026-12-14", "exit", base_dir=self.dir, net_rs=1.0)
        with journal._path("2026-12-14", self.dir).open("a") as f:
            f.write('{"event": "exit", "event_id": "x", "net')
        self.assertEqual(len(journal.read("2026-12-14", base_dir=self.dir)), 1)

    def test_mirror_copies_the_day_file_and_restore_brings_it_back(self):
        from core import storage
        remote = storage.Local(tempfile.mkdtemp())
        journal.append("2026-12-14", "exit", base_dir=self.dir, mirror=remote, net_rs=5.0)
        self.assertIsNotNone(remote.get("journal/2026-12-14.jsonl"))
        fresh_dir = tempfile.mkdtemp()  # a new GitHub runner starts empty
        journal.restore("2026-12-14", base_dir=fresh_dir, mirror=remote)
        self.assertEqual(len(journal.read("2026-12-14", base_dir=fresh_dir)), 1)

    def test_missing_day_is_empty(self):
        self.assertEqual(journal.read("2026-01-01", base_dir=self.dir), [])


if __name__ == "__main__":
    unittest.main()
