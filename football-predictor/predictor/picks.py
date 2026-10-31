"""The model's best picks for a match: its most likely outcomes that still pay.

Candidates are the markets where the walk-forward backtest showed skill
(README, "What the backtest says"): match result, double chance, team to score
and total goals. BTTS and corners have no skill, so they're never picks.
Outcomes above MAX_PICK_PROB are skipped: bookmakers price those around
1.05-1.20, so even a winning pick barely pays.

A pick is the model's opinion, not yet a bet. It is a bet only at odds inside
its range (safety.bettable_odds); below that it can win most of the time and
still lose money. The play-safe rules apply: no team news, or a key player
doubtful, withholds a fixture's picks.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import safety

PICK_MARKETS = ("1", "2", "1X", "X2", "home_over_0.5", "away_over_0.5",
                "over_1.5", "over_2.5", "under_2.5", "under_3.5")
MAX_PICK_PROB = 0.80


@dataclass
class Pick:
    market: str
    prob: float
    odds_range: tuple[float, float]   # bet only at odds in this range


def best_picks(probs: dict[str, float], n: int = 3) -> list[Pick]:
    """Up to n picks, most likely first."""
    picks = []
    for market in PICK_MARKETS:
        p = probs.get(market)
        if p is None or p > MAX_PICK_PROB:
            continue
        window = safety.bettable_odds(market, p)
        if window:
            picks.append(Pick(market, p, window))
    return sorted(picks, key=lambda pk: pk.prob, reverse=True)[:n]
