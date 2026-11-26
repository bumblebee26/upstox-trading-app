"""lakehouse.history_copy: the one-time copy of the old NSE and market history (files, never tables)."""
import unittest
from collections import namedtuple

from lakehouse import history_copy as hc

Info = namedtuple("Info", "path name size")


class FakeFs:
    def __init__(self, files):
        self.files = dict(files)  # path -> bytes
        self.copied = []

    def ls(self, path):
        path = path.rstrip("/") + "/"
        out = {}
        for p, b in self.files.items():
            if p.startswith(path):
                head = p[len(path):].split("/")[0]
                if "/" in p[len(path):]:
                    out[head + "/"] = Info(path + head + "/", head + "/", 0)
                else:
                    out[head] = Info(p, head, len(b))
        if not out:
            raise FileNotFoundError(path)
        return list(out.values())

    def cp(self, src, dst):
        self.files[dst] = self.files[src]
        self.copied.append(dst)

    def head(self, path, n):
        return self.files[path][:n].decode()


OLD = hc.OLD_ROOT


def landing(source, day, name, body=b"SYMBOL,CLOSE\nABC,10\n"):
    return f"{OLD}/landing/{source}/date={day}/{name}", body


class CopyTest(unittest.TestCase):
    def test_copies_once_verifies_and_reports(self):
        fs = FakeFs([landing("nse", "2024-01-02", "bhav.csv"), landing("nse", "2025-06-30", "bhav.csv"),
                     landing("fred", "2025-01-01", "obs.json", b'{"a": 1}')])
        report = hc.run(fs, sources=["nse", "fred", "massive"], news_min_days=7)
        nse = report["nse"]
        self.assertEqual((nse["files"], nse["first_day"], nse["last_day"], nse["types"]),
                         (2, "2024-01-02", "2025-06-30", {"csv": 2}))
        self.assertTrue(nse["verified"])
        self.assertIn("SYMBOL,CLOSE", nse["sample"])
        self.assertIn(f"{hc.NEW_ROOT}/nse/date=2024-01-02/bhav.csv", fs.files)
        self.assertEqual(report["massive"], {"skipped": "not in the old volume"})
        self.assertEqual(hc.run(fs, sources=["nse"], news_min_days=7)["nse"]["copied"], 0)  # second run copies nothing

    def test_news_only_if_it_covers_more_than_a_week(self):
        few = FakeFs([(f"{OLD}/news/date=2026-11-2{d}/snap_0900.jsonl", b"{}") for d in range(3)])
        self.assertIn("skipped", hc.run(few, sources=[], news_min_days=7)["news"])
        many = FakeFs([(f"{OLD}/news/date=2026-10-{d:02d}/snap_0900.jsonl", b"{}") for d in range(1, 20)])
        self.assertEqual(hc.run(many, sources=[], news_min_days=7)["news"]["files"], 19)


if __name__ == "__main__":
    unittest.main()
