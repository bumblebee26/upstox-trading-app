"""trader.council: the quick intraday council (skeptic + tape reader + base rate), run with a fake Claude."""
import json
import time
import unittest

from trader import council

CASE = {"symbol": "ABC", "side": "BUY", "entry": 500.0, "stop": 495.0, "target": 510.0, "facts": {"price": 500.0}}


def fake(answers, delay=0.0):
    def runner(prompt, timeout):
        time.sleep(delay)
        for name, text in answers.items():
            if f"[{name}]" in prompt:
                if isinstance(text, Exception):
                    raise text
                return text
        return ""
    return runner


class CouncilTest(unittest.TestCase):
    def test_combines_members_and_base_rate(self):
        r = council.review(CASE, track=[], runner=fake({
            "skeptic": '{"yes_pct": 40, "verdict": "against", "why": "late in the range"}',
            "tape": 'Sure. {"yes_pct": 70, "verdict": "for", "why": "clean break on volume"}',
        }))
        self.assertEqual(r["members"]["skeptic"]["yes_pct"], 40)
        self.assertEqual(r["members"]["tape"]["yes_pct"], 70)
        self.assertEqual(r["members"]["base_rate"]["yes_pct"], 50.0)  # no history yet
        self.assertAlmostEqual(r["yes_pct"], 53.3, places=1)

    def test_base_rate_shrinks_toward_50(self):
        track = [{"setup": "ORB long", "won": True}] * 8 + [{"setup": "ORB long", "won": False}] * 2
        self.assertEqual(council.base_rate(track, "ORB long")["yes_pct"], 65.0)  # (8+5)/(10+10)
        self.assertEqual(council.base_rate(track, "VWAP reclaim")["n"], 0)

    def test_member_that_fails_or_times_out_is_left_out(self):
        r = council.review(CASE, track=[], runner=fake({
            "skeptic": TimeoutError("30 s"), "tape": "no json here"}))
        self.assertIn("error", r["members"]["skeptic"])
        self.assertIn("error", r["members"]["tape"])
        self.assertEqual(r["yes_pct"], 50.0)  # only the base rate answered

    def test_members_never_see_the_ais_pitch(self):
        seen = []

        def runner(prompt, timeout):
            seen.append(prompt)
            return '{"yes_pct": 50, "verdict": "split", "why": "-"}'
        council.review(dict(CASE, agent_reasons="I love this trade"), track=[], runner=runner)
        self.assertTrue(seen and all("I love this trade" not in p for p in seen))

    def test_members_run_in_parallel(self):
        start = time.monotonic()
        council.review(CASE, track=[], runner=fake({"skeptic": '{"yes_pct": 1}', "tape": '{"yes_pct": 1}'}, 0.3))
        self.assertLess(time.monotonic() - start, 0.55)

    def test_clamps_scores(self):
        r = council.review(CASE, track=[], runner=fake({"skeptic": '{"yes_pct": 140}', "tape": '{"yes_pct": -5}'}))
        self.assertEqual((r["members"]["skeptic"]["yes_pct"], r["members"]["tape"]["yes_pct"]), (95, 5))


if __name__ == "__main__":
    unittest.main()
