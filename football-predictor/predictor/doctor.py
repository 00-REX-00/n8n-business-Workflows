"""Check a SportyBet booking code: what each leg costs, what's wrong with it,
and a better ticket at the same total odds.

For any ticket, the chance it wins is the product of the legs' probabilities
and its total odds the product of their odds, so

    chance = expected return / total odds,  expected return = product of (odds x probability).

SportyBet publishes its own probability for every outcome, so odds x
probability is its own expected return on that leg, and 1 minus it is the
margin it keeps (about 2% on a big match result, 4-5% on many goal lines). At
a given total odds the only ways to raise the chance are to pay less margin
or to find legs SportyBet has priced wrongly. `improve` does the first: it
keeps the legs you choose and rebuilds the rest for the highest chance at your
total odds, from legs that also pass the model and play-safe checks
(acca.candidates). It can't make a ticket likely, only less unlikely.
"""
from __future__ import annotations

import math

import pandas as pd

from . import acca

EXPENSIVE_MARGIN = 0.04   # a leg keeping >= 4% (and more than the slip's median) is flagged
DISAGREE = 0.10           # model at least 10 points below SportyBet's probability


def leg_prob(leg: dict) -> float:
    """SportyBet's probability, or 1/odds (no margin) on the rare leg without one."""
    return leg["prob"] if leg["prob"] == leg["prob"] else 1 / leg["odds"]


def margin(leg: dict) -> float:
    return 1 - leg["odds"] * leg_prob(leg)


def analyse(legs: list[dict], results_by_event: dict[str, dict], news_checked: bool = False) -> pd.DataFrame:
    """One row per leg: SportyBet's chance, its margin, the model's chance where
    the app analyses the match, and the problems that make it worth replacing."""
    margins = [margin(leg) for leg in legs]
    median = float(pd.Series(margins).median()) if margins else 0.0
    per_event = pd.Series([leg["event_id"] for leg in legs]).value_counts()
    rows = []
    for leg, m in zip(legs, margins):
        r = results_by_event.get(leg["event_id"])
        model = r["pred"]["probs"].get(leg["market"]) if r and leg["market"] else None
        problems, notes = [], []
        if leg["started"]:
            problems.append(f"Already started: {leg['state']}")
        elif not leg["active"]:
            problems.append("Suspended or no longer offered")
        if per_event[leg["event_id"]] > 1:
            problems.append("Same match twice")
        if m >= EXPENSIVE_MARGIN and m > median:
            problems.append(f"Expensive: SportyBet keeps {m:.1%}")
        if model is not None and model < leg_prob(leg) - DISAGREE:
            problems.append(f"Model disagrees ({model:.0%})")
        if r and r["withheld"] and not (news_checked and r["withheld"].startswith("No team news")):
            problems.append(r["withheld"].split(" (")[0])
        if m < 0:
            notes.append(f"Value by SportyBet's own numbers ({-m:+.1%})")
        if r is None:
            notes.append("Model doesn't cover this match" if leg["league"] is None or leg["home"] is None
                         else "Not in the analysed fixtures")
        elif leg["market"] is None:
            notes.append("Model doesn't cover this market")
        rows.append({"problems": problems, "notes": notes, "margin": m, "model_prob": model,
                     "book_prob": leg_prob(leg), "news": (r["news"].source if r and r["news"].found else None)})
    return pd.DataFrame(rows, columns=["problems", "notes", "margin", "model_prob", "book_prob", "news"])


def default_keep(analysis: pd.DataFrame) -> list[bool]:
    """Keep every leg without a problem."""
    return [not p for p in analysis["problems"]]


def summary(odds: list[float], probs: list[float]) -> dict:
    """Same meaning as acca.summary: total odds, chance, expected return per 1 staked."""
    total, chance = math.prod(odds), math.prod(probs)
    return {"legs": len(odds), "odds": total, "chance": chance, "expected_return": chance * total}


def improve(legs: list[dict], keep: list[bool], pool: list[acca.Leg], target: float,
            max_legs: int = acca.MEGA_MAX_LEGS) -> tuple[list[dict], list[acca.Leg]] | None:
    """(kept legs, new legs): the kept legs plus the fill with the highest
    chance whose total odds reach `target` (up to OVERSHOOT above it). New legs
    never reuse a kept leg's match. None if no fill reaches the target."""
    kept = [leg for leg, k in zip(legs, keep) if k]
    kept_odds = math.prod(leg["odds"] for leg in kept)
    if kept_odds >= target:
        return kept, []
    if len(kept) >= max_legs:
        return None
    used = {leg["event_id"] for leg in kept}
    free = [leg for leg in pool if leg.result["fx"].get("event_id") not in used]
    fill = acca.build(free, target / kept_odds, max_legs - len(kept), strict=True)
    return (kept, fill) if fill else None
