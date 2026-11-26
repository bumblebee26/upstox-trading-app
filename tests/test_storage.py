"""core.storage (local backend): get/put, JSON helpers, once-only claims."""
import tempfile
import unittest

from core import storage


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.s = storage.Local(tempfile.mkdtemp())

    def test_put_get_and_missing(self):
        self.s.put("a/b.json", b"hi")
        self.assertEqual(self.s.get("a/b.json"), b"hi")
        self.assertIsNone(self.s.get("nope"))

    def test_json_round_trip(self):
        storage.put_json("x.json", {"n": 1, "₹": "ok"}, store=self.s)
        self.assertEqual(storage.get_json("x.json", store=self.s), {"n": 1, "₹": "ok"})
        self.assertEqual(storage.get_json("missing.json", {"d": 0}, store=self.s), {"d": 0})

    def test_claim_succeeds_once(self):
        self.assertTrue(self.s.claim("claims/2026-12-14-morning"))
        self.assertFalse(self.s.claim("claims/2026-12-14-morning"))

    def test_list_keys_under_a_prefix(self):
        for k in ("feed/2026-12-14/1.json", "feed/2026-12-14/2.json", "feed/2026-12-15/1.json"):
            self.s.put(k, b"{}")
        self.assertEqual(self.s.list("feed/2026-12-14/"), ["feed/2026-12-14/1.json", "feed/2026-12-14/2.json"])


if __name__ == "__main__":
    unittest.main()
