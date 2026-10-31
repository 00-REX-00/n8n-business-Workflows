import unittest

import numpy as np
import pandas as pd

from predictor import markets, ratings, teams, value


def synthetic_league(seed=0, rounds=4):
    """Double round-robin with known strengths."""
    rng = np.random.default_rng(seed)
    names = [f"T{i}" for i in range(10)]
    att = np.linspace(0.4, -0.4, 10)
    dfn = -att
    rows, day = [], pd.Timestamp("2024-08-01")
    for _ in range(rounds):
        for h in range(10):
            for a in range(10):
                if h == a:
                    continue
                lam = np.exp(0.2 + 0.25 + att[h] + dfn[a])
                mu = np.exp(0.2 + att[a] + dfn[h])
                rows.append({"date": day, "season": 2024, "home": names[h], "away": names[a],
                             "hg": rng.poisson(lam), "ag": rng.poisson(mu)})
                day += pd.Timedelta(hours=6)
    return pd.DataFrame(rows), att


class RatingsTest(unittest.TestCase):
    def test_recovers_team_order_and_home_advantage(self):
        df, att = synthetic_league()
        r = ratings.fit(df, df["date"].max() + pd.Timedelta(days=1), xi=0.0, ridge=0.1)
        fitted = np.array([r.attack[r.index[f"T{i}"]] for i in range(10)])
        self.assertGreater(np.corrcoef(fitted, att)[0, 1], 0.9)
        self.assertAlmostEqual(r.home_adv, 0.25, delta=0.1)

    def test_uses_only_past_matches(self):
        df, _ = synthetic_league()
        cutoff = df["date"].iloc[100]
        a = ratings.fit(df, cutoff)
        b = ratings.fit(df.iloc[:100], cutoff)
        np.testing.assert_allclose(a.attack, b.attack, atol=1e-6)


class MarketsTest(unittest.TestCase):
    def test_probabilities_are_consistent(self):
        m = ratings.score_matrix(1.6, 1.1, -0.05)
        p = markets.goal_markets(m)
        self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1, places=9)
        self.assertAlmostEqual(p["over_2.5"] + p["under_2.5"], 1, places=9)
        self.assertGreater(p["over_1.5"], p["over_2.5"])
        self.assertAlmostEqual(p["1X"], p["1"] + p["X"], places=9)

    def test_outcomes(self):
        row = {"hg": 2, "ag": 1, "hc": 6, "ac": 4, "hy": 2, "ay": 1, "hr": 0, "ar": 0}
        self.assertEqual(markets.outcome("1", row), 1.0)
        self.assertEqual(markets.outcome("X2", row), 0.0)
        self.assertEqual(markets.outcome("over_2.5", row), 1.0)
        self.assertEqual(markets.outcome("btts_yes", row), 1.0)
        self.assertEqual(markets.outcome("corners_over_9.5", row), 1.0)
        self.assertEqual(markets.outcome("cards_under_3.5", row), 1.0)
        self.assertIsNone(markets.outcome("dnb_1", {**row, "ag": 2}))


class ValueTest(unittest.TestCase):
    def test_no_bet_without_edge(self):
        self.assertEqual(value.find_value({"over_2.5": 0.55}, {"over_2.5": 1.75}), [])

    def test_stake_is_capped(self):
        bets = value.find_value({"1": 0.60}, {"1": 2.5})
        self.assertEqual(len(bets), 1)
        self.assertLessEqual(bets[0].stake_pct, value.MAX_STAKE)


class TeamsTest(unittest.TestCase):
    def test_resolve(self):
        known = ["Man United", "Nott'm Forest", "Ath Madrid", "Inter", "Bayern Munich"]
        self.assertEqual(teams.resolve("Manchester United", known), "Man United")
        self.assertEqual(teams.resolve("Nottingham Forest", known), "Nott'm Forest")
        self.assertEqual(teams.resolve("Atlético Madrid", known), "Ath Madrid")
        self.assertEqual(teams.resolve("Inter Milan", known), "Inter")
        with self.assertRaises(KeyError):
            teams.resolve("Sporting Lisbon", known)


if __name__ == "__main__":
    unittest.main()


class CalibrationTest(unittest.TestCase):
    def test_apply_keeps_markets_consistent(self):
        from predictor import calibration
        raw = markets.goal_markets(ratings.score_matrix(1.7, 0.9, -0.05))
        raw.update(markets.count_markets("cards", 4.0, 0.05, markets.CARD_LINES))
        params = {"1": [1.3, 0.05], "X": [1.1, 0.14], "2": [1.3, 0.2],
                  "over_1.5": [0.9, 0.2], "over_2.5": [1.0, 0.05], "cards_over_3.5": [0.7, 0.1]}
        p = calibration.apply(raw, params)
        self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1, places=9)
        self.assertAlmostEqual(p["1X"], p["1"] + p["X"], places=9)
        self.assertAlmostEqual(p["over_2.5"] + p["under_2.5"], 1, places=9)
        self.assertGreaterEqual(p["over_1.5"], p["over_2.5"])
        self.assertGreaterEqual(p["cards_over_3.5"], p["cards_over_4.5"])
        self.assertGreater(p["1"], raw["1"])  # a > 1 sharpens the favourite


class MarketProbsTest(unittest.TestCase):
    def test_removes_margin(self):
        mp = value.market_probs({"1": 2.0, "X": 3.4, "2": 3.8, "over_2.5": 1.9, "under_2.5": 1.9})
        self.assertAlmostEqual(mp["1"] + mp["X"] + mp["2"], 1, places=9)
        self.assertAlmostEqual(mp["over_2.5"], 0.5, places=9)
        self.assertNotIn("btts_yes", mp)


class TrackerTest(unittest.TestCase):
    def test_profit_and_summary(self):
        import tempfile
        from pathlib import Path
        from predictor import tracker
        path = Path(tempfile.mkdtemp()) / "bets.csv"
        tracker.add({"market": "1", "odds": 2.0, "stake": 100, "result": "won", "closing_odds": 1.9}, path)
        tracker.add({"market": "over_2.5", "odds": 1.8, "stake": 100, "result": "lost"}, path)
        tracker.add({"market": "X", "odds": 3.4, "stake": 50}, path)
        s = tracker.summary(tracker.load(path))
        self.assertEqual((s["bets"], s["settled"], s["pending"]), (3, 2, 1))
        self.assertAlmostEqual(s["profit"], 0.0)
        self.assertAlmostEqual(s["hit_rate"], 0.5)


class SlipTest(unittest.TestCase):
    def test_names_and_summary(self):
        from predictor import slip
        self.assertEqual(slip.sportybet_name("over_2.5"), ("Over/Under", "Over 2.5"))
        self.assertEqual(slip.sportybet_name("btts_yes"), ("GG/NG", "GG"))
        self.assertEqual(slip.sportybet_name("1X"), ("Double Chance", "Home or Draw"))
        legs = [slip.Leg("2026-05-24", "E0", "A", "B", "1", 2.0, 0.55),
                slip.Leg("2026-05-24", "E0", "C", "D", "over_2.5", 1.9, 0.56)]
        s = slip.summary(legs, 10000)
        self.assertAlmostEqual(s["acca_odds"], 3.8)
        self.assertAlmostEqual(s["acca_prob"], 0.55 * 0.56)
        self.assertLessEqual(s["acca_stake"], 10000 * slip.ACCA_MAX_STAKE)
        self.assertEqual(s["warnings"], [])
        legs.append(slip.Leg("2026-05-24", "E0", "A", "B", "btts_yes", 1.8, 0.5))
        self.assertTrue(any("same match" in w for w in slip.summary(legs, 10000)["warnings"]))


class AbsencesTest(unittest.TestCase):
    def players(self):
        return pd.DataFrame({
            "team": ["T"] * 4, "player": ["Star Striker", "Winger", "Defender", "Keeper"],
            "minutes": [3000, 2500, 3000, 3420], "games": [36, 33, 35, 38],
            "npxG": [20.0, 6.0, 1.0, 0.0], "xA": [4.0, 6.0, 1.0, 0.1]})

    def test_star_matters_more(self):
        from predictor import absences
        sh = absences.attack_shares(self.players(), "T")
        self.assertEqual(sh["player"][0], "Star Striker")
        star = absences.multiplier(sh, ["Star Striker"])
        keeper = absences.multiplier(sh, ["Keeper"])
        self.assertLess(star, keeper)
        self.assertGreaterEqual(star, absences.MIN_MULTIPLIER)
        self.assertEqual(absences.multiplier(sh, []), 1.0)

    def test_resolve_surname(self):
        from predictor import absences
        sh = absences.attack_shares(self.players(), "T")
        self.assertEqual(absences.resolve_players(["striker", "Nobody"], sh), (["Star Striker"], ["Nobody"]))


class XgMergeTest(unittest.TestCase):
    def test_strength_target_uses_xg_when_present(self):
        from predictor import model
        df = pd.DataFrame({"hg": [3, 0] * 150, "ag": [0, 0] * 150, "hst": [3, 3] * 150, "ast": [1, 1] * 150,
                           "xg_h": [1.0, np.nan] * 150, "xg_a": [0.5, np.nan] * 150})
        t = model._strength_target(df)
        conv = 3 * 150 / (4 * 300)
        w = model.GOAL_WEIGHT + model.SOT_WEIGHT + model.XG_WEIGHT
        self.assertAlmostEqual(t["h_str"][0], (model.GOAL_WEIGHT * 3 + model.SOT_WEIGHT * conv * 3
                                               + model.XG_WEIGHT * 1.0) / w)
        self.assertAlmostEqual(t["h_str"][1], (model.GOAL_WEIGHT * 0 + model.SOT_WEIGHT * conv * 3)
                               / (model.GOAL_WEIGHT + model.SOT_WEIGHT))
