"""Compare model probabilities with bookmaker odds and size stakes."""
from __future__ import annotations

from dataclasses import dataclass

# Defaults are deliberately conservative. Raise them only after the model
# has shown a real edge over hundreds of tracked bets.
MIN_EDGE = 0.05          # model must expect >= 5% return per unit staked
MIN_PROB = 0.25          # ignore long shots: model error dominates there
MAX_ODDS = 4.0
KELLY_FRACTION = 0.25    # quarter Kelly
MAX_STAKE = 0.02         # never more than 2% of bankroll on one bet
# Markets where the backtest showed no skill over the league average. The
# model still prints their probabilities, but never calls them value.
NO_SKILL_PREFIXES = ("corners_", "btts_")


@dataclass
class Bet:
    market: str
    prob: float
    odds: float
    edge: float
    stake_pct: float

    @property
    def fair_odds(self) -> float:
        return 1 / self.prob


def edge(prob: float, odds: float) -> float:
    """Expected return per unit staked."""
    return prob * odds - 1


def kelly_stake(prob: float, odds: float) -> float:
    """Fraction of bankroll to stake (fractional Kelly, capped)."""
    if odds <= 1:
        return 0.0
    full = (prob * odds - 1) / (odds - 1)
    return max(0.0, min(full * KELLY_FRACTION, MAX_STAKE))


def find_value(probs: dict[str, float], odds: dict[str, float],
               min_edge: float = MIN_EDGE) -> list[Bet]:
    bets = []
    for market, price in odds.items():
        p = probs.get(market)
        if market.startswith(NO_SKILL_PREFIXES):
            continue
        if p is None or not price or price != price or price <= 1:
            continue
        e = edge(p, price)
        if e >= min_edge and p >= MIN_PROB and price <= MAX_ODDS:
            bets.append(Bet(market, p, price, e, kelly_stake(p, price)))
    return sorted(bets, key=lambda b: b.edge, reverse=True)


def market_probs(odds: dict[str, float]) -> dict[str, float]:
    """The bookmaker's own probabilities with its margin removed.

    Only possible where all outcomes of a market have odds: 1/X/2,
    over/under the same line, BTTS yes/no.
    """
    groups = [["1", "X", "2"], ["btts_yes", "btts_no"]]
    for key in odds:
        if "over_" in key:
            groups.append([key, key.replace("over_", "under_")])
    out = {}
    for group in groups:
        prices = [odds.get(k) for k in group]
        if all(p and p > 1 for p in prices):
            implied = [1 / p for p in prices]
            total = sum(implied)
            out.update({k: i / total for k, i in zip(group, implied)})
            out[f"margin:{group[0]}"] = total - 1
    return out


def accumulator(legs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """(win probability, combined odds, edge) for independent legs of (prob, odds).

    Every leg carries the bookmaker's margin, so an accumulator multiplies
    margins together. Only combine legs that each have positive edge.
    """
    p = o = 1.0
    for prob, odds in legs:
        p *= prob
        o *= odds
    return p, o, edge(p, o)
