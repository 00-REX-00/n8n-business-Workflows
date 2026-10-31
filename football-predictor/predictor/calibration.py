"""Correct systematic over/under-confidence learned from the backtest.

For each market, Platt scaling maps the raw probability p to
sigmoid(a * logit(p) + b). a > 1 means the raw model was too timid (its
favourites win more often than it says), a < 1 means it was overconfident.
The parameters are fitted on walk-forward backtest predictions, so they only
ever learn from matches the model had not seen.

Derived markets are rebuilt from calibrated base markets so everything stays
consistent: under = 1 - over, 1X = 1 + X, and so on.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "models" / "calibration.json"

# Base markets we calibrate; everything else is derived from these.
BASE_MARKETS = ["1", "X", "2", "btts_yes",
                "home_over_0.5", "home_over_1.5", "away_over_0.5", "away_over_1.5"]
LINE_PREFIXES = ["over_", "corners_over_", "cards_over_"]


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _platt(p, a, b):
    return 1 / (1 + np.exp(-(a * _logit(p) + b)))


def fit(results: pd.DataFrame, min_rows: int = 500) -> dict[str, list[float]]:
    """Fit (a, b) per market from backtest rows (columns: market, prob, won)."""
    params = {}
    for market, r in results.groupby("market"):
        if not (market in BASE_MARKETS or any(market.startswith(p) for p in LINE_PREFIXES)):
            continue
        if len(r) < min_rows:
            continue
        p, y = r["prob"].to_numpy(), r["won"].to_numpy()

        def loss(ab):
            q = np.clip(_platt(p, *ab), 1e-6, 1 - 1e-6)
            return -(y * np.log(q) + (1 - y) * np.log(1 - q)).mean()

        a, b = minimize(loss, [1.0, 0.0], method="Nelder-Mead").x
        params[market] = [round(float(a), 4), round(float(b), 4)]
    return params


def save(params: dict, path: Path = DEFAULT_PATH, note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"note": note, "params": params}, indent=2))


def load(path: Path = DEFAULT_PATH) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())["params"]


def apply(probs: dict[str, float], params: dict[str, list[float]]) -> dict[str, float]:
    if not params:
        return probs
    out = dict(probs)
    for market, (a, b) in params.items():
        if market in out:
            out[market] = float(_platt(out[market], a, b))

    # 1X2 must sum to one; rebuild everything that depends on it
    s = out["1"] + out["X"] + out["2"]
    p1, px, p2 = out["1"] / s, out["X"] / s, out["2"] / s
    out.update({"1": p1, "X": px, "2": p2, "1X": p1 + px, "X2": px + p2, "12": p1 + p2,
                "dnb_1": p1 / (p1 + p2), "dnb_2": p2 / (p1 + p2)})
    out["btts_no"] = 1 - out["btts_yes"]
    out["home_clean_sheet"] = 1 - out["away_over_0.5"]
    out["away_clean_sheet"] = 1 - out["home_over_0.5"]
    for key in list(out):
        for prefix in LINE_PREFIXES:
            if key.startswith(prefix):
                out[key.replace("over_", "under_")] = 1 - out[key]

    # calibrating each line separately can, rarely, break the ordering
    # (P(over 1.5) must be >= P(over 2.5)); enforce it
    for prefix in LINE_PREFIXES:
        lines = sorted((float(k[len(prefix):]), k) for k in out if k.startswith(prefix))
        for (_, lower), (_, higher) in zip(lines, lines[1:]):
            if out[higher] > out[lower]:
                out[higher] = out[lower]
                out[higher.replace("over_", "under_")] = 1 - out[lower]
    return out
