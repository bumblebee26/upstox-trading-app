"""core.ssm: only /upx/ parameters, decrypted, read once."""
import unittest

from core import ssm


class FakeSSM:
    def __init__(self):
        self.calls = []

    def get_parameter(self, Name, WithDecryption):
        self.calls.append((Name, WithDecryption))
        return {"Parameter": {"Value": f"value-of-{Name}"}}


class SsmTest(unittest.TestCase):
    def setUp(self):
        ssm._cache.clear()

    def test_reads_decrypted_value(self):
        fake = FakeSSM()
        self.assertEqual(ssm.get("/upx/telegram-bot-token", client=fake), "value-of-/upx/telegram-bot-token")
        self.assertEqual(fake.calls, [("/upx/telegram-bot-token", True)])

    def test_reads_each_parameter_once(self):
        fake = FakeSSM()
        ssm.get("/upx/a", client=fake)
        ssm.get("/upx/a", client=fake)
        self.assertEqual(len(fake.calls), 1)

    def test_refuses_old_repo_parameters(self):
        for name in ("/stocks/telegram-bot-token", "/stocks-trader/github-dispatch-token", "upx/no-slash"):  # isolation-ok
            with self.assertRaises(ValueError):
                ssm.get(name, client=FakeSSM())


if __name__ == "__main__":
    unittest.main()
