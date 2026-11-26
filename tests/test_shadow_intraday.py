"""shadows.intraday: the catalog's entry rules on made-up days, and the variant list."""
import random
import unittest

from shadows import intraday as si


def minute_day(path, day="2026-12-14", vol=1000, vol_at=None):
    """1-minute candles from 09:15 following `path` (one price a minute)."""
    out = []
    for i, p in enumerate(path):
        h, m = divmod(15 + i, 60)
        prev = path[i - 1] if i else p
        v = (vol_at or {}).get(i, vol)
        out.append({"ts": f"{day}T{9 + h:02d}:{m:02d}:00+05:30", "open": prev, "high": max(prev, p) + 0.05,
                    "low": min(prev, p) - 0.05, "close": p, "volume": v})
    return out


def daily(n=30, close=100.0, high=101.0, low=99.0):
    rows = [{"ts": f"2026-11-{d % 28 + 1:02d}T00:00:00+05:30", "open": close, "high": close + 3, "low": close - 3,
             "close": close, "volume": 10 ** 6} for d in range(n)]
    rows[-1].update(high=high, low=low, close=close)
    return rows


def ctx(path, **kw):
    return si.build_context("ABC", "K", minute_day(path, vol_at=kw.pop("vol_at", None)), kw.pop("daily", daily()),
                            **kw)


class PropertyTest(unittest.TestCase):
    def test_every_entry_gives_sane_signals_on_random_days(self):
        rnd = random.Random(7)
        for day in range(6):
            path, p = [], 100.0 + day
            for _ in range(375):
                p = max(10, p * (1 + rnd.gauss(0, 0.002)))
                path.append(round(p, 2))
            c = ctx(path, nifty_one=minute_day([24000 + i for i in range(375)]),
                    sector_one=minute_day([50000 - i for i in range(375)]), vix_prev=15, nifty_above_200=True)
            for eid, fn in si.ENTRIES.items():
                for sig in si.signals(c, fn):
                    i = c.index_of(sig.signal_time)
                    close = c.close[i]
                    self.assertTrue("09:30" <= sig.signal_time[11:16] <= "14:30", eid)
                    self.assertTrue(sig.stop < close if sig.side == "BUY" else sig.stop > close, (eid, sig))
                    if sig.target is not None:
                        self.assertTrue(sig.target > close if sig.side == "BUY" else sig.target < close, eid)


class EntryTest(unittest.TestCase):
    def first(self, c, eid):
        sigs = si.signals(c, si.ENTRIES[eid])
        return sigs[0] if sigs else None

    def test_orb15_breakout_needs_volume(self):
        path = [100.0] * 15 + [100.0 + 0.02 * i for i in range(1, 30)] + [100.6] * 330
        quiet = ctx(path)
        loud = ctx(path, vol_at={i: 5000 for i in range(15, 45)})
        self.assertIsNone(self.first(quiet, "E02"))
        s = self.first(loud, "E02")
        self.assertEqual(s.side, "BUY")
        self.assertLess(s.stop, 100.2)

    def test_previous_day_high_break(self):
        path = [100.0] * 20 + [100.0 + 0.1 * i for i in range(1, 20)] + [102.0] * 336
        s = self.first(ctx(path, daily=daily(high=101.0)), "E05")
        self.assertEqual(s.side, "BUY")

    def test_gap_down_fade(self):
        path = [96.0, 95.8, 95.6] + [95.5] * 12 + [95.5 + 0.1 * i for i in range(1, 15)] + [97.0] * 346
        s = self.first(ctx(path, daily=daily(close=100.0)), "E07")
        self.assertEqual(s.side, "BUY")
        self.assertLessEqual(s.signal_time[11:16], "11:00")

    def test_overlay_o3_follows_the_market(self):
        path = [100.0] * 15 + [100.0 + 0.02 * i for i in range(1, 30)] + [100.6] * 330
        kw = dict(vol_at={i: 5000 for i in range(15, 45)})
        down = ctx(path, nifty_one=minute_day([24000 - i for i in range(375)]), **kw)
        up = ctx(path, nifty_one=minute_day([24000 + i for i in range(375)]), **kw)
        fn, _, overlay = si.VARIANTS["E02-O3"]
        self.assertEqual(si.signals(down, fn, overlay), [])
        self.assertEqual(len(si.signals(up, fn, overlay)), 1)


class VariantTest(unittest.TestCase):
    def test_catalog_size_and_names(self):
        self.assertEqual(len(si.ENTRIES), 30)
        self.assertEqual(len(si.VARIANTS), 66)
        self.assertIn("E09-X7", si.VARIANTS)
        self.assertIn("E04-O2", si.VARIANTS)


if __name__ == "__main__":
    unittest.main()
