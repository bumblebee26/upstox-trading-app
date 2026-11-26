"""shadows.families: grouping, the luck line (best-of-family under no edge), and each variant's status."""
import random
import unittest

from shadows import families as fam


def days(n):
    return [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


class FamilyTest(unittest.TestCase):
    def test_grouping(self):
        self.assertEqual([fam.family(v) for v in ("E05-X1", "E02-X3", "E04-O2", "S03", "S01-CH", "L07", "A01", "B01-long")],
                         ["intraday entries", "intraday exits", "intraday overlays", "swing", "swing exits",
                          "long-term", "AI vs rules", "benchmarks"])

    def test_luck_line_grows_with_more_variants(self):
        rnd = random.Random(1)
        d = days(120)
        few = {f"V{i}": {x: rnd.gauss(0, 100) for x in d} for i in range(2)}
        many = dict(few, **{f"W{i}": {x: rnd.gauss(0, 100) for x in d} for i in range(30)})
        self.assertGreater(fam.luck_line(many, n=400), fam.luck_line(few, n=400))

    def test_statuses(self):
        rnd = random.Random(2)
        d = days(150)
        edge = {x: 60 + rnd.gauss(0, 100) for x in d}      # a real edge, ₹60 a day
        noise = {x: rnd.gauss(0, 100) for x in d}
        loser = {x: -40 + rnd.gauss(0, 30) for x in d}
        variants = {
            "E01-X1": {"days": edge, "trades": [1.0] * 220},
            "E02-X1": {"days": noise, "trades": [1.0] * 220},
            "E03-X1": {"days": noise, "trades": [1.0] * 50},
            "E04-X1": {"days": loser, "trades": [-5.0 + rnd.gauss(0, 2) for _ in range(220)]},
        }
        rows = {r["variant"]: r for r in fam.judge(variants, state={}, today=d[-1])}
        self.assertEqual(rows["E01-X1"]["status"], "above luck")
        self.assertEqual(rows["E02-X1"]["status"], "watching")
        self.assertEqual(rows["E03-X1"]["status"], "too early")
        self.assertEqual(rows["E04-X1"]["status"], "kill")

    def test_passed_needs_20_trading_days_still_above(self):
        rnd = random.Random(3)
        d = days(150)
        edge = {x: 80 + rnd.gauss(0, 50) for x in d}
        state = {"E01-X1": {"first_above": d[-25]}}
        rows = fam.judge({"E01-X1": {"days": edge, "trades": [1.0] * 250},
                          "E02-X1": {"days": {x: rnd.gauss(0, 50) for x in d}, "trades": [1.0] * 250}},
                         state=state, today=d[-1], trading_days=d)
        self.assertEqual(rows[0]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
