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
