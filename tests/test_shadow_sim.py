"""shadows.sim: one strategy's paper day on 1-minute candles (fills, exits, sizing, costs, caps)."""
import unittest

from shadows import sim


def m(hhmm, o, h, l, c, v=1000):
    return {"ts": f"2026-12-14T{hhmm}:00+05:30", "open": o, "high": h, "low": l, "close": c, "volume": v}


def flat_after(start_hhmm, price, until="15:29"):
    h, mm = map(int, start_hhmm.split(":"))
    out = []
    while f"{h:02d}:{mm:02d}" <= until:
        out.append(m(f"{h:02d}:{mm:02d}", price, price + 0.1, price - 0.1, price))
        mm += 1
        if mm == 60:
            h, mm = h + 1, 0
    return out


def charges(key, qty, side, price):
    return 10.0


class ExitTest(unittest.TestCase):
    def trade(self, candles, exit_rule="X1", side="BUY", stop=99.0, target=None):
        sig = sim.Signal(symbol="ABC", key="K", side=side, signal_time="2026-12-14T10:00", stop=stop, target=target)
        return sim.simulate_trade(sig, candles, exit_rule, five_vwap=None)

    def test_fill_at_next_minute_open_with_slippage_then_target(self):
        candles = [m("10:00", 100, 100.2, 99.8, 100), m("10:01", 100.5, 103, 100.4, 102.9)] + flat_after("10:02", 103)
        t = self.trade(candles)
        self.assertEqual(t["entry_time"][11:16], "10:00")
        self.assertEqual(t["entry"], round(100 * 1.0005, 2))
        self.assertEqual(t["exit_reason"], "target")
        self.assertAlmostEqual(t["exit"], t["entry"] + 2 * (t["entry"] - 99.0), places=2)

    def test_stop_counts_first_when_a_candle_touches_both(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 100, 104, 98, 101)] + flat_after("10:02", 101)
        self.assertEqual(self.trade(candles)["exit_reason"], "stop")

    def test_stop_gap_through_fills_at_the_open(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 97, 97.5, 96, 97)] + flat_after("10:02", 97)
        t = self.trade(candles)
        self.assertEqual(t["exit"], round(97 * 0.9995, 2))

    def test_square_off_at_1510(self):
        candles = [m("10:00", 100, 100, 100, 100)] + flat_after("10:01", 100.5)
        t = self.trade(candles, exit_rule="X6")
        self.assertEqual((t["exit_reason"], t["exit_time"][11:16]), ("square_off", "15:10"))

    def test_trailing_stop_locks_gains(self):
        up = [m(f"10:{i:02d}", 100 + i * 0.5, 100 + i * 0.5 + 0.2, 100 + i * 0.5 - 0.1, 100 + i * 0.5 + 0.1)
              for i in range(0, 11)]  # climbs to ~105
        down = [m("10:11", 104.8, 104.9, 102.0, 102.2)] + flat_after("10:12", 102.2)
        t = self.trade(up + down, exit_rule="X3")
        self.assertEqual(t["exit_reason"], "trail")
        self.assertGreater(t["exit"], t["entry"])

    def test_time_stop_after_60_minutes(self):
        candles = [m("10:00", 100, 100, 100, 100)] + flat_after("10:01", 100.3)
        t = self.trade(candles, exit_rule="X5")
        self.assertEqual((t["exit_reason"], t["exit_time"][11:16]), ("time", "11:00"))

    def test_short_side(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 99.5, 99.6, 97, 97.1)] + flat_after("10:02", 97)
        t = self.trade(candles, side="SELL", stop=101.0)
        self.assertEqual(t["exit_reason"], "target")
        self.assertLess(t["exit"], t["entry"])

    def test_explicit_target_used(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 100, 100.8, 99.9, 100.7)] + flat_after("10:02", 100.7)
        self.assertEqual(self.trade(candles, target=100.6)["exit_reason"], "target")


class DayTest(unittest.TestCase):
    def test_sizing_costs_and_caps(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 100, 103, 100, 103)] + flat_after("10:02", 103)
        sigs = [sim.Signal(symbol=f"S{i}", key=f"K{i}", side="BUY", signal_time="2026-12-14T10:00", stop=99.0)
                for i in range(7)]
        trades = sim.run_day(sigs, {f"K{i}": candles for i in range(7)}, "X1", charges, five_vwap={})
        self.assertEqual(len(trades), 5)  # at most 5 open at once
        t = trades[0]
        self.assertEqual(t["qty"], 380)  # ₹400 risk / ₹1.05 a share, under the 30% margin cap of 599 shares
        self.assertAlmostEqual(t["net_rs"], round((t["exit"] - t["entry"]) * t["qty"] - 20.0, 2))

    def test_open_positions_never_use_more_margin_than_the_pool(self):
        candles = [m("10:00", 100, 100, 100, 100)] + flat_after("10:01", 100.2)
        sigs = [sim.Signal(symbol=f"S{i}", key="K", side="BUY", signal_time="2026-12-14T10:00", stop=99.95)
                for i in range(5)]  # tiny stops: each wants the 30% cap (₹12,000 margin)
        trades = sim.run_day(sigs, {"K": candles}, "X6", charges, five_vwap={})
        margin = sum(t["qty"] * t["entry"] / sim.LEVERAGE for t in trades)
        self.assertLessEqual(margin, sim.CAPITAL)

    def test_one_entry_per_stock_and_ten_a_day(self):
        candles = [m("10:00", 100, 100, 100, 100), m("10:01", 100, 100, 98, 98)] + flat_after("10:02", 98)
        sigs = [sim.Signal(symbol=f"S{i % 12}", key="K", side="BUY", signal_time=f"2026-12-14T1{i // 12}:{i % 12:02d}",
                           stop=99.0) for i in range(24)]
        trades = sim.run_day(sigs, {"K": candles + []}, "X1", charges, five_vwap={})
        self.assertLessEqual(len(trades), 10)
        self.assertEqual(len({t["symbol"] for t in trades}), len(trades))

    def test_charges_unavailable_skips_the_trade(self):
        candles = [m("10:00", 100, 100, 100, 100)] + flat_after("10:01", 100)
        sig = sim.Signal(symbol="A", key="K", side="BUY", signal_time="2026-12-14T10:00", stop=99.0)
        self.assertEqual(sim.run_day([sig], {"K": candles}, "X1", lambda *a: None, five_vwap={}), [])


if __name__ == "__main__":
    unittest.main()
