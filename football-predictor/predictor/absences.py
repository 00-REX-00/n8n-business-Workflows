"""Turn missing players into an attack adjustment.

Each player's attacking involvement is their non-penalty xG plus xA (the xG
of chances they create) per 90 minutes. Their share of the team's involvement
per match is what the team loses when they're out, less what the replacement
provides. REPLACEMENT = 0.5 assumes the stand-in produces half of it; a rough
rule of thumb, since historical lineups aren't available to fit it.
Example: Haaland at ~28% of Man City's attack gives 1 - 0.28 * 0.5 = 0.86.
"""
from __future__ import annotations

import difflib

import pandas as pd

REPLACEMENT = 0.5
MIN_MULTIPLIER = 0.70
UNDERSTAT_LEAGUES = {"E0", "SP1", "I1", "D1", "F1"}
MIN_MINUTES = 270           # ignore players with less than 3 full games
SHRINK_MINUTES = 900        # per-90 rates move halfway to the team median after 10 full games


def attack_shares(players: pd.DataFrame, team: str) -> pd.DataFrame:
    """Player, minutes, involvement per 90 and share of the team's attack per match."""
    p = players[players["team"] == team].copy()
    if p.empty:
        return pd.DataFrame(columns=["player", "minutes", "per90", "share"])
    p["involvement"] = p["npxG"].fillna(0) + p["xA"].fillna(0)
    team_games = max(p["games"].max(), 1)
    team_per_match = p["involvement"].sum() / team_games
    p = p[p["minutes"] >= MIN_MINUTES]
    # small samples flatter: shrink each player's rate towards the squad median
    prior = (p["involvement"] / p["minutes"] * 90).median()
    p["per90"] = (p["involvement"] + SHRINK_MINUTES * prior / 90) / (p["minutes"] + SHRINK_MINUTES) * 90
    p["share"] = (p["per90"] / team_per_match).clip(upper=0.6) if team_per_match > 0 else 0.0
    return p.sort_values("share", ascending=False)[["player", "minutes", "per90", "share"]].reset_index(drop=True)


def multiplier(shares: pd.DataFrame, missing: list[str]) -> float:
    if not missing or shares.empty:
        return 1.0
    lost = shares.loc[shares["player"].isin(missing), "share"].sum()
    return max(MIN_MULTIPLIER, 1 - lost * (1 - REPLACEMENT))


def resolve_players(names: list[str], shares: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Match typed names to the squad list. Returns (matched, unknown)."""
    known = list(shares["player"])
    lower = {k.lower(): k for k in known}
    matched, unknown = [], []
    for name in names:
        name = name.strip()
        if not name:
            continue
        hit = lower.get(name.lower())
        if hit is None:
            # surname only or initial + surname, e.g. "Haaland", "E. Haaland"
            surname = name.lower().split()[-1]
            hits = [k for k in known if k.lower().split()[-1] == surname]
            hit = hits[0] if len(hits) == 1 else None
        if hit is None:
            close = difflib.get_close_matches(name.lower(), list(lower), n=1, cutoff=0.8)
            hit = lower[close[0]] if close else None
        (matched if hit else unknown).append(hit or name)
    return matched, unknown


def team_shares(league: str, team: str, season: int, fd_teams: list[str]) -> pd.DataFrame:
    """Shares from this season, or last season if the team has played < 5 games."""
    from .xg import load_players
    for s in (season, season - 1):
        players = load_players(league, s, fd_teams)
        team_rows = players[players["team"] == team]
        if not team_rows.empty and team_rows["games"].max() >= 5:
            return attack_shares(players, team)
    return attack_shares(pd.DataFrame(columns=["team"]), team)
