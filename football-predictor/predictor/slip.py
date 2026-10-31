"""Bet slips: turn picks into a list you can enter on SportyBet and book.

SportyBet has no public API, so the app can't create a booking code by
itself. Instead it gives the selections under SportyBet's own market names;
add them on sportybet.com/ng, press "Book Bet", and SportyBet returns the
code.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import markets, value

MAX_ACCA_LEGS = 3
ACCA_MAX_STAKE = 0.01   # accumulators: at most 1% of bankroll


def sportybet_name(market: str) -> tuple[str, str]:
    """(SportyBet market, selection) for one of our market keys."""
    fixed = {
        "1": ("1X2", "Home"), "X": ("1X2", "Draw"), "2": ("1X2", "Away"),
        "1X": ("Double Chance", "Home or Draw"), "X2": ("Double Chance", "Draw or Away"),
        "12": ("Double Chance", "Home or Away"),
        "dnb_1": ("Draw No Bet", "Home"), "dnb_2": ("Draw No Bet", "Away"),
        "btts_yes": ("GG/NG", "GG"), "btts_no": ("GG/NG", "NG"),
    }
    if market in fixed:
        return fixed[market]
    side, line = market.rsplit("_", 1)
    names = {
        "over": ("Over/Under", "Over {}"), "under": ("Over/Under", "Under {}"),
        "home_over": ("Home Over/Under", "Over {}"), "away_over": ("Away Over/Under", "Over {}"),
        "corners_over": ("Corners - Over/Under", "Over {}"), "corners_under": ("Corners - Over/Under", "Under {}"),
        "cards_over": ("Bookings - Over/Under", "Over {}"), "cards_under": ("Bookings - Over/Under", "Under {}"),
    }
    m, sel = names.get(side, (markets.label(market), ""))
    return m, sel.format(line)


@dataclass
class Leg:
    date: str
    league: str
    home: str
    away: str
    market: str
    odds: float
    prob: float

    @property
    def edge(self) -> float:
        return value.edge(self.prob, self.odds)

    def line(self) -> str:
        m, sel = sportybet_name(self.market)
        return f"{self.date}  {self.home} vs {self.away}  |  {m}: {sel}  @ {self.odds:.2f}"


def summary(legs: list[Leg], bankroll: float) -> dict:
    """Combined odds, win chance, edge and stakes for singles and an accumulator."""
    p, o, e = value.accumulator([(l.prob, l.odds) for l in legs]) if legs else (0.0, 0.0, 0.0)
    acca_stake = min(value.kelly_stake(p, o), ACCA_MAX_STAKE) if legs else 0.0
    warnings = []
    if len(legs) > MAX_ACCA_LEGS:
        warnings.append(f"More than {MAX_ACCA_LEGS} legs: the win chance falls fast and the "
                        "bookmaker's margin multiplies. Prefer singles or split into smaller slips.")
    if len({(l.home, l.away) for l in legs}) < len(legs):
        warnings.append("Two legs from the same match are linked (not independent); "
                        "SportyBet may also refuse to combine them.")
    big = [f"{l.home} v {l.away}" for l in legs if l.edge > 0.15]
    if big:
        warnings.append("Very large edge on " + ", ".join(big) + ": usually the model is missing news "
                        "(injuries, rotation, motivation). Check before betting.")
    if any(l.edge < 0 for l in legs):
        warnings.append("At least one leg has no value at its odds; it drags the whole slip down.")
    return {
        "legs": len(legs),
        "acca_odds": o, "acca_prob": p, "acca_edge": e,
        "acca_stake": acca_stake * bankroll,
        "singles_stake": sum(value.kelly_stake(l.prob, l.odds) for l in legs) * bankroll,
        "singles_expected_profit": sum(value.kelly_stake(l.prob, l.odds) * l.edge for l in legs) * bankroll,
        "warnings": warnings,
    }


def to_text(legs: list[Leg]) -> str:
    return "\n".join(f"{i}. {leg.line()}" for i, leg in enumerate(legs, 1))
