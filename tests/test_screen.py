"""trader.screen: guardrails on every NSE stock, then a ranked shortlist."""
import unittest
from datetime import datetime

from trader import screen

AT_1015 = datetime(2026, 12, 14, 10, 15)  # 60 of 375 minutes gone


def quote(price=500.0, prev=490.0, open_=495.0, volume=2_000_000, bid=None, ask=None, up=None, low=None):
    bid = bid or price - 0.1
    ask = ask or price + 0.1
    return {"last_price": price, "net_change": price - prev, "ohlc": {"open": open_}, "volume": volume,
            "average_price": price, "upper_circuit_limit": up or price * 1.2, "lower_circuit_limit": low or price * 0.8,
            "depth": {"buy": [{"price": bid}], "sell": [{"price": ask}]}}


BASE = {"avg_volume": 3_000_000, "avg_turnover_cr": 150.0, "prev_close": 490.0}


def run(quotes, base=None, core=("AAA",), news=(), top=20):
    return screen.shortlist(quotes, base or {s: BASE for s in quotes}, set(core), set(news), AT_1015, top=top)


class GuardrailTest(unittest.TestCase):
    def test_passes_a_liquid_stock(self):
        self.assertEqual([r["symbol"] for r in run({"AAA": quote()})], ["AAA"])

    def test_rejects_cheap_wide_spread_near_circuit_or_thin(self):
        cases = {
            "price": quote(price=40, prev=39, open_=39.5),
            "spread": quote(bid=499.0, ask=501.0),
            "circuit": quote(up=505.0),
            "no book": dict(quote(), depth={"buy": [], "sell": []}),
        }
        for why, q in cases.items():
            self.assertEqual(run({"AAA": q}), [], why)
        thin = dict(BASE, avg_turnover_cr=20.0)
        self.assertEqual(run({"AAA": quote()}, base={"AAA": thin}), [])

    def test_outside_the_500_needs_news_or_a_big_move_and_enough_money_today(self):
        quiet = quote(price=500, prev=498, open_=499, volume=2_000_000)
        mover = quote(price=520, prev=500, open_=505, volume=2_000_000)
        self.assertEqual(run({"ZZZ": quiet}, core=()), [])
        self.assertEqual([r["symbol"] for r in run({"ZZZ": mover}, core=())], ["ZZZ"])
        self.assertEqual([r["symbol"] for r in run({"ZZZ": quiet}, core=(), news=("ZZZ",))], ["ZZZ"])
        tiny = quote(price=520, prev=500, open_=505, volume=10_000)
        self.assertEqual(run({"ZZZ": tiny}, core=()), [])


class RankTest(unittest.TestCase):
    def test_more_active_stocks_rank_higher_and_reasons_are_given(self):
        rows = run({"AAA": quote(volume=500_000), "BBB": quote(volume=4_000_000, price=510)},
                   core=("AAA", "BBB"), news=("BBB",))
        self.assertEqual([r["symbol"] for r in rows], ["BBB", "AAA"])
        self.assertIn("news", rows[0]["why"])
        self.assertGreater(rows[0]["rvol"], rows[1]["rvol"])

    def test_top_n(self):
        quotes = {f"S{i}": quote(volume=1_000_000 + i) for i in range(30)}
        self.assertEqual(len(run(quotes, core=tuple(quotes), top=20)), 20)


if __name__ == "__main__":
    unittest.main()
