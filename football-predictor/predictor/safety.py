"""Play-safe filter applied to value bets before they are shown as picks.

1. No team news, no bet: if no news source answered for the fixture (and you
   haven't confirmed the news yourself), every pick for it is withheld.
2. A key player is doubtful (>= KEY_SHARE of the team's attack): withhold the
   fixture; the model can't know whether they play.
3. An edge above MAX_EDGE is treated as a sign the model is missing
   something (motivation, rotation, a late injury), not as a gift.
"""
from __future__ import annotations

import math

import pandas as pd

from . import absences, value
from .news import FixtureNews
from .value import Bet

MAX_EDGE = 0.15
KEY_SHARE = 0.10


def bettable_odds(market: str, prob: float) -> tuple[float, float] | None:
    """(lowest, highest) odds at which this market would be a pick, or None.

    Below the range there is no value; above it the edge exceeds MAX_EDGE and
    the pick is withheld. Lets you scan a bookmaker without typing every price.
    """
    if market.startswith(value.NO_SKILL_PREFIXES) or prob < value.MIN_PROB:
        return None
    # Start next to the exact bound and step with the same checks find_value and
    # screen use, so float rounding can't put a price in the range they'd reject.
    lo = math.floor((1 + value.MIN_EDGE) / prob * 100) / 100
    while value.edge(prob, lo) < value.MIN_EDGE:
        lo = round(lo + 0.01, 2)
    hi = math.ceil(min((1 + MAX_EDGE) / prob, value.MAX_ODDS) * 100) / 100
    while hi > value.MAX_ODDS or value.edge(prob, hi) > MAX_EDGE:
        hi = round(hi - 0.01, 2)
    return (lo, hi) if lo <= hi else None


def key_doubts(doubtful: list[str], shares: pd.DataFrame) -> list[str]:
    matched, _ = absences.resolve_players(doubtful, shares)
    if shares.empty:
        return []
    key = set(shares.loc[shares["share"] >= KEY_SHARE, "player"])
    return [p for p in matched if p in key]


def fixture_reason(news: FixtureNews | None, home_shares: pd.DataFrame, away_shares: pd.DataFrame,
                   manual_ok: bool = False) -> str | None:
    """Why every pick for this fixture is withheld (rules 1 and 2), or None."""
    if not manual_ok and (news is None or not news.found):
        return "No team news found" + (f" ({news.note})" if news and news.note else "")
    if news is not None and news.found:
        doubts = key_doubts(news.home.doubtful, home_shares) + key_doubts(news.away.doubtful, away_shares)
        if doubts:
            return f"Key player doubtful: {', '.join(doubts)}"
    return None


def screen(bets: list[Bet], news: FixtureNews | None, home_shares: pd.DataFrame,
           away_shares: pd.DataFrame, manual_ok: bool = False) -> tuple[list[Bet], list[tuple[Bet, str]]]:
    """Split bets into (kept, [(skipped bet, reason)])."""
    reason = fixture_reason(news, home_shares, away_shares, manual_ok)
    kept, skipped = [], []
    for b in bets:
        if reason:
            skipped.append((b, reason))
        elif b.edge > MAX_EDGE:
            skipped.append((b, f"Edge {b.edge:+.0%} is too large: the model is probably missing information"))
        else:
            kept.append(b)
    return kept, skipped
