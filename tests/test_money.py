"""Acceptance tests for the money rules (carried over from paper-trader's live rules, 26 Nov 2026).

These are the limits the AI can never talk its way around: sizing from the AI's stop, the loss limits,
caps, the entry window, the never-widen stop rule, the ledger maths and the ₹1 reconciliation.
"""
import subprocess
import sys
import unittest
from datetime import datetime

from trader import ledger, risk

MON_1000 = datetime(2026, 12, 14, 10, 0)  # a Monday, inside the 09:30-14:30 entry window


def fresh(pool="intraday", vix=15.0):
    s = ledger.new_pool(pool)
    ledger.new_day(s, MON_1000.date(), vix=vix)
    return s


def flat_charges(rupees):
    return lambda qty: rupees  # round-trip Upstox charges for qty shares


def gate(s, symbol="ABC", side="BUY", entry=500.0, stop=495.0, target=510.0, sector="Banks", now=MON_1000,
         charges=flat_charges(10.0), **kw):
    return risk.gate(s, symbol=symbol, side=side, entry=entry, stop=stop, target=target, sector=sector, now=now,
                     round_trip_charges=charges, **kw)


class ImportTest(unittest.TestCase):
    def test_each_module_imports_on_its_own(self):
        for mod in ("trader.risk", "trader.ledger"):
            subprocess.run([sys.executable, "-c", f"import {mod}"], check=True)


class SizingTest(unittest.TestCase):
    def test_risk_per_trade_follows_vix(self):
        self.assertEqual([risk.risk_pct_for_vix(v) for v in (15, 20, 29.9, 30, None)], [1.0, 0.75, 0.75, 0.5, 0.75])

    def test_quantity_comes_from_the_ais_stop(self):
        ok = gate(fresh())  # 1% of ₹40,000 = ₹400 risk; ₹5 a share -> 80 shares
        self.assertTrue(ok.allowed, ok.reason)
        self.assertEqual((ok.qty, ok.risk_rs), (80, 400.0))

    def test_wider_stop_means_fewer_shares_same_risk(self):
        ok = gate(fresh(), stop=490.0, target=520.0)
        self.assertEqual((ok.qty, ok.risk_rs), (40, 400.0))

    def test_one_trade_margin_capped_at_30pct_of_balance(self):
        ok = gate(fresh(), entry=2000.0, stop=1990.0, target=2020.0)
        # risk says 40 shares, but 30% of ₹40,000 x 5 leverage / ₹2,000 = 30 shares
        self.assertEqual(ok.qty, 30)

    def test_weekly_brake_halves_size(self):
        s = fresh()
        s["week"]["brake"] = True
        self.assertEqual(gate(s).qty, 40)


class GateTest(unittest.TestCase):
    def assertBlocked(self, result, words):
        self.assertFalse(result.allowed)
        self.assertIn(words, result.reason)

    def test_stop_and_target_must_be_on_the_right_sides(self):
        self.assertBlocked(gate(fresh(), stop=505.0), "stop < entry < target")
        self.assertBlocked(gate(fresh(), side="SELL", stop=495.0, target=490.0), "stop < entry < target")

    def test_entry_window(self):
        self.assertBlocked(gate(fresh(), now=MON_1000.replace(hour=9, minute=20)), "entry window")
        self.assertBlocked(gate(fresh(), now=MON_1000.replace(hour=14, minute=31)), "entry window")

    def test_min_risk_reward(self):
        self.assertBlocked(gate(fresh(), target=507.0), "risk-reward")

    def test_min_price_and_tradable(self):
        self.assertBlocked(gate(fresh(), entry=40.0, stop=39.0, target=43.0), "under ₹50")
        self.assertBlocked(gate(fresh(), tradable=False), "tradable")

    def test_user_stop_pause_breaker_stale(self):
        for flag, words in (("stopped", "/stop"), ("paused", "paused")):
            s = fresh()
            s[flag] = True
            self.assertBlocked(gate(s), words)
        self.assertBlocked(gate(fresh(), breaker_on=True), "circuit breaker")
        self.assertBlocked(gate(fresh(), data_stale=True), "stale")

    def test_caps_positions_trades_sectors(self):
        s = fresh()
        for i, sec in enumerate(("A", "B", "C", "D", "E")):
            ledger.open_position(s, f"S{i}", "BUY", 1, 500.0, 499.0, 502.0, sec, charges=0.0, now=MON_1000)
        self.assertBlocked(gate(s, sector="F"), "max 5 open")
        s = fresh()
        ledger.open_position(s, "HDFC", "BUY", 1, 500.0, 499.0, 502.0, "Banks", charges=0.0, now=MON_1000)
        self.assertBlocked(gate(s), "open per sector")
        s = fresh()
        s["sector_trades"]["Banks"] = 2
        self.assertBlocked(gate(s), "Banks trades today")
        s = fresh()
        s["trades_today"] = 10
        self.assertBlocked(gate(s), "trades for today")

    def test_already_holding(self):
        s = fresh()
        ledger.open_position(s, "ABC", "BUY", 1, 500.0, 499.0, 502.0, "IT", charges=0.0, now=MON_1000)
        self.assertBlocked(gate(s, sector="Banks"), "already holding")

    def test_daily_loss_limit_counts_open_risk(self):
        s = fresh()  # 4R = ₹1,600
        s["realized_today"] = -1400.0
        ok = gate(s)  # ₹200 room left -> 40 shares at ₹5
        self.assertEqual(ok.qty, 40)
        s["realized_today"] = -1600.0
        self.assertBlocked(gate(s), "daily loss limit")

    def test_cooloff_after_three_losses(self):
        s = fresh()
        for i in range(3):
            ledger.open_position(s, f"L{i}", "BUY", 10, 500.0, 495.0, 510.0, f"X{i}", charges=0.0, now=MON_1000)
            ledger.close_position(s, f"L{i}", 495.0, charges=0.0, now=MON_1000, reason="stop_loss")
        self.assertBlocked(gate(s), "cool-off")
        self.assertTrue(gate(s, now=MON_1000.replace(minute=31)).allowed)

    def test_costs_over_30pct_of_risk_block(self):
        self.assertBlocked(gate(fresh(), charges=flat_charges(130.0)), "costs")

    def test_charges_unavailable_blocks_entry(self):
        self.assertBlocked(gate(fresh(), charges=lambda qty: None), "charges unavailable")


class DeliveryPoolTest(unittest.TestCase):
    def test_swing_buys_only_and_caps_position_at_25pct(self):
        s = fresh("swing")
        self.assertFalse(gate(s, side="SELL", stop=510.0, target=480.0).allowed)
        ok = gate(s, entry=500.0, stop=480.0, target=560.0)  # 2% of ₹60,000 = ₹1,200 risk -> 60 shares
        self.assertEqual(ok.qty, 30)  # 25% of ₹60,000 / ₹500 = 30 shares
        ok = gate(s, now=MON_1000.replace(hour=15, minute=40), entry=500.0, stop=480.0, target=560.0)
        self.assertTrue(ok.allowed, "swing entries are not limited to the intraday window")

    def test_long_term_caps_at_15pct_and_10_holdings(self):
        s = fresh("long_term")
        self.assertEqual(gate(s, entry=1000.0, stop=750.0, target=1500.0).qty, 15)
        for i in range(10):
            ledger.open_position(s, f"L{i}", "BUY", 1, 100.0, 75.0, 200.0, f"I{i}", charges=0.0, now=MON_1000)
        self.assertFalse(gate(s, entry=1000.0, stop=750.0, target=1500.0, sector="Z").allowed)

    def test_long_term_stop_cannot_be_below_the_25pct_floor(self):
        s = fresh("long_term")
        r = gate(s, entry=1000.0, stop=700.0, target=1500.0)
        self.assertFalse(r.allowed)
        self.assertIn("25%", r.reason)


class StopTest(unittest.TestCase):
    def setUp(self):
        self.s = fresh()
        ledger.open_position(self.s, "ABC", "BUY", 10, 500.0, 495.0, 510.0, "IT", charges=0.0, now=MON_1000)
        self.p = self.s["positions"]["ABC"]

    def test_stop_may_tighten(self):
        ledger.move_stop(self.s, "ABC", 498.0)
        self.assertEqual(self.p["stop"], 498.0)

    def test_stop_may_never_widen(self):
        with self.assertRaises(risk.RuleBroken):
            ledger.move_stop(self.s, "ABC", 494.0)
        self.assertEqual(self.p["stop"], 495.0)

    def test_short_stop_may_never_widen(self):
        ledger.open_position(self.s, "XYZ", "SELL", 10, 500.0, 505.0, 490.0, "Auto", charges=0.0, now=MON_1000)
        with self.assertRaises(risk.RuleBroken):
            ledger.move_stop(self.s, "XYZ", 506.0)


class LedgerTest(unittest.TestCase):
    def test_net_pnl_after_upstox_charges_and_reconciliation(self):
        s = fresh()
        ledger.open_position(s, "ABC", "BUY", 80, 500.0, 495.0, 510.0, "IT", charges=6.5, now=MON_1000)
        net = ledger.close_position(s, "ABC", 510.0, charges=7.25, now=MON_1000, reason="target")
        self.assertEqual(net, 800.0 - 6.5 - 7.25)
        self.assertEqual(s["balance"], 40000.0 + net)
        self.assertEqual(s["realized_today"], net)
        events = [{"event": "exit", "pool": "intraday", "net_rs": net},
                  {"event": "exit", "pool": "swing", "net_rs": 500.0}]  # one journal file holds every pool
        self.assertTrue(ledger.reconciles(s, events))
        self.assertFalse(ledger.reconciles(s, [{"event": "exit", "pool": "intraday", "net_rs": net - 1.5}]))

    def test_new_day_twice_on_the_same_day_changes_nothing(self):
        s = fresh()
        s["realized_today"], s["trades_today"] = -900.0, 3
        ledger.new_day(s, MON_1000.date(), vix=15.0)  # a restart on the same day
        self.assertEqual((s["realized_today"], s["trades_today"], s["week"]["realized"]), (-900.0, 3, 0.0))

    def test_slippage_makes_every_fill_worse(self):
        self.assertEqual(ledger.slip(500.0, "BUY"), 500.25)
        self.assertEqual(ledger.slip(500.0, "SELL"), 499.75)

    def test_short_pnl(self):
        s = fresh()
        ledger.open_position(s, "XYZ", "SELL", 10, 500.0, 505.0, 490.0, "Auto", charges=0.0, now=MON_1000)
        self.assertEqual(ledger.close_position(s, "XYZ", 490.0, charges=0.0, now=MON_1000, reason="target"), 100.0)

    def test_margin_reserved_while_open(self):
        s = fresh()
        ledger.open_position(s, "ABC", "BUY", 100, 500.0, 495.0, 510.0, "IT", charges=0.0, now=MON_1000)
        self.assertEqual(ledger.free_margin(s), 40000.0 - 100 * 500.0 / 5)

    def test_new_day_resets_counters_and_monday_rolls_the_week(self):
        s = fresh()
        s["realized_today"], s["trades_today"], s["week"]["realized"] = -500.0, 4, -300.0
        ledger.new_day(s, datetime(2026, 12, 15).date(), vix=22.0)  # Tuesday
        self.assertEqual((s["realized_today"], s["trades_today"], s["day_risk_pct"]), (0.0, 0, 0.75))
        self.assertEqual(s["week"]["realized"], -800.0)
        ledger.new_day(s, datetime(2026, 12, 21).date(), vix=15.0)  # next Monday
        self.assertEqual((s["week"]["realized"], s["week"]["brake"]), (0.0, False))

    def test_weekly_brake_switches_on_at_8r(self):
        s = fresh()
        s["week"]["realized"] = -3000.0
        ledger.open_position(s, "ABC", "BUY", 40, 500.0, 495.0, 510.0, "IT", charges=0.0, now=MON_1000)
        ledger.close_position(s, "ABC", 495.0, charges=0.0, now=MON_1000, reason="stop_loss")  # -₹200: week -₹3,200 = 8R
        self.assertTrue(s["week"]["brake"])


if __name__ == "__main__":
    unittest.main()
