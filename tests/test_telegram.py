"""trader.telegram and trader.messages: the owner-only filter, the feed copy, the short formats."""
import tempfile
import unittest
from unittest import mock

from core import storage
from trader import messages, telegram


class TelegramTest(unittest.TestCase):
    def setUp(self):
        self.store = storage.Local(tempfile.mkdtemp())
        self.sent = []
        patcher = mock.patch.object(telegram, "_api", side_effect=self._api)
        patcher.start()
        self.addCleanup(patcher.stop)
        for p in (mock.patch.object(telegram, "_chat_id", return_value="111"),
                  mock.patch.object(telegram.storage, "backend", return_value=self.store)):
            p.start()
            self.addCleanup(p.stop)

    def _api(self, method, **params):
        self.sent.append((method, params))
        if method == "sendMessage":
            return {"message_id": 42}
        if method == "getUpdates":
            return [
                {"update_id": 1, "message": {"chat": {"id": 111}, "text": "/ledger"}},
                {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/stop"}},  # a stranger
                {"update_id": 3, "callback_query": {"id": "c", "data": "exit:ABC", "message": {"chat": {"id": 111}}}},
                {"update_id": 4, "message_reaction": {"chat": {"id": 111}, "message_id": 42,
                                                      "new_reaction": [{"type": "emoji", "emoji": "👍"}]}},
            ]
        return True

    def test_send_returns_id_and_keeps_a_feed_copy(self):
        mid = telegram.send("hello", buttons=[[("👍", "rate:p1:up")]], now_ist="2026-12-14T10:05:03")
        self.assertEqual(mid, 42)
        self.assertEqual(self.sent[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "rate:p1:up")
        keys = self.store.list("feed/2026-12-14/")
        self.assertEqual(len(keys), 1)
        self.assertIn('"text": "hello"', self.store.get(keys[0]).decode())

    def test_only_the_owners_chat_is_obeyed(self):
        updates, offset = telegram.poll(0, wait=0)
        self.assertEqual(offset, 5)
        self.assertEqual([u["kind"] for u in updates], ["command", "button", "reaction"])
        self.assertEqual(updates[0]["text"], "/ledger")
        self.assertEqual(updates[1]["data"], "exit:ABC")
        self.assertEqual((updates[2]["message_id"], updates[2]["emoji"]), (42, "👍"))


class FormatTest(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual([messages.inr(x) for x in (712.5, 40000, 123456.7, -2500, 10000000)],
                         ["₹712.50", "₹40,000", "₹1,23,457", "-₹2,500", "₹1,00,00,000"])
        self.assertEqual(messages.inr(250, sign=True), "+₹250")

    def test_proposal_is_short_and_has_no_mock_prefix(self):
        text = messages.proposal(
            side="BUY", symbol="ABC", setup="ORB long", qty=40, entry=712.5, target=725.0, stop=706.25,
            risk_rs=250, rr=2.0, pros="broke 15-min high, 2.1x volume", cons="Nifty flat",
            council={"yes_pct": 62.0, "members": {"skeptic": {"yes_pct": 40, "why": "late"},
                                                    "tape": {"yes_pct": 70, "why": "clean"},
                                                    "base_rate": {"yes_pct": 50.0, "n": 0}}},
            decision="placed")
        lines = text.splitlines()
        self.assertEqual(lines[0], "🟢 BUY ABC · ORB long · council 62%")
        self.assertIn("40 @ ₹712.50 · 🎯 ₹725 · 🛑 ₹706.25 · risk ₹250 · 2.0R", lines[1])
        self.assertNotIn("MOCK", text)
        self.assertLessEqual(len(lines), 7)

    def test_short_shows_red(self):
        text = messages.proposal(side="SELL", symbol="XYZ", setup="VWAP loss", qty=10, entry=500, target=490,
                                 stop=505, risk_rs=50, rr=2.0, pros="", cons="", council=None, decision="placed")
        self.assertTrue(text.startswith("🔴 SHORT XYZ"))


if __name__ == "__main__":
    unittest.main()
