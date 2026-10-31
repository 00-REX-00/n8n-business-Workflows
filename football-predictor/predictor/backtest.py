"""Walk-forward backtest: every week, refit on the past only, predict that week.

No information from a match leaks into its own prediction, so these numbers
are what the model would actually have produced at the time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import markets, value
from .model import LeagueModel

BINARY_MARKETS = [
    "over_1.5", "over_2.5", "over_3.5", "btts_yes",
    "home_over_0.5", "away_over_0.5", "1X", "X2",
    "corners_over_9.5", "cards_over_3.5", "cards_over_4.5",
]
CONFIDENCE_LEVELS = [0.70, 0.75, 0.80, 0.85, 0.90]


def run(matches: pd.DataFrame, leagues: list[str], seasons: list[int]) -> pd.DataFrame:
    """One row per (match, market) with the model probability and the result."""
    rows = []
    for league in leagues:
        target = matches[(matches["league"] == league) & matches["season"].isin(seasons)]
        week_start = target["date"].dt.to_period("W-MON").dt.start_time
        for start, week in target.groupby(week_start):
            lm = LeagueModel.fit(matches, league, start)
            for _, g in week.iterrows():
                try:
                    pred = lm.predict(g["home"], g["away"], g["referee"], calibrated=False)
                except KeyError:
                    continue
                probs = pred["probs"]
                for market, p in probs.items():
                    won = markets.outcome(market, g)
                    if won is None:
                        continue
                    rows.append({
                        "date": g["date"], "league": league, "season": g["season"],
                        "home": g["home"], "away": g["away"], "market": market,
                        "prob": p, "won": won, "odds": g.get(f"odds:{market}", np.nan),
                    })
        print(f"  {league}: done")
    return pd.DataFrame(rows)


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def scorecard(res: pd.DataFrame) -> pd.DataFrame:
    """Per market: how often the model's favoured side won, and log loss
    against a no-skill baseline that always predicts the league base rate."""
    out = []
    for market in BINARY_MARKETS:
        r = res[res["market"] == market]
        if r.empty:
            continue
        base = r.groupby("league")["won"].transform("mean").to_numpy()
        p, y = r["prob"].to_numpy(), r["won"].to_numpy()
        ll, ll_base = _log_loss(p, y), _log_loss(base, y)
        out.append({
            "market": market,
            "matches": len(r),
            "base_rate": y.mean(),
            "accuracy": ((p >= 0.5) == (y == 1)).mean(),
            "log_loss": ll,
            "baseline_ll": ll_base,
            "skill_%": 100 * (1 - ll / ll_base),
        })
    # 1X2 as a three-way pick
    three = res[res["market"].isin(["1", "X", "2"])].pivot_table(
        index=["date", "home", "away"], columns="market", values=["prob", "won"])
    if not three.empty:
        pick = three["prob"].idxmax(axis=1)
        hit = np.array([three["won"].loc[i, m] for i, m in pick.items()])
        out.insert(0, {"market": "1X2 (pick favourite)", "matches": len(three),
                       "base_rate": np.nan, "accuracy": hit.mean(),
                       "log_loss": np.nan, "baseline_ll": np.nan, "skill_%": np.nan})
    return pd.DataFrame(out).set_index("market")


def confidence_table(res: pd.DataFrame) -> pd.DataFrame:
    """Hit rate when only betting picks the model rates at >= a threshold.

    'breakeven_odds' is the lowest price at which those picks would have
    returned a profit. Compare it with the odds you actually get.
    """
    out = []
    for market in BINARY_MARKETS:
        r = res[res["market"] == market]
        under = market.replace("over", "under") if "over" in market else None
        for level in CONFIDENCE_LEVELS:
            picks = r[r["prob"] >= level]
            if under:  # the other side of the line counts as a pick too
                u = res[(res["market"] == under) & (res["prob"] >= level)]
                picks = pd.concat([picks, u])
            if len(picks) < 20:
                continue
            hit = picks["won"].mean()
            out.append({"market": market + (" / under" if under else ""), "min_prob": level,
                        "picks": len(picks), "avg_model_prob": picks["prob"].mean(),
                        "hit_rate": hit, "breakeven_odds": 1 / hit})
    return pd.DataFrame(out)


def calibration(res: pd.DataFrame, market: str, bins: int = 10) -> pd.DataFrame:
    r = res[res["market"] == market]
    cut = pd.cut(r["prob"], np.linspace(0, 1, bins + 1))
    return r.groupby(cut, observed=True).agg(
        matches=("won", "size"), predicted=("prob", "mean"), actual=("won", "mean"))


def betting(res: pd.DataFrame, min_edge: float = value.MIN_EDGE) -> pd.DataFrame | None:
    """Flat-stake results of betting every value pick at the historical odds."""
    r = res.dropna(subset=["odds"])
    if r.empty:
        return None
    r = r[(r["prob"] * r["odds"] - 1 >= min_edge) & (r["prob"] >= value.MIN_PROB)
          & (r["odds"] <= value.MAX_ODDS)]
    if r.empty:
        return None
    r = r.assign(profit=np.where(r["won"] == 1, r["odds"] - 1, -1.0))
    return r.groupby("market").agg(
        bets=("profit", "size"), hit_rate=("won", "mean"),
        avg_odds=("odds", "mean"), profit_units=("profit", "sum"),
        roi_pct=("profit", lambda s: 100 * s.mean()))
