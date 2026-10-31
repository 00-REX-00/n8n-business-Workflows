"""One league's full model: goals, corners and cards, plus match context."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import calibration, markets, ratings

HISTORY_SEASONS = 3          # seasons of data each fit uses
REFEREE_SHRINK = 8           # referee needs ~8 games to move halfway from the league average
# Ratings learn from a blend of three measures of attacking output: real goals,
# shots on target (converted to goals at the league rate) and Understat expected
# goals (xG) where available. xG and shots are far less noisy than goals, so
# they reveal true team strength faster. Matches without xG share its weight
# between goals and shots.
GOAL_WEIGHT = 0.25
SOT_WEIGHT = 0.25
XG_WEIGHT = 0.5
RIDGE = 4.0
XI = 0.003
# Corners and cards are steadier team habits than goals, so their ratings use
# their own settings.
COUNT_RIDGE = 20.0
COUNT_XI = 0.004


def _with_card_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hcards"] = df["hy"] + df["hr"]
    df["acards"] = df["ay"] + df["ar"]
    return df


def _dispersion(r: ratings.TeamRatings, df: pd.DataFrame, hcol: str, acol: str) -> float:
    """Negative-binomial alpha for match totals: var = mean + alpha * mean^2."""
    df = df.dropna(subset=[hcol, acol])
    df = df[df["home"].map(r.has) & df["away"].map(r.has)]
    if len(df) < 50:
        return 0.0
    mean = np.array([sum(r.expected(h, a)) for h, a in zip(df["home"], df["away"])])
    y = (df[hcol] + df[acol]).to_numpy(float)
    alpha = (((y - mean) ** 2).mean() - mean.mean()) / (mean ** 2).mean()
    return float(max(alpha, 0.0))


def _strength_target(hist: pd.DataFrame) -> pd.DataFrame | None:
    """hist with h_str/a_str: the weighted goals/shots/xG blend per match."""
    if SOT_WEIGHT == 0 and XG_WEIGHT == 0:
        return None
    sot = hist.dropna(subset=["hst", "ast"])
    has_sot = len(sot) > 200
    conv = ((sot["hg"].sum() + sot["ag"].sum()) / (sot["hst"].sum() + sot["ast"].sum())) if has_sot else 0.0
    has_xg = hist[["xg_h", "xg_a"]].notna().all(axis=1) if "xg_h" in hist else pd.Series(False, index=hist.index)
    if not has_sot and not has_xg.any():
        return None

    out = hist.copy()
    for side, g, st, xg in (("h", "hg", "hst", "xg_h"), ("a", "ag", "ast", "xg_a")):
        sot_goals = (conv * out[st]).fillna(out[g]) if has_sot else out[g]
        xg_val = out[xg] if xg in out else pd.Series(np.nan, index=out.index)
        w_sot = SOT_WEIGHT if has_sot else 0.0
        with_xg = (GOAL_WEIGHT * out[g] + w_sot * sot_goals + XG_WEIGHT * xg_val) / (GOAL_WEIGHT + w_sot + XG_WEIGHT)
        no_xg = (GOAL_WEIGHT * out[g] + w_sot * sot_goals) / (GOAL_WEIGHT + w_sot)
        out[f"{side}_str"] = np.where(has_xg, with_xg, no_xg)
    return out


_CALIBRATION: dict | None = None


def _calibration() -> dict:
    global _CALIBRATION
    if _CALIBRATION is None:
        _CALIBRATION = calibration.load()
    return _CALIBRATION


@dataclass
class LeagueModel:
    league: str
    as_of: pd.Timestamp
    goals: ratings.TeamRatings
    corners: ratings.TeamRatings | None
    cards: ratings.TeamRatings | None
    corner_alpha: float
    card_alpha: float
    referee_factor: dict[str, float]
    history: pd.DataFrame = field(repr=False)

    @classmethod
    def fit(cls, matches: pd.DataFrame, league: str, as_of: pd.Timestamp) -> "LeagueModel":
        hist = matches[(matches["league"] == league) & (matches["date"] < as_of)]
        hist = hist[hist["season"] > hist["season"].max() - HISTORY_SEASONS]
        hist = _with_card_columns(hist)
        goals = ratings.fit(hist, as_of, xi=XI, ridge=RIDGE)
        target = _strength_target(hist)
        if target is not None:
            strength = ratings.fit(target, as_of, "h_str", "a_str", xi=XI, ridge=RIDGE, dixon_coles=False)
            strength.rho = goals.rho
            goals = strength

        corners = cards = None
        corner_alpha = card_alpha = 0.0
        if hist[["hc", "ac"]].notna().all(axis=1).sum() > 200:
            corners = ratings.fit(hist, as_of, "hc", "ac", xi=COUNT_XI, ridge=COUNT_RIDGE, dixon_coles=False)
            corner_alpha = _dispersion(corners, hist, "hc", "ac")
        if hist[["hcards", "acards"]].notna().all(axis=1).sum() > 200:
            cards = ratings.fit(hist, as_of, "hcards", "acards", xi=COUNT_XI, ridge=COUNT_RIDGE, dixon_coles=False)
            card_alpha = _dispersion(cards, hist, "hcards", "acards")

        referee_factor = {}
        ref = hist.dropna(subset=["referee", "hcards", "acards"])
        if not ref.empty:
            w = np.exp(-0.0019 * (as_of - ref["date"]).dt.days)
            total = ref["hcards"] + ref["acards"]
            league_avg = np.average(total, weights=w)
            g = pd.DataFrame({"ref": ref["referee"], "w": w, "wc": w * total}).groupby("ref").sum()
            shrunk = (g["wc"] + REFEREE_SHRINK * league_avg) / (g["w"] + REFEREE_SHRINK)
            referee_factor = (shrunk / league_avg).to_dict()

        return cls(league, as_of, goals, corners, cards, corner_alpha, card_alpha,
                   referee_factor, hist)

    def predict(
        self,
        home: str,
        away: str,
        referee: str | None = None,
        home_adj: float = 1.0,
        away_adj: float = 1.0,
        calibrated: bool = True,
    ) -> dict:
        """Market probabilities for one fixture.

        home_adj / away_adj multiply that team's expected goals. Use them for
        news the ratings cannot see yet: 0.85 for a missing star striker,
        0.90 for heavy rotation before a Champions League game, etc.
        """
        for team in (home, away):
            if not self.goals.has(team):
                raise KeyError(f"{team!r} has no {self.league} history")
        lam, mu = self.goals.expected(home, away)
        lam, mu = lam * home_adj, mu * away_adj
        m = ratings.score_matrix(lam, mu, self.goals.rho)
        probs = markets.goal_markets(m)
        out = {"xg_home": lam, "xg_away": mu, "scores": markets.top_scores(m), "probs": probs, "matrix": m}

        if self.corners and self.corners.has(home) and self.corners.has(away):
            c = sum(self.corners.expected(home, away))
            out["exp_corners"] = c
            probs.update(markets.count_markets("corners", c, self.corner_alpha, markets.CORNER_LINES))
        if self.cards and self.cards.has(home) and self.cards.has(away):
            c = sum(self.cards.expected(home, away))
            if referee and referee in self.referee_factor:
                c *= self.referee_factor[referee]
                out["referee_factor"] = self.referee_factor[referee]
            out["exp_cards"] = c
            probs.update(markets.count_markets("cards", c, self.card_alpha, markets.CARD_LINES))
        if calibrated:
            out["raw_probs"] = probs
            out["probs"] = calibration.apply(probs, _calibration())
        return out

    def context(self, home: str, away: str, n: int = 5) -> dict:
        """Recent form and head-to-head, for the human reading the report.

        Head-to-head is shown but not fed into the probabilities: past meetings
        are a handful of games, often with different players and managers, and
        the team ratings already capture current strength far better.
        """
        h = self.history
        def form(team):
            games = h[(h["home"] == team) | (h["away"] == team)].tail(n)
            res = []
            for _, g in games.iterrows():
                gf, ga = (g["hg"], g["ag"]) if g["home"] == team else (g["ag"], g["hg"])
                res.append("W" if gf > ga else "D" if gf == ga else "L")
            return "".join(res)
        h2h = h[((h["home"] == home) & (h["away"] == away)) | ((h["home"] == away) & (h["away"] == home))].tail(n)
        return {
            "home_form": form(home),
            "away_form": form(away),
            "h2h": [f"{g['date']:%Y-%m-%d} {g['home']} {int(g['hg'])}-{int(g['ag'])} {g['away']}"
                    for _, g in h2h.iterrows()],
        }
