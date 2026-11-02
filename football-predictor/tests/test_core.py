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
        self.assertEqual(teams.resolve("Racing Santander", ["Santander", "Valencia"]), "Santander")
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


class NewsSafetyTest(unittest.TestCase):
    known = ["Man City", "Liverpool", "Arsenal"]

    def test_parse_fpl(self):
        from predictor import news
        payload = {"teams": [{"id": 1, "name": "Man City"}, {"id": 2, "name": "Liverpool"}],
                   "elements": [
                       {"team": 1, "first_name": "Erling", "second_name": "Haaland", "status": "i",
                        "chance_of_playing_next_round": 0},
                       {"team": 1, "first_name": "Phil", "second_name": "Foden", "status": "d",
                        "chance_of_playing_next_round": 50},
                       {"team": 2, "first_name": "Mohamed", "second_name": "Salah", "status": "a",
                        "chance_of_playing_next_round": None}]}
        n = news.parse_fpl(payload, self.known)
        self.assertEqual(n["Man City"].out, ["Erling Haaland"])
        self.assertEqual(n["Man City"].doubtful, ["Phil Foden"])
        self.assertNotIn("Liverpool", n)

    def test_parse_api_football(self):
        from predictor import news
        rows = [{"player": {"name": "E. Haaland", "type": "Missing Fixture", "reason": "Injury"},
                 "team": {"name": "Manchester City"}},
                {"player": {"name": "B. Saka", "type": "Questionable", "reason": "Knock"},
                 "team": {"name": "Arsenal"}}]
        n = news.parse_api_football(rows, self.known)
        self.assertEqual(n["Man City"].out, ["E. Haaland"])
        self.assertEqual(n["Arsenal"].doubtful, ["B. Saka"])

    def _shares(self):
        from predictor import absences
        return absences.attack_shares(pd.DataFrame({
            "team": ["T"] * 3, "player": ["Erling Haaland", "Phil Foden", "Ederson"],
            "minutes": [3000, 2500, 3420], "games": [36, 33, 38],
            "npxG": [20.0, 6.0, 0.0], "xA": [4.0, 6.0, 0.1]}), "T")

    def test_screen_rules(self):
        from predictor import news, safety
        bet = value.Bet("1", 0.6, 1.9, 0.14, 0.02)
        big = value.Bet("2", 0.5, 2.5, 0.25, 0.02)
        sh = self._shares()
        none = news.FixtureNews(False, "", news.TeamNews(), news.TeamNews(), note="no key")
        kept, skipped = safety.screen([bet], none, sh, sh)
        self.assertEqual(kept, [])
        self.assertIn("No team news", skipped[0][1])
        kept, _ = safety.screen([bet], none, sh, sh, manual_ok=True)
        self.assertEqual(kept, [bet])
        ok = news.FixtureNews(True, "FPL", news.TeamNews(), news.TeamNews())
        kept, skipped = safety.screen([bet, big], ok, sh, sh)
        self.assertEqual(kept, [bet])
        self.assertIn("too large", skipped[0][1])
        doubt = news.FixtureNews(True, "FPL", news.TeamNews(doubtful=["E. Haaland"]), news.TeamNews())
        kept, skipped = safety.screen([bet], doubt, sh, sh)
        self.assertEqual(kept, [])
        self.assertIn("Haaland", skipped[0][1])

    def test_bettable_odds_matches_the_rules(self):
        from predictor import safety
        self.assertEqual(safety.bettable_odds("1", 0.5), (2.10, 2.30))
        lo, hi = safety.bettable_odds("over_2.5", 0.6)
        self.assertEqual(len(value.find_value({"over_2.5": 0.6}, {"over_2.5": lo})), 1)
        self.assertEqual(value.find_value({"over_2.5": 0.6}, {"over_2.5": lo - 0.01}), [])
        self.assertLessEqual(0.6 * hi - 1, safety.MAX_EDGE)
        self.assertEqual(safety.bettable_odds("1", 0.27), (3.89, 4.0))  # capped at MAX_ODDS
        self.assertIsNone(safety.bettable_odds("btts_yes", 0.6))       # no proven skill
        self.assertIsNone(safety.bettable_odds("2", 0.2))              # long shot


class FixturesTest(unittest.TestCase):
    def test_parse_football_data(self):
        from predictor import fixtures
        raw = pd.DataFrame({"Div": ["E0", "SP1"], "Date": ["31/10/2026", "01/11/2026"], "Time": ["12:30", "20:00"],
                            "HomeTeam": ["Chelsea", "Betis"], "AwayTeam": ["Man United", "Malaga"],
                            "Referee": ["P Bankes", None], "AvgH": [1.81, None], "B365H": [1.83, 1.5],
                            "Avg>2.5": [1.55, 1.7]})
        fx = fixtures.parse_football_data(raw)
        self.assertEqual(fx["kickoff"][0], pd.Timestamp("2026-10-31 12:30"))
        self.assertEqual(fx["odds:1"].tolist(), [1.81, 1.5])  # market average, else Bet365
        self.assertTrue(pd.isna(fx["referee"][1]))
        self.assertTrue(fx["odds:X"].isna().all())

    def test_parse_understat_skips_played_and_renames(self):
        from predictor import fixtures
        dates = [{"isResult": True, "h": {"title": "Arsenal"}, "a": {"title": "Chelsea"},
                  "datetime": "2026-10-20 15:00:00"},
                 {"isResult": False, "h": {"title": "Manchester United"}, "a": {"title": "Arsenal"},
                  "datetime": "2026-11-07 17:30:00"},
                 {"isResult": False, "h": {"title": "Unknown FC"}, "a": {"title": "Arsenal"},
                  "datetime": "2026-11-08 17:30:00"}]
        fx = fixtures.parse_understat(dates, "E0", ["Arsenal", "Chelsea", "Man United"])
        self.assertEqual(fx[["home", "away"]].values.tolist(), [["Man United", "Arsenal"]])

    def test_select_window_timezone_and_duplicates(self):
        from datetime import timedelta, timezone
        from predictor import fixtures
        fx = pd.DataFrame({
            "league": ["E0", "E0", "E0", "E0", "E0"],
            "kickoff": pd.to_datetime(["2026-10-31 11:00", "2026-10-31 15:00", "2026-10-31 15:00",
                                       "2026-11-02 20:00", "2026-11-03 20:00"]),
            "home": ["A", "C", "C", "E", "G"], "away": ["B", "D", "D", "F", "H"],
            "referee": [None, "Ref", None, None, None], "source": ["fd", "fd", "understat", "fd", "fd"]})
        wat = timezone(timedelta(hours=1))  # UK is on GMT after 25 Oct 2026, so local = UK + 1h
        out = fixtures.select(fx, pd.Timestamp("2026-10-31 13:00"), 3, tz=wat)
        # 11:00 UK (12:00 local) already started; 3 Nov is outside a 3-day window; C v D listed once
        self.assertEqual(out["home"].tolist(), ["C", "E"])
        self.assertEqual(out["kickoff"][0], pd.Timestamp("2026-10-31 16:00"))
        self.assertEqual(out["referee"][0], "Ref")
        self.assertEqual(out["date"][1], pd.Timestamp("2026-11-02"))

    def test_missing_results_only_adds_what_football_data_lacks(self):
        from predictor import xg
        fd = pd.DataFrame({"date": pd.to_datetime(["2026-10-25", "2026-10-26", "2026-09-01"]),
                           "home": ["Rennes", "Lille", "Nice"], "away": ["Paris SG", "Lens", "Rennes"],
                           "hg": [2, 1, 0], "ag": [2, 0, 1]})

        def game(day, h, a, hg=1, ag=0):
            return {"isResult": True, "datetime": f"{day} 20:00:00", "h": {"title": h}, "a": {"title": a},
                    "goals": {"h": str(hg), "a": str(ag)}, "xG": {"h": "1.1", "a": "0.4"}}
        dates = [game("2026-10-25", "Paris Saint Germain", "Rennes"),   # listed the other way round: skip
                 game("2026-10-30", "Le Havre", "Paris Saint Germain", 1, 5),  # new: add
                 game("2026-10-20", "Nice", "Rennes"),                   # fixture already played: skip
                 game("2026-08-01", "Lille", "Le Havre"),               # older than the window: skip
                 {"isResult": False, "datetime": "2026-11-01 20:00:00", "h": {"title": "Lens"},
                  "a": {"title": "Lille"}, "goals": {"h": None, "a": None}, "xG": {"h": None, "a": None}}]
        fd_known = pd.concat([fd, pd.DataFrame({"date": [pd.Timestamp("2026-08-10")], "home": ["Le Havre"],
                                                "away": ["Lens"], "hg": [0], "ag": [0]})])
        out = xg.missing_results(fd_known, dates, "F1", 2026)
        self.assertEqual(out[["home", "away", "hg", "ag"]].values.tolist(), [["Le Havre", "Paris SG", 1.0, 5.0]])
        self.assertEqual(out["xg_h"][0], 1.1)

    def test_normalise_fills_optional_columns(self):
        from predictor import predict
        fx = predict.normalise_fixtures(pd.DataFrame({"league": ["E0"], "home": ["A"], "away": ["B"]}))
        self.assertEqual((fx["home_adj"][0], fx["away_adj"][0]), (1.0, 1.0))
        self.assertIsNone(fx["home_missing"][0])


class HistoryTest(unittest.TestCase):
    def matches(self):
        return pd.DataFrame({
            "league": ["SP2", "SP2", "SP1", "SP1", "SP1"], "season": [2023, 2023, 2025, 2025, 2026],
            "date": pd.to_datetime(["2023-10-01", "2024-03-01", "2025-11-08", "2026-01-31", "2026-10-25"]),
            "home": ["Levante", "Ath Madrid", "Ath Madrid", "Levante", "Levante"],
            "away": ["Ath Madrid", "Levante", "Levante", "Ath Madrid", "Betis"],
            "hg": [2, 1, 3, 0, 1], "ag": [1, 1, 1, 0, 2]})

    def test_head_to_head_newest_first_across_divisions(self):
        from predictor import history
        h = history.head_to_head(self.matches(), "Levante", "Ath Madrid", pd.Timestamp("2026-10-31"))
        self.assertEqual(h["Match"].tolist(), ["Levante 0-0 Ath Madrid", "Ath Madrid 3-1 Levante",
                                               "Ath Madrid 1-1 Levante", "Levante 2-1 Ath Madrid"])
        self.assertEqual(h["Competition"].tolist()[-1], "La Liga 2")
        self.assertEqual(history.record(h, "Levante", "Ath Madrid"), "Levante 1 wins · 2 draws · Ath Madrid 1 wins")

    def test_form_from_the_teams_side_and_before_the_match(self):
        from predictor import history
        f = history.form(self.matches(), "Levante", pd.Timestamp("2026-10-25"), n=3)
        self.assertEqual(f["Result"].tolist(), ["D", "L", "D"])   # the 25 Oct match is excluded
        self.assertEqual(f["Score"].tolist(), ["0-0", "1-3", "1-1"])
        self.assertEqual(f[""].tolist(), ["H", "A", "A"])


class ReviewTest(unittest.TestCase):
    def test_parse_espn_and_grade(self):
        from predictor import news, picks, review

        def event(home, away, hs, as_, done):
            return {"date": "2026-10-31T15:00Z", "status": {"type": {"completed": done, "description": "x"}},
                    "competitions": [{"competitors": [
                        {"homeAway": "home", "score": hs, "team": {"displayName": home, "shortDisplayName": home}},
                        {"homeAway": "away", "score": as_, "team": {"displayName": away, "shortDisplayName": away}}]}]}
        known = ["Hull", "Ipswich", "Man City", "Brighton"]
        sc = review.parse_espn([event("Hull City", "Ipswich Town", "2", "2", True),
                                event("Manchester City", "Brighton & Hove Albion", "0", "0", False)], "E0", known)
        self.assertEqual(sc[["home", "away"]].values.tolist(), [["Hull", "Ipswich"], ["Man City", "Brighton"]])
        self.assertTrue(sc["hg"].isna()[1])   # not finished: no score

        probs = markets.goal_markets(ratings.score_matrix(1.6, 1.1, -0.05))
        fn = news.FixtureNews(True, "FPL", news.TeamNews(), news.TeamNews())
        res = [{"league": "E0", "home": "Hull", "away": "Ipswich", "pred": {"probs": probs},
                "odds": {"1": 2.0, "X": 3.5, "2": 4.0}, "picks": picks.best_picks(probs), "withheld": None,
                "bets": [value.Bet("X", 0.3, 3.5, 0.05, 0.01)], "skipped": [], "news": fn}]
        m, p = review.grade(res, sc)
        self.assertEqual(m["Score"].tolist(), ["2-2"])
        self.assertFalse(m["Model right"][0])        # model said home win
        bet = p[p["Kind"] == "Value bet"].iloc[0]
        self.assertTrue(bet["Won"])                  # the draw came in
        s = review.summary(m, p)
        self.assertAlmostEqual(s["Value bet"]["profit_units"], 2.5)


class SportyBetTest(unittest.TestCase):
    def tournaments(self):
        def market(mid, outcomes, spec=None, status=0):
            m = {"id": mid, "status": status, "outcomes": [{"id": o, "odds": str(x), "isActive": 1}
                                                           for o, x in outcomes]}
            if spec:
                m["specifier"] = spec
            return m
        return [{"events": [{"eventId": "sr:match:1", "homeTeamName": "Liverpool", "awayTeamName": "Arsenal",
                             "estimateStartTime": 1793550600000,
                             "markets": [market("1", [("1", 2.6), ("2", 3.5), ("3", 2.5)]),
                                         market("10", [("9", 1.5), ("10", 1.3), ("11", 1.42)]),
                                         market("18", [("12", 1.7), ("13", 2.1)], "total=2.5"),
                                         market("18", [("12", 1.3), ("13", 3.4)], "total=2"),   # whole line: ignored
                                         market("29", [("74", 1.6), ("76", 2.2)], status=2)]},  # suspended
                            {"eventId": "sr:match:2", "homeTeamName": "Unknown FC", "awayTeamName": "Arsenal",
                             "estimateStartTime": 1793550600000, "markets": []}]}]

    def test_parse_events(self):
        from predictor import sportybet
        ev = sportybet.parse_events(self.tournaments(), "E0", ["Liverpool", "Arsenal"])
        self.assertEqual(len(ev), 1)
        r = ev.iloc[0]
        self.assertEqual((r["event_id"], r["home"], r["away"]), ("sr:match:1", "Liverpool", "Arsenal"))
        self.assertEqual((r["odds:1"], r["odds:X2"], r["odds:over_2.5"], r["odds:under_2.5"]), (2.6, 1.42, 1.7, 2.1))
        self.assertNotIn("odds:btts_yes", ev.columns)

    def test_merge_odds_and_selection(self):
        from predictor import sportybet
        ev = sportybet.parse_events(self.tournaments(), "E0", ["Liverpool", "Arsenal"])
        fx = pd.DataFrame({"league": ["E0", "E0"], "home": ["Liverpool", "Chelsea"], "away": ["Arsenal", "Fulham"],
                           "odds:1": [2.33, 1.9], "odds:under_2.5": [2.0, 2.2]})
        out = sportybet.merge_odds(fx, ev)
        self.assertEqual(out["odds_source"].tolist(), ["SportyBet", "Bookmaker average"])
        self.assertEqual(out["odds:1"].tolist(), [2.6, 1.9])
        self.assertEqual(out["odds:X2"][0], 1.42)
        self.assertTrue(pd.isna(out["odds:X2"][1]))
        self.assertEqual(out["event_id"][0], "sr:match:1")
        self.assertEqual(sportybet.selection("sr:match:1", "X2"),
                         {"eventId": "sr:match:1", "marketId": "10", "specifier": None, "outcomeId": "11"})
        self.assertEqual(sportybet.selection("sr:match:1", "home_over_0.5")["specifier"], "total=0.5")

    def test_events_pages_ten_at_a_time(self):
        from unittest import mock
        from predictor import sportybet
        calls = []

        def fake_call(path, body=None, **params):   # the feed sends <= 10 events per page
            calls.append(params)
            start = (params["pageNum"] - 1) * params["pageSize"]
            evs = [{"eventId": f"sr:match:{i}", "homeTeamName": "Liverpool", "awayTeamName": "Arsenal",
                    "estimateStartTime": 1793550600000, "markets": []} for i in range(start, min(start + 10, 24))]
            return {"totalNum": 24, "tournaments": [{"events": evs}]}
        with mock.patch.object(sportybet, "_call", fake_call):
            ev = sportybet.events("E0", ["Liverpool", "Arsenal"])
        self.assertEqual(len(ev), 24)
        self.assertEqual([c["pageNum"] for c in calls], [1, 2, 3])
        self.assertTrue(all(c["pageSize"] == sportybet.PAGE_SIZE for c in calls))

    def test_add_unlisted(self):
        from predictor import sportybet
        fx = pd.DataFrame({"league": ["E0"], "home": ["Liverpool"], "away": ["Arsenal"],
                           "kickoff": [pd.Timestamp("2026-11-01 17:30")], "odds:1": [2.6]})
        sb = pd.DataFrame({"league": ["E0", "E0", "E0", "E0"], "event_id": ["a", "b", "c", "d"],
                           "home": ["Liverpool", "Chelsea", "Fulham", None], "away": ["Arsenal", "Leeds", "Wolves", "X"],
                           "sb_home": ["", "", "", "X FC"], "sb_away": ["", "", "", ""],
                           "kickoff": pd.to_datetime(["2026-11-01 17:30", "2026-11-05 20:00", "2026-11-20 15:00",
                                                      "2026-11-05 20:00"]),
                           "odds:1": [2.6, 1.8, 2.0, 3.0]})
        out = sportybet.add_unlisted(fx, sb, pd.Timestamp("2026-11-01 12:00"), pd.Timestamp("2026-11-08"))
        self.assertEqual(out["home"].tolist(), ["Liverpool", "Chelsea"])     # listed, in window, named only
        added = out.iloc[1]
        self.assertEqual((added["odds_source"], added["event_id"], added["date"]),
                         ("SportyBet", "b", pd.Timestamp("2026-11-05")))
        self.assertNotIn("sb_home", out.columns)

    def test_parse_events_keep_unknown(self):
        from predictor import sportybet
        ev = sportybet.parse_events(self.tournaments(), "E0", ["Liverpool", "Arsenal"], keep_unknown=True)
        self.assertEqual(len(ev), 2)
        self.assertEqual(ev["sb_home"].tolist(), ["Liverpool", "Unknown FC"])
        self.assertTrue(pd.isna(ev["home"][1]))
        self.assertEqual(ev["away"][1], "Arsenal")


class AccaTest(unittest.TestCase):
    @staticmethod
    def leg(match, market, odds, q, p=None):
        from predictor import acca
        home, away = match.split("-")
        return acca.Leg({"home": home, "away": away, "fx": {"kickoff": pd.Timestamp("2026-11-01")}},
                        market, odds, q, p or q)

    def test_build_matches_brute_force(self):
        import itertools
        import math
        from predictor import acca
        rng = np.random.default_rng(3)
        legs = []
        for i in range(8):
            for mk in ("1X", "over_1.5"):
                o = float(rng.uniform(1.2, 1.9))
                legs.append(self.leg(f"H{i}-A{i}", mk, round(o, 2), min(0.95, 1 / o / float(rng.uniform(1.0, 1.08)))))
        target = 6.0
        got = acca.build(legs, target)
        best, best_p = None, -1.0
        by_match = {}
        for leg in legs:
            by_match.setdefault(leg.match, []).append(leg)
        options = [[None] + g for g in by_match.values()]
        for combo in itertools.product(*options):
            chosen = [c for c in combo if c is not None]
            odds = math.prod(c.odds for c in chosen)
            if chosen and target <= odds <= target * acca.OVERSHOOT:
                p = math.prod(c.book_prob for c in chosen)
                if p > best_p:
                    best, best_p = chosen, p
        self.assertAlmostEqual(acca.summary(got)["chance"], best_p, places=3)
        self.assertEqual(len({leg.match for leg in got}), len(got))   # one leg per match

    def test_build_prefers_fewer_fairer_legs_and_reports_impossible(self):
        from predictor import acca
        short = [self.leg(f"S{i}-T{i}", "1X", 1.25, 0.76) for i in range(12)]    # 5% margin each
        long_ = [self.leg(f"L{i}-M{i}", "1", 3.2, 0.30) for i in range(2)]       # 4% margin each
        got = acca.build(short + long_, 10.0)
        self.assertEqual(sorted(leg.odds for leg in got), [3.2, 3.2])
        self.assertEqual(acca.build(short[:3], 10.0), [])

    def test_alternatives_and_by_league(self):
        from predictor import acca
        legs = [self.leg(f"H{i}-A{i}", "1", 1.4 + 0.02 * i, 0.69 - 0.005 * i) for i in range(20)]
        for leg, league in zip(legs, ["I1"] * 14 + ["SP1"] * 2 + ["E0"] * 4):   # E0 gets the 1.72-1.78 legs
            leg.result["league"] = league
        alts = acca.alternatives(legs, 10.0)
        self.assertEqual(len(alts), 3)
        self.assertEqual([l.match for l in alts[0]], [l.match for l in acca.build(legs, 10.0)])
        matches = [l.match for t in alts for l in t]
        self.assertEqual(len(matches), len(set(matches)))                   # no match reused
        chances = [acca.summary(t)["chance"] for t in alts]
        self.assertEqual(chances, sorted(chances, reverse=True))            # best first
        per = acca.by_league(legs, 3.0)
        self.assertEqual(set(per), {"E0", "I1"})                            # SP1's 2 legs can't reach 3 odds
        self.assertTrue(all(l.result["league"] == lg for lg, t in per.items() for l in t))

    def test_mega_ticket(self):
        import math
        from predictor import acca
        rng = np.random.default_rng(5)
        legs = []
        for i in range(60):                                       # a week of matches, 2 legs each
            for mk in ("1", "1X"):
                o = round(float(rng.uniform(1.25, 1.75)), 2)
                legs.append(self.leg(f"H{i}-A{i}", mk, o, 1 / o / 1.05))
        got = acca.build(legs, 3000.0, acca.MEGA_MAX_LEGS)
        s = acca.summary(got)
        daily = acca.build(legs, 3000.0)                          # at most MAX_LEGS legs
        self.assertGreaterEqual(s["chance"], acca.summary(daily)["chance"] * 0.999 if daily else 0.0)
        self.assertGreaterEqual(s["odds"], 3000.0)                # coarse step rounds legs down: never short
        self.assertLess(s["odds"], 3000.0 * acca.OVERSHOOT * 1.15)
        self.assertLessEqual(len(got), acca.MEGA_MAX_LEGS)
        self.assertEqual(len({leg.match for leg in got}), len(got))
        # it beats the naive ticket: the most likely legs until the odds pass the target
        naive, odds = [], 1.0
        for leg in sorted(legs, key=lambda l: -l.book_prob):
            if odds >= 3000.0:
                break
            if leg.match not in {n.match for n in naive}:
                naive.append(leg)
                odds *= leg.odds
        self.assertGreaterEqual(s["chance"], math.prod(n.book_prob for n in naive))
        self.assertAlmostEqual(acca.reach(legs[:4], 1), max(l.odds for l in legs[:4]))

    def test_implied_probs(self):
        from predictor import sportybet
        q = sportybet.implied_probs({"1": 2.0, "X": 3.5, "2": 4.0, "home_over_0.5": 1.25, "home_under_0.5": 4.0})
        self.assertAlmostEqual(q["1"] + q["X"] + q["2"], 1.0)
        self.assertAlmostEqual(q["1X"], q["1"] + q["X"])
        self.assertAlmostEqual(q["home_over_0.5"] + q["home_under_0.5"], 1.0)


class PicksTest(unittest.TestCase):
    def test_best_picks(self):
        from predictor import picks
        probs = {"1": 0.55, "X": 0.25, "2": 0.20, "1X": 0.80, "X2": 0.45, "over_1.5": 0.86,
                 "over_2.5": 0.62, "under_2.5": 0.38, "btts_yes": 0.75, "home_over_0.5": 0.90}
        got = picks.best_picks(probs)
        self.assertEqual([p.market for p in got], ["1X", "over_2.5", "1"])  # >80% and BTTS left out
        lo, hi = got[0].odds_range
        self.assertGreaterEqual(0.80 * lo - 1, value.MIN_EDGE)


def code_event(eid, home, away, tournament, status, market, specifier, outcome, odds, prob, desc="Pick"):
    """One leg as SportyBet's orders/share/{code} returns it (trimmed)."""
    m = {"id": market, "desc": "Market", "status": 0,
         "outcomes": [{"id": outcome, "odds": str(odds), "probability": str(prob), "isActive": 1, "desc": desc}]}
    if specifier:
        m["specifier"] = specifier
    return {"eventId": eid, "estimateStartTime": 1793550600000, "status": status, "setScore": "1:0",
            "playedSeconds": "75:36", "matchStatus": "H2" if status else "Not start",
            "homeTeamName": home, "awayTeamName": away,
            "sport": {"category": {"tournament": {"id": tournament, "name": "T"}}}, "markets": [m]}


class CheckCodeTest(unittest.TestCase):
    known = {"E0": ["Liverpool", "Arsenal", "Chelsea", "Fulham"]}

    def code(self):
        return {"outcomes": [
            code_event("e1", "Liverpool", "Arsenal", "sr:tournament:17", 0, "1", "", "1", 2.0, 0.49),       # 2% margin
            code_event("e2", "Chelsea", "Fulham", "sr:tournament:17", 1, "18", "total=2.5", "12", 1.8, 0.53),  # live
            code_event("e3", "Club A", "Club B", "sr:tournament:999", 0, "1", "", "3", 1.5, 0.62),        # 7% margin
            code_event("e1", "Liverpool", "Arsenal", "sr:tournament:17", 0, "999", "", "1", 3.0, 0.34),   # same match
        ], "unavailableOutcomes": [{"eventId": "x"}]}

    def test_parse_code(self):
        from predictor import sportybet
        legs, gone = sportybet.parse_code(self.code(), self.known)
        self.assertEqual(gone, 1)
        self.assertEqual([leg["league"] for leg in legs], ["E0", "E0", None, "E0"])
        self.assertEqual([leg["market"] for leg in legs], ["1", "over_2.5", "2", None])
        self.assertEqual((legs[0]["home"], legs[0]["away"]), ("Liverpool", "Arsenal"))
        self.assertTrue(legs[1]["started"])
        self.assertIn("Live 1:0", legs[1]["state"])
        self.assertEqual(sportybet.raw_selection(legs[1]),
                         {"eventId": "e2", "marketId": "18", "specifier": "total=2.5", "outcomeId": "12"})
        self.assertAlmostEqual(legs[0]["prob"], 0.49)

    def test_analyse_flags_and_keep(self):
        from predictor import doctor, news, sportybet
        legs, _ = sportybet.parse_code(self.code(), self.known)
        fn = news.FixtureNews(found=False, source="", note="", home=news.TeamNews(), away=news.TeamNews())
        results = {"e1": {"pred": {"probs": {"1": 0.30}}, "withheld": None, "news": fn}}   # model far below 49%
        check = doctor.analyse(legs, results)
        problems = check["problems"].tolist()
        self.assertTrue(any("Model disagrees" in p for p in problems[0]))
        self.assertTrue(any("Already started" in p for p in problems[1]))
        self.assertTrue(any("Expensive" in p for p in problems[2]))       # 7% > median and >= 4%
        self.assertTrue(any("Same match twice" in p for p in problems[3]))
        self.assertIn("Model doesn't cover this match", check["notes"][2])
        self.assertAlmostEqual(check["margin"][0], 1 - 2.0 * 0.49)
        self.assertEqual(doctor.default_keep(check), [False, False, False, False])

    def test_improve_keeps_legs_and_hits_the_target(self):
        import math
        from predictor import acca, doctor, sportybet
        legs, _ = sportybet.parse_code(self.code(), self.known)
        def pool_leg(eid, odds, q):
            return acca.Leg({"home": eid, "away": "Z", "league": "E0", "fx": {"kickoff": pd.Timestamp("2026-11-02"),
                                                                                "event_id": eid}}, "1", odds, q, q)
        pool = [pool_leg("e1", 1.5, 0.66), pool_leg("p1", 1.6, 0.61), pool_leg("p2", 1.7, 0.58),
                pool_leg("p3", 2.5, 0.38)]
        kept, fill = doctor.improve(legs, [True, False, False, False], pool, 5.0)
        self.assertEqual([leg["event_id"] for leg in kept], ["e1"])
        self.assertNotIn("e1", [leg.result["fx"]["event_id"] for leg in fill])   # kept match not reused
        total = 2.0 * math.prod(leg.odds for leg in fill)
        self.assertTrue(5.0 <= total <= 5.0 * acca.OVERSHOOT * 1.01)   # strict: never below the target
        self.assertEqual(doctor.improve(legs, [True, True, False, False], pool, 3.0)[1], [])  # kept already reach it
        self.assertIsNone(doctor.improve(legs, [True, False, False, False], pool[:1], 50.0))

    def test_swap_one_for_one(self):
        from predictor import acca, doctor, sportybet
        legs, _ = sportybet.parse_code(self.code(), self.known)   # odds 2.0, 1.8, 1.5, 3.0

        def pool_leg(eid, odds, q):
            return acca.Leg({"home": eid, "away": "Z", "league": "E0", "fx": {"kickoff": pd.Timestamp("2026-11-02"),
                                                                                "event_id": eid}}, "1", odds, q, q)
        pool = [pool_leg("p1", 1.55, 0.63),    # near 1.5, o*p 0.977
                pool_leg("p2", 1.45, 0.67),    # near 1.5, o*p 0.972
                pool_leg("p3", 1.75, 0.56),    # near 1.8, o*p 0.98
                pool_leg("e1", 1.8, 0.56)]     # the kept leg's match: never used
        kept, swaps = doctor.swap(legs, [True, False, False, True], pool)
        self.assertEqual([leg["event_id"] for leg in kept], ["e1", "e1"])
        got = {old["odds"]: (new.result["fx"]["event_id"] if new else None) for old, new in swaps}
        self.assertEqual(got, {1.8: "p3", 1.5: "p1"})         # best-priced within 25% of each, no reuse
        kept, swaps = doctor.swap(legs, [False, False, False, False], pool[:1])
        self.assertEqual(sum(new is None for _, new in swaps), 3)   # one swap left: the others are dropped

    def test_strict_build_never_lands_below_the_target(self):
        import math
        from predictor import acca
        rng = np.random.default_rng(11)
        legs = [AccaTest.leg(f"H{i}-A{i}", "1", round(float(rng.uniform(1.2, 1.9)), 2), 0.6) for i in range(30)]
        for target in (2.37, 4.81, 6.02, 9.99, 13.7):
            got = acca.build(legs, target, strict=True)
            self.assertGreaterEqual(math.prod(leg.odds for leg in got), target)

    def test_probabilities_flow_into_tickets(self):
        from predictor import acca, sportybet
        t = SportyBetTest().tournaments()
        t[0]["events"][0]["markets"][0]["outcomes"][0]["probability"] = "0.36"
        ev = sportybet.parse_events(t, "E0", ["Liverpool", "Arsenal"])
        self.assertEqual(ev["prob:1"][0], 0.36)
        fx = pd.DataFrame({"league": ["E0"], "home": ["Liverpool"], "away": ["Arsenal"], "odds:1": [2.33]})
        self.assertEqual(sportybet.merge_odds(fx, ev)["prob:1"][0], 0.36)
        r = {"fx": {"odds_source": "SportyBet", "event_id": "sr:match:1"}, "withheld": None,
             "odds": {"1": 2.6, "X": 3.5, "2": 2.5}, "book_probs": {"1": 0.36},
             "pred": {"probs": {"1": 0.40, "X": 0.3, "2": 0.3}}}
        got = {leg.market: leg.book_prob for leg in acca.candidates([r], 0.30)}
        self.assertEqual(got["1"], 0.36)                                          # SportyBet's own, not from odds
        self.assertAlmostEqual(got["2"], sportybet.implied_probs(r["odds"])["2"])  # no probability: falls back


class OutageTest(unittest.TestCase):
    def test_understat_failure_is_remembered(self):
        from unittest import mock
        from predictor import xg
        xg.clear_cache()
        calls = []

        def down(league, season):
            calls.append(league)
            raise OSError("Temporary failure in name resolution")
        with mock.patch.object(xg, "_fetch_understat_league_json", down):
            for _ in range(3):
                with self.assertRaises(Exception):
                    xg._understat_league_json("E0", 2026)
            self.assertEqual(calls, ["E0"])                    # one try, not one per team
            xg.clear_cache()                                   # Refresh data retries at once
            with self.assertRaises(Exception):
                xg._understat_league_json("E0", 2026)
            self.assertEqual(calls, ["E0", "E0"])
        xg.clear_cache()

    def test_players_use_the_saved_copy(self):
        import os
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock
        from predictor import xg
        with tempfile.TemporaryDirectory() as tmp:
            saved = pd.DataFrame({"team": ["Arsenal"], "player": ["Saka"], "minutes": [900], "games": [10],
                                  "npxG": [3.1], "xA": [2.0]})
            path = Path(tmp) / "players_E0_2026.csv"
            saved.to_csv(path, index=False)
            boom = mock.Mock(side_effect=OSError("down"))
            with mock.patch.object(xg, "current_season", return_value=2026), \
                    mock.patch.object(xg, "_from_understat", boom), mock.patch.object(xg, "_players_mirror", boom):
                self.assertEqual(xg.load_players("E0", 2026, ["Arsenal"], Path(tmp))["player"].tolist(), ["Saka"])
                boom.assert_not_called()                       # fresh: no download at all
                old = time.time() - (xg.PLAYERS_TTL_HOURS + 1) * 3600
                os.utime(path, (old, old))
                self.assertEqual(xg.load_players("E0", 2026, ["Arsenal"], Path(tmp))["player"].tolist(), ["Saka"])
                self.assertEqual(boom.call_count, 1)           # Understat tried; the mirror wasn't needed

    def test_api_football_plan_refusal_covers_the_season(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from predictor import news
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(news, "DEFAULT_CACHE", Path(tmp)):
            refusal = {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}
            with mock.patch.object(news, "_cached_json", return_value=refusal) as cached:
                with self.assertRaises(RuntimeError):
                    news._api_football("SP1", 2026, "2026-11-02", "key")
                with self.assertRaises(RuntimeError) as err:
                    news._api_football("I1", 2026, "2026-11-07", "key")   # another league and day
                self.assertEqual(cached.call_count, 1)
                self.assertIn("Free plans", str(err.exception))


class ConsensusTest(unittest.TestCase):
    @staticmethod
    def match():
        odds = {"B365": (2.2, 3.4, 3.5, 1.9, 1.95), "Avg": (2.0, 3.3, 3.8, 1.85, 1.95),
                "AvgC": (2.1, 3.3, 3.6, 1.9, 1.9)}
        from predictor import consensus
        row = {"date": pd.Timestamp("2025-09-01"), "league": "E0", "season": 2025, "home": "A", "away": "B",
               "hg": 2, "ag": 1}
        for source in consensus.SOURCES:
            for m, o in zip(consensus.MARKETS, odds.get(source, [np.nan] * 5)):
                row[f"{source}:{m}"] = o
        return pd.DataFrame([row])

    def test_fair_removes_margin(self):
        from predictor import consensus
        df = self.match()
        plain = consensus.fair(df, "Avg", "proportional").iloc[0]
        power = consensus.fair(df, "Avg", "power").iloc[0]
        book = value.market_probs({"1": 2.0, "X": 3.3, "2": 3.8})
        self.assertAlmostEqual(plain["1"], book["1"])
        for p in (plain, power):
            self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0)
            self.assertAlmostEqual(p["over_2.5"] + p["under_2.5"], 1.0)
        # the power method takes more margin off the long shot than the favourite
        self.assertGreater(power["1"], plain["1"])
        self.assertLess(power["2"], plain["2"])
        self.assertTrue(consensus.fair(df, "PSC").isna().all().all())

    def test_edges(self):
        from predictor import consensus
        rows = consensus.edges(self.match(), "B365", "Avg").set_index("market")
        p_ref = consensus.fair(self.match(), "Avg").iloc[0]
        p_close = consensus.fair(self.match(), "AvgC").iloc[0]   # no Pinnacle closing: falls back to average
        self.assertAlmostEqual(rows.loc["1", "edge"], 2.2 * p_ref["1"] - 1)
        self.assertAlmostEqual(rows.loc["1", "clv"], 2.2 * p_close["1"] - 1)
        self.assertEqual((rows.loc["1", "won"], rows.loc["X", "won"], rows.loc["over_2.5", "won"]), (1.0, 0.0, 1.0))
        self.assertAlmostEqual(rows.loc["1", "profit"], 1.2)
        self.assertEqual(rows.loc["under_2.5", "profit"], -1.0)

    def test_decision_rule(self):
        from predictor import consensus
        steady = pd.DataFrame({"won": [1, 1, 1, 0] * 50, "price": 1.8, "profit": [0.8, 0.8, 0.8, -1.0] * 50,
                               "clv": 0.02})
        self.assertTrue(consensus.promising(consensus.stats(steady)))
        self.assertFalse(consensus.promising(consensus.stats(steady.head(100))))   # too few bets
        self.assertFalse(consensus.promising(consensus.stats(steady.assign(clv=-0.01))))


class ProfitTestTest(unittest.TestCase):
    def test_rules_sources_and_clv(self):
        from predictor import backtest
        rows = []
        for (d, season, home, p1, o1) in ((pd.Timestamp("2023-09-01"), 2023, "A", 0.6, 1.9),
                                          (pd.Timestamp("2025-09-01"), 2025, "A", 0.6, 1.9),   # edge 14%: bet
                                          (pd.Timestamp("2025-09-02"), 2025, "C", 0.6, 2.0)):  # 20%: capped
            for market, p, o, won in (("1", p1, o1, 1.0), ("X", 0.25, 4.0, 0.0), ("2", 0.15, 7.0, 0.0)):
                rows.append({"date": d, "league": "E0", "season": season, "home": home, "away": "B",
                             "market": market, "prob": p, "won": won, "odds": o})
        res = pd.DataFrame(rows)
        extra = pd.DataFrame([{"date": pd.Timestamp("2025-09-01"), "league": "E0", "home": "A", "away": "B",
                               "B365:1": 1.8, "B365:X": 3.5, "B365:2": 6.0,
                               "B365:over_2.5": np.nan, "B365:under_2.5": np.nan}])
        bets, ll = backtest.profit_test(res, [2025], extra)
        closing = bets[bets["source"] == "closing"]
        self.assertEqual(closing[["home", "market"]].values.tolist(), [["A", "1"]])
        self.assertAlmostEqual(closing["profit"].iloc[0], 0.9)
        b365 = bets[bets["source"] == "bet365"].iloc[0]
        fair = value.market_probs({"1": 1.9, "X": 4.0, "2": 7.0})
        self.assertAlmostEqual(b365["clv"], 1.8 * fair["1"] - 1)
        self.assertEqual(len(ll), 2)


class SnapshotTest(unittest.TestCase):
    def test_append_keeps_one_header_and_column_order(self):
        import tempfile
        from pathlib import Path
        from predictor import snapshot
        with tempfile.TemporaryDirectory() as tmp:
            first = pd.DataFrame([{"odds:1": 2.0, "taken_at": pd.Timestamp("2026-11-01 08:00"), "event_id": "e1"}])
            second = pd.DataFrame([{"event_id": "e1", "taken_at": pd.Timestamp("2026-11-01 10:00"), "odds:X": 3.1}])
            p1 = snapshot.append(first, "sportybet", snapshot.SB_COLUMNS, Path(tmp))
            p2 = snapshot.append(second, "sportybet", snapshot.SB_COLUMNS, Path(tmp))
            self.assertEqual(p1, p2)
            self.assertEqual(p1.name, "sportybet_2026-11.csv")
            back = snapshot.load_log("sportybet", Path(tmp))
            self.assertEqual(list(back.columns), snapshot.SB_COLUMNS)
            self.assertEqual(back["odds:1"].tolist()[0], 2.0)
            self.assertEqual(back["odds:X"].tolist()[1], 3.1)

    def test_append_rewrites_an_older_header(self):
        import tempfile
        from pathlib import Path
        from predictor import snapshot
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sportybet_2026-11.csv"
            pd.DataFrame([{"taken_at": "2026-11-01 08:00", "event_id": "e1", "odds:1": 2.0}]).to_csv(path, index=False)
            snapshot.append(pd.DataFrame([{"taken_at": pd.Timestamp("2026-11-01 10:00"), "event_id": "e1",
                                           "odds:1": 1.9, "prob:1": 0.5}]), "sportybet", snapshot.SB_COLUMNS, Path(tmp))
            back = pd.read_csv(path)
            self.assertEqual(back["odds:1"].tolist(), [2.0, 1.9])
            self.assertTrue(pd.isna(back["prob:1"][0]))
            self.assertEqual(back["prob:1"][1], 0.5)
            self.assertEqual(list(back.columns), snapshot.SB_COLUMNS)

    def test_closing_is_last_snapshot_before_kickoff(self):
        from predictor import snapshot
        log = pd.DataFrame({"event_id": ["e1"] * 3, "kickoff": pd.Timestamp("2026-11-01 15:00"),
                            "taken_at": pd.to_datetime(["2026-11-01 09:00", "2026-11-01 13:00",
                                                        "2026-11-01 16:00"]), "odds:1": [2.0, 1.9, 1.5]})
        self.assertEqual(snapshot.closing(log)["odds:1"].tolist(), [1.9])
