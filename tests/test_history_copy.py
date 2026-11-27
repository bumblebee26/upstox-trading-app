"""lakehouse.history_copy: the one-time copy of the old NSE and market history (files, never tables)."""
import unittest
from collections import namedtuple

from lakehouse import history_copy as hc

Info = namedtuple("Info", "path name size")


def _plain(path):
    return path[5:] if path.startswith("dbfs:") else path


class FakeFs:
    """Like Databricks' dbutils.fs: ls returns paths with a dbfs: prefix (the cause of the 27 Nov bug)."""
    def __init__(self, files):
        self.files = dict(files)  # path -> bytes
        self.copied, self.removed = [], []

    def ls(self, path):
        path = _plain(path).rstrip("/") + "/"
        out = {}
        for p, b in self.files.items():
            if p.startswith(path):
                head = p[len(path):].split("/")[0]
                if "/" in p[len(path):]:
                    out[head + "/"] = Info("dbfs:" + path + head + "/", head + "/", 0)
                else:
                    out[head] = Info("dbfs:" + p, head, len(b))
        if not out:
            raise FileNotFoundError(path)
        return list(out.values())

    def cp(self, src, dst):
        self.files[_plain(dst)] = self.files[_plain(src)]
        self.copied.append(_plain(dst))

    def head(self, path, n):
        return self.files[_plain(path)][:n].decode()

    def rm(self, path, recurse=False):
        path = _plain(path).rstrip("/") + "/"
        gone = [p for p in self.files if p.startswith(path)]
        for p in gone:
            del self.files[p]
        self.removed.append(path)


OLD = hc.OLD_ROOT


def landing(source, day, name, body=b"SYMBOL,CLOSE\nABC,10\n"):
    return f"{OLD}/landing/{source}/date={day}/{name}", body


class CopyTest(unittest.TestCase):
    def test_copies_once_verifies_and_reports(self):
        fs = FakeFs([landing("nse", "2024-01-02", "bhav.csv"), landing("nse", "2025-06-30", "bhav.csv"),
                     landing("fred", "2025-01-01", "obs.json", b'{"a": 1}')])
        report = hc.run(fs, sources=["nse", "fred", "massive"])
        nse = report["nse"]
        self.assertEqual((nse["files"], nse["first_day"], nse["last_day"], nse["types"]),
                         (2, "2024-01-02", "2025-06-30", {"csv": 2}))
        self.assertTrue(nse["verified"])
        self.assertIn("SYMBOL,CLOSE", nse["sample"])
        self.assertIn(f"{hc.NEW_ROOT}/nse/date=2024-01-02/bhav.csv", fs.files)
        self.assertEqual(report["massive"], {"skipped": "not in the old volume"})
        self.assertEqual(hc.run(fs, sources=["nse"])["nse"]["copied"], 0)  # second run copies nothing

    def test_removes_misplaced_and_dropped_folders_only_after_everything_verified(self):
        new = hc.NEW_ROOT
        fs = FakeFs([landing("nse", "2024-01-02", "bhav.csv"),
                     (f"{new}/nseg/nse/date=2024-01-02/bhav.csv", b"x"),       # misplaced by the 27 Nov bug
                     (f"{new}/fred/fred/date=2026-11-07/f.json", b"x"),        # a source the owner dropped
                     (f"{new}/news/news/date=2026-11-09/s.jsonl", b"x")])
        report = hc.run(fs, sources=["nse"])
        self.assertTrue(report["nse"]["verified"])
        self.assertEqual(sorted(report["removed"]), [f"{new}/fred/", f"{new}/news/", f"{new}/nseg/"])
        self.assertIn(f"{new}/nse/date=2024-01-02/bhav.csv", fs.files)

    def test_keeps_everything_when_a_copy_fails_to_verify(self):
        fs = FakeFs([landing("nse", "2024-01-02", "bhav.csv"), (f"{hc.NEW_ROOT}/nseg/x.csv", b"x")])
        fs.cp = lambda src, dst: None  # nothing lands
        report = hc.run(fs, sources=["nse"])
        self.assertFalse(report["nse"]["verified"])
        self.assertEqual(report["removed"], [])


if __name__ == "__main__":
    unittest.main()
