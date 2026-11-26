"""trader.llm_council: the full council for swing and long-term plans (members, anonymous review, chair)."""
import json
import unittest

from trader import llm_council

PLAN = {"buys": [{"symbol": "ABC", "stop": 470, "target": 560, "why": "breakout"}], "sells": [], "stops": [],
        "notes": "one buy"}


class Recorder:
    def __init__(self, chair_answer=None, fail=()):
        self.prompts = []
        self.chair_answer = chair_answer or {"buys": [], "sells": [], "stops": [], "notes": "chair dropped ABC"}
        self.fail = fail

    def __call__(self, prompt, timeout, model):
        self.prompts.append((prompt, model))
        for lens in self.fail:
            if f"lens: {lens}" in prompt.lower():
                raise TimeoutError("slow")
        if prompt.startswith("[chair]"):
            return json.dumps(self.chair_answer)
        if prompt.startswith("[review]"):
            return "1. A: strong point / flaw\nRANKING: A, B, C, D\nMISSED: nothing"
        return "ANSWER: drop ABC, earnings next week\nCONFIDENCE: medium"


class CouncilTest(unittest.TestCase):
    def test_three_stages_and_the_chair_decides(self):
        rec = Recorder()
        out = llm_council.review("swing", {"holdings": {}}, PLAN, runner=rec)
        stages = [p.split("]")[0] + "]" for p, _ in rec.prompts]
        self.assertEqual(stages.count("[member]"), 4)
        self.assertEqual(stages.count("[review]"), 4)
        self.assertEqual(stages.count("[chair]"), 1)
        self.assertEqual(out["final"]["buys"], [])
        self.assertEqual(out["final"]["notes"], "chair dropped ABC")
        self.assertEqual(len(out["members"]), 4)

    def test_reviewers_see_anonymous_answers_only(self):
        rec = Recorder()
        llm_council.review("swing", {}, PLAN, runner=rec)
        for prompt, _ in rec.prompts:
            if prompt.startswith("[review]"):
                self.assertIn("Response A", prompt)
                for lens in llm_council.LENSES:
                    self.assertNotIn(lens, prompt.lower())

    def test_members_and_reviewers_use_sonnet_and_the_chair_opus(self):
        rec = Recorder()
        llm_council.review("long_term", {}, PLAN, runner=rec)
        models = {p.split("]")[0]: m for p, m in rec.prompts}
        self.assertEqual((models["[member"], models["[review"], models["[chair"]), ("sonnet", "sonnet", "opus"))

    def test_a_failed_member_is_noted_and_the_rest_carry_on(self):
        out = llm_council.review("swing", {}, PLAN, runner=Recorder(fail=("skeptic",)))
        self.assertIn("error", out["members"]["skeptic"])
        self.assertEqual(out["final"]["notes"], "chair dropped ABC")

    def test_a_chair_without_valid_json_keeps_no_new_buys(self):
        rec = Recorder()
        rec.chair_answer = None

        def bad(prompt, timeout, model):
            rec.prompts.append((prompt, model))
            return "I think we should buy" if prompt.startswith("[chair]") else "ANSWER: ok"
        out = llm_council.review("swing", {}, PLAN, runner=bad)
        self.assertEqual(out["final"]["buys"], [])  # no valid decision means no new money at risk
        self.assertIn("chair", out["final"]["notes"])


if __name__ == "__main__":
    unittest.main()
