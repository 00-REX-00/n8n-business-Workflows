"""Bet of the day: an accumulator near a target total odds with the best chance of winning.

Every leg must be rated at least `min_prob` likely by both SportyBet's own odds
(margin removed) and the model, pass the play-safe rules, and come from a
different match. Among those, `build` finds the combination whose total odds
land between the target and target x OVERSHOOT with the highest chance that
every leg wins.

That chance is estimated from SportyBet's odds, not the model: in the October
2026 backtest the bookmakers' odds predicted results better than the model on
every market, and blending the model in made them worse. Because each leg
carries the bookmaker's margin, a few well-priced legs beat many very short
ones at the same total odds, and by the bookmaker's own prices every
accumulator loses money on average.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import picks, safety, sportybet

LEG_MARKETS = picks.PICK_MARKETS
LEAGUE_TARGET = 3.0     # one league has ~3 matches a day: 10 odds is rarely reachable
OVERSHOOT = 1.35        # total odds may land up to 35% above the target
MAX_LEGS = 12
MIN_LEG_ODDS = 1.10     # shorter legs add almost nothing but another margin
STEP = 0.002            # resolution of the search, in log-odds


@dataclass
class Leg:
    result: dict            # the fixture's entry from predict.analyse
    market: str
    odds: float             # SportyBet's current price
    book_prob: float        # SportyBet's probability, margin removed
    model_prob: float

    @property
    def match(self) -> str:
        return f"{self.result['home']} v {self.result['away']}"


def candidates(results: list[dict], min_prob: float, news_checked: bool = False) -> list[Leg]:
    """Legs that pass every filter, from fixtures SportyBet lists.

    `news_checked` is the play-safe override: you confirm you've checked the
    team news for fixtures no news source covered."""
    legs = []
    for r in results:
        if r["fx"].get("odds_source") != "SportyBet" or not r["fx"].get("event_id"):
            continue
        if r["withheld"] and not (news_checked and r["withheld"].startswith("No team news")):
            continue
        book = sportybet.implied_probs(r["odds"])
        probs = r["pred"]["probs"]
        for market in LEG_MARKETS:
            o, q, p = r["odds"].get(market), book.get(market), probs.get(market)
            if o is None or q is None or p is None or o < MIN_LEG_ODDS:
                continue
            if min(p, q) < min_prob or p * o - 1 > safety.MAX_EDGE:  # rule 3: a huge edge means missing news
                continue
            legs.append(Leg(r, market, o, q, p))
    return legs


def build(legs: list[Leg], target: float, max_legs: int = MAX_LEGS) -> list[Leg]:
    """The legs (one per match) with total odds in [target, target x OVERSHOOT]
    that maximise the product of bookmaker probabilities. [] if none reach it."""
    groups: dict[str, list[Leg]] = {}
    for leg in legs:
        groups.setdefault(leg.match, []).append(leg)
    groups_list = list(groups.values())
    lo, hi = math.ceil(math.log(target) / STEP), int(math.log(target * OVERSHOOT) / STEP)
    dp = np.full((max_legs + 1, hi + 1), np.inf)
    dp[0, 0] = 0.0
    choices = []
    for group in groups_list:
        new = dp.copy()
        choice = np.full(dp.shape, -1, dtype=np.int16)
        for j, leg in enumerate(group):
            w, c = round(math.log(leg.odds) / STEP), -math.log(leg.book_prob)
            if w > hi:
                continue
            for k in range(max_legs):
                cand = dp[k, :hi + 1 - w] + c
                better = cand < new[k + 1, w:]
                new[k + 1, w:][better] = cand[better]
                choice[k + 1, w:][better] = j
        dp = new
        choices.append(choice)
    window = dp[1:, lo:]
    if not np.isfinite(window).any():
        return []
    k, w = np.unravel_index(np.argmin(window), window.shape)
    k, w = int(k) + 1, int(w) + lo
    chosen = []
    for group, choice in zip(reversed(groups_list), reversed(choices)):
        j = int(choice[k, w])
        if j >= 0:
            leg = group[j]
            chosen.append(leg)
            k, w = k - 1, w - round(math.log(leg.odds) / STEP)
    return sorted(chosen, key=lambda leg: leg.result["fx"]["kickoff"])


def alternatives(legs: list[Leg], target: float, n: int = 3) -> list[list[Leg]]:
    """The best ticket, then the best from the matches left, up to n: no two share a match."""
    tickets, pool = [], list(legs)
    while len(tickets) < n:
        ticket = build(pool, target)
        if not ticket:
            break
        tickets.append(ticket)
        used = {leg.match for leg in ticket}
        pool = [leg for leg in pool if leg.match not in used]
    return tickets


def by_league(legs: list[Leg], target: float = LEAGUE_TARGET) -> dict[str, list[Leg]]:
    """The best ticket within each league, for leagues that can reach the target."""
    groups: dict[str, list[Leg]] = {}
    for leg in legs:
        groups.setdefault(leg.result["league"], []).append(leg)
    tickets = {league: build(group, target) for league, group in groups.items()}
    return {league: ticket for league, ticket in tickets.items() if ticket}


def summary(legs: list[Leg]) -> dict:
    odds = math.prod(leg.odds for leg in legs)
    book = math.prod(leg.book_prob for leg in legs)
    model = math.prod(leg.model_prob for leg in legs)
    return {"legs": len(legs), "odds": odds, "chance": book, "model_chance": model,
            "expected_return": book * odds}   # per 1 staked, by SportyBet's own prices
