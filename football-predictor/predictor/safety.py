"""Play-safe filter applied to value bets before they are shown as picks.

1. No team news, no bet: if no news source answered for the fixture (and you
   haven't confirmed the news yourself), every pick for it is withheld.
2. A key player is doubtful (>= KEY_SHARE of the team's attack): withhold the
   fixture; the model can't know whether they play.
3. An edge above MAX_EDGE is treated as a sign the model is missing
   something (motivation, rotation, a late injury), not as a gift.
"""
from __future__ import annotations

import pandas as pd

from . import absences
from .news import FixtureNews
from .value import Bet

MAX_EDGE = 0.15
KEY_SHARE = 0.10


def key_doubts(doubtful: list[str], shares: pd.DataFrame) -> list[str]:
    matched, _ = absences.resolve_players(doubtful, shares)
    if shares.empty:
        return []
    key = set(shares.loc[shares["share"] >= KEY_SHARE, "player"])
    return [p for p in matched if p in key]


def screen(bets: list[Bet], news: FixtureNews | None, home_shares: pd.DataFrame,
           away_shares: pd.DataFrame, manual_ok: bool = False) -> tuple[list[Bet], list[tuple[Bet, str]]]:
    """Split bets into (kept, [(skipped bet, reason)])."""
    fixture_reason = None
    if not manual_ok and (news is None or not news.found):
        fixture_reason = "No team news found" + (f" ({news.note})" if news and news.note else "")
    elif news is not None and news.found:
        doubts = key_doubts(news.home.doubtful, home_shares) + key_doubts(news.away.doubtful, away_shares)
        if doubts:
            fixture_reason = f"Key player doubtful: {', '.join(doubts)}"
    kept, skipped = [], []
    for b in bets:
        if fixture_reason:
            skipped.append((b, fixture_reason))
        elif b.edge > MAX_EDGE:
            skipped.append((b, f"Edge {b.edge:+.0%} is too large: the model is probably missing information"))
        else:
            kept.append(b)
    return kept, skipped
