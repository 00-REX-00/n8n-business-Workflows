"""Head-to-head and recent form, for the person reading (not used in the probabilities).

The model only needs three seasons of one league, which misses meetings from
before a promotion or relegation: a promoted side showed just its two meetings
since coming up. So these look back H2H_SEASONS seasons across the league and
the divisions next to it.

Source: football-data.co.uk league matches, plus this season's results it
hasn't added yet (from Understat). Cup and European matches aren't included.
"""
from __future__ import annotations

import pandas as pd

from . import data

H2H_SEASONS = 10
RELATED_DIVISIONS = {
    "E0": ["E1"], "E1": ["E0", "E2"], "SP1": ["SP2"], "SP2": ["SP1"], "I1": ["I2"], "I2": ["I1"],
    "D1": ["D2"], "D2": ["D1"], "F1": ["F2"], "F2": ["F1"], "SC0": ["SC1"],
}
DIVISION_NAMES = {**data.LEAGUES, "E2": "League One", "SC1": "Scottish Championship"}
COLUMNS = ["league", "season", "date", "home", "away", "hg", "ag"]


def archive(league: str, cache_dir=data.DEFAULT_CACHE) -> pd.DataFrame:
    """League matches of the last H2H_SEASONS seasons in `league` and its neighbours."""
    now = data.current_season()
    return data.load_matches([league] + RELATED_DIVISIONS.get(league, []), list(range(now - H2H_SEASONS, now + 1)),
                             cache_dir, refresh_current=False, with_xg=False)[COLUMNS]


def combine(past: pd.DataFrame, recent: pd.DataFrame) -> pd.DataFrame:
    """The archive plus the latest matches (which may include Understat fill-ins)."""
    out = pd.concat([past[COLUMNS], recent[COLUMNS]], ignore_index=True)
    return out.drop_duplicates(["date", "home", "away"]).sort_values("date").reset_index(drop=True)


def form(matches: pd.DataFrame, team: str, before: pd.Timestamp, n: int = 5) -> pd.DataFrame:
    """The team's last n matches before `before`, newest first."""
    g = matches[((matches["home"] == team) | (matches["away"] == team)) & (matches["date"] < before)]
    rows = []
    for r in g.tail(n).iloc[::-1].itertuples():
        at_home = r.home == team
        gf, ga = (r.hg, r.ag) if at_home else (r.ag, r.hg)
        rows.append({"Date": r.date.date(), "Competition": DIVISION_NAMES.get(r.league, r.league),
                     "": "H" if at_home else "A", "Opponent": r.away if at_home else r.home,
                     "Score": f"{gf:.0f}-{ga:.0f}", "Result": "W" if gf > ga else "D" if gf == ga else "L"})
    return pd.DataFrame(rows, columns=["Date", "Competition", "", "Opponent", "Score", "Result"])


def head_to_head(matches: pd.DataFrame, a: str, b: str, before: pd.Timestamp, n: int = 10) -> pd.DataFrame:
    """Meetings of a and b before `before`, newest first, scores as played (home first)."""
    g = matches[(((matches["home"] == a) & (matches["away"] == b)) | ((matches["home"] == b) & (matches["away"] == a)))
                & (matches["date"] < before)]
    rows = [{"Date": r.date.date(), "Competition": DIVISION_NAMES.get(r.league, r.league),
             "Match": f"{r.home} {r.hg:.0f}-{r.ag:.0f} {r.away}",
             "Winner": r.home if r.hg > r.ag else r.away if r.ag > r.hg else "Draw"}
            for r in g.tail(n).iloc[::-1].itertuples()]
    return pd.DataFrame(rows, columns=["Date", "Competition", "Match", "Winner"])


def record(h2h: pd.DataFrame, a: str, b: str) -> str:
    wins = h2h["Winner"].value_counts()
    return f"{a} {wins.get(a, 0)} wins · {wins.get('Draw', 0)} draws · {b} {wins.get(b, 0)} wins"
