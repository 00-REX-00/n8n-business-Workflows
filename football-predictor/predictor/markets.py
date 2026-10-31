"""Turn model outputs into betting-market probabilities.

Market keys are used everywhere (fixture odds columns, reports, backtests):
  1, X, 2, 1X, X2, 12, dnb_1, dnb_2
  over_0.5 ... over_4.5, under_0.5 ... under_4.5     (total goals)
  home_over_0.5, home_over_1.5, away_over_0.5, away_over_1.5
  btts_yes, btts_no, home_clean_sheet, away_clean_sheet
  corners_over_7.5 ... corners_under_12.5
  cards_over_2.5 ... cards_under_6.5
"""
from __future__ import annotations

import numpy as np
from scipy.stats import nbinom, poisson

GOAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]
CORNER_LINES = [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
CARD_LINES = [2.5, 3.5, 4.5, 5.5, 6.5]


def goal_markets(m: np.ndarray) -> dict[str, float]:
    n = m.shape[0]
    i, j = np.indices(m.shape)
    total = i + j
    p1, px, p2 = m[i > j].sum(), m[i == j].sum(), m[i < j].sum()
    out = {
        "1": p1, "X": px, "2": p2,
        "1X": p1 + px, "X2": px + p2, "12": p1 + p2,
        "dnb_1": p1 / (p1 + p2), "dnb_2": p2 / (p1 + p2),
        "btts_yes": m[1:, 1:].sum(),
        "home_clean_sheet": m[:, 0].sum(),
        "away_clean_sheet": m[0, :].sum(),
    }
    out["btts_no"] = 1 - out["btts_yes"]
    for line in GOAL_LINES:
        over = m[total > line].sum()
        out[f"over_{line}"] = over
        out[f"under_{line}"] = 1 - over
    home_goals = m.sum(axis=1)
    away_goals = m.sum(axis=0)
    for line in (0.5, 1.5):
        out[f"home_over_{line}"] = home_goals[np.arange(n) > line].sum()
        out[f"away_over_{line}"] = away_goals[np.arange(n) > line].sum()
    return {k: float(v) for k, v in out.items()}


def top_scores(m: np.ndarray, k: int = 3) -> list[tuple[str, float]]:
    flat = np.argsort(m, axis=None)[::-1][:k]
    return [(f"{a}-{b}", float(m[a, b])) for a, b in zip(*np.unravel_index(flat, m.shape))]


def count_over(mean: float, alpha: float, line: float) -> float:
    """P(count > line) for a negative binomial with variance mean + alpha*mean^2."""
    k = int(np.floor(line))
    if alpha < 1e-3:
        return float(poisson.sf(k, mean))
    r = 1 / alpha
    return float(nbinom.sf(k, r, r / (r + mean)))


def count_markets(prefix: str, mean: float, alpha: float, lines: list[float]) -> dict[str, float]:
    out = {}
    for line in lines:
        over = count_over(mean, alpha, line)
        out[f"{prefix}_over_{line}"] = over
        out[f"{prefix}_under_{line}"] = 1 - over
    return out


def outcome(market: str, row) -> float | None:
    """1.0 if `market` won for a finished match row, 0.0 if lost, None if unknown/void."""
    hg, ag = row["hg"], row["ag"]
    if market in ("1", "X", "2", "1X", "X2", "12"):
        res = "1" if hg > ag else "X" if hg == ag else "2"
        return float(res in market)
    if market.startswith("dnb_"):
        if hg == ag:
            return None
        return float((hg > ag) == (market == "dnb_1"))
    if market == "btts_yes":
        return float(hg > 0 and ag > 0)
    if market == "btts_no":
        return float(not (hg > 0 and ag > 0))
    if market == "home_clean_sheet":
        return float(ag == 0)
    if market == "away_clean_sheet":
        return float(hg == 0)
    side, line = market.rsplit("_", 1)
    line = float(line)
    if side in ("over", "under"):
        value = hg + ag
    elif side in ("home_over", "away_over"):
        value = hg if side == "home_over" else ag
    elif side.startswith("corners"):
        value = row["hc"] + row["ac"]
    elif side.startswith("cards"):
        value = row["hy"] + row["ay"] + row["hr"] + row["ar"]
    else:
        raise ValueError(f"unknown market {market}")
    if value != value:  # NaN
        return None
    return float(value < line) if side.endswith("under") else float(value > line)
