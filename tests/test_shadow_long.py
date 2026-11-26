"""shadows.longterm: monthly picks from fundamentals and daily bars, and the rebalance rhythm."""
import random
import unittest

from shadows import longterm as lt


def hist(values, cat):
    return {"category": cat, "history": [{"period": f"Mar {2026 - i}", "value": v} for i, v in enumerate(values)]}


def company(roce="20%", roe="18%", pe="20", sector_pe="30", ev_ebitda="12", rev=(160, 140, 120, 100),
            profit=(40, 33, 27, 22), ocf=(10, 8, -1, 6), promoters=(50, 50), fii=(20, 20), divs=()):
    return {
        "ratios": [{"name": "ROCE", "company_value": roce}, {"name": "ROE", "company_value": roe},
                   {"name": "P/E", "company_value": pe, "sector_value": sector_pe},
                   {"name": "EV/EBITDA", "company_value": ev_ebitda}],
        "income": {"income_statement": [hist(rev, "revenue"), hist(profit, "net_profit")]},
        "cashflow": {"cash_flow": [hist(ocf, "operating")]},
        "holdings": [hist(promoters, "promoters"), hist(fii, "fii")],
        "actions": [{"name": "Dividend", "amount": a, "expiry_date": dt} for a, dt in divs],
    }


def bars(seed, vol=0.01, drift=0.001, n=270):
    rnd, p, out = random.Random(seed), 100.0, []
    for _ in range(n):
        o, p = p, p * (1 + drift + rnd.gauss(0, vol))
        out.append({"open": o, "high": max(o, p), "low": min(o, p), "close": p, "volume": 10 ** 6})
    return out


class PickTest(unittest.TestCase):
    def setUp(self):
        self.data = {
            "GOOD": company(),
            "SLOW": company(rev=(105, 103, 101, 100), profit=(23, 22.5, 22, 22)),
            "DEAR": company(pe="80"),
            "WEAK": company(roce="8%", roe="7%"),
            "CASHBURN": company(ocf=(-5, -3, 2, -1)),
            "PROMO": company(promoters=(55, 50)),
            "PAYER": company(divs=[(30, "2026-08-10"), (10, "2025-11-20")]),
        }
        self.daily = {s: bars(i, vol=0.005 if s == "GOOD" else 0.02) for i, s in enumerate(self.data)}
        self.today = "2026-12-01"

    def pick(self, lid):
        return lt.targets(lid, self.data, self.daily, self.today)

    def test_quality_needs_growth_cash_flow_and_a_fair_price(self):
        picks = self.pick("L01")
        self.assertIn("GOOD", picks)
        for bad in ("SLOW", "WEAK", "CASHBURN"):
            self.assertNotIn(bad, picks)

    def test_value_garp_magic_low_vol_shareholding_dividend(self):
        self.assertNotIn("WEAK", self.pick("L04"))
        self.assertNotIn("SLOW", self.pick("L05"))      # growth under 15%
        self.assertEqual(self.pick("L06")[-1], "WEAK")  # no quality filter in the formula: it ranks last
        self.assertEqual(self.pick("L08")[0], "GOOD")   # the calmest quality stock
        self.assertEqual(self.pick("L10"), ["PROMO"])   # promoters +5 points
        self.assertEqual(self.pick("L07")[0], "PAYER")

    def test_caps(self):
        many = {f"X{i}": company() for i in range(30)}
        daily = {s: bars(i) for i, s in enumerate(many)}
        self.assertLessEqual(len(lt.targets("L01", many, daily, self.today)), 10)
        self.assertLessEqual(len(lt.targets("L03", many, daily, self.today)), 5)

    def test_at_most_two_per_industry(self):
        many = {f"X{i}": company() for i in range(8)}
        daily = {s: bars(i) for i, s in enumerate(many)}
        picks = lt.targets("L04", many, daily, self.today, industries={s: "IT" for s in many})
        self.assertEqual(len(picks), 2)
        self.assertEqual(len(lt.targets("L16", many, daily, self.today, index_members=list(many),
                                        industries={s: "IT" for s in many})), 8)  # index copies keep every member

    def test_rebalance_rhythm(self):
        self.assertTrue(lt.rebalance_due("L01", {}, "2026-12-01"))
        self.assertFalse(lt.rebalance_due("L01", {"month": "2026-12"}, "2026-12-02"))
        self.assertTrue(lt.rebalance_due("L01", {"month": "2026-12"}, "2027-01-01"))
        self.assertFalse(lt.rebalance_due("L16", {"month": "2026-12"}, "2027-02-01"))  # quarterly
        self.assertTrue(lt.rebalance_due("L16", {"month": "2026-12"}, "2027-04-01"))

    def test_catalog(self):
        self.assertEqual(set(lt.STRATEGIES), {"L01", "L02", "L03", "L04", "L05", "L06", "L07", "L08", "L09", "L10",
                                              "L15", "L16"})


if __name__ == "__main__":
    unittest.main()
