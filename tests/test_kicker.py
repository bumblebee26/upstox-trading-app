"""lambdas.kicker: starts a GitHub workflow on schedule (the AWS kicker; GitHub's own cron can run hours late)."""
import json
import unittest
from unittest import mock

from core import ssm
from lambdas import kicker


class KickerTest(unittest.TestCase):
    def setUp(self):
        ssm._cache[kicker.TOKEN_PARAM] = "ghp_TEST"
        self.addCleanup(ssm._cache.clear)

    def test_dispatches_the_workflow_on_main_with_inputs(self):
        with mock.patch.object(kicker.http, "request", return_value=b"") as req:
            out = kicker.handler({"workflow": "trading-session.yml", "inputs": {"phase": "morning"}}, None)
        (method, url), kw = req.call_args
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.github.com/repos/bumblebee26/upstox-trading-app/actions/workflows/"
                              "trading-session.yml/dispatches")
        self.assertEqual(json.loads(kw["data"]), {"ref": "main", "inputs": {"phase": "morning"}})
        self.assertEqual(kw["headers"]["Authorization"], "Bearer ghp_TEST")
        self.assertNotIn("ghp_TEST", kw["log_url"])
        self.assertEqual(out, {"dispatched": "trading-session.yml", "inputs": {"phase": "morning"}})

    def test_only_known_workflows(self):
        with mock.patch.object(kicker.http, "request") as req:
            with self.assertRaises(ValueError):
                kicker.handler({"workflow": "anything-else.yml"}, None)
        req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
