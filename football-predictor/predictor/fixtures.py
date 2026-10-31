"""Upcoming fixtures, fetched online so you don't have to type them.

Sources, merged:
  1. football-data.co.uk fixtures.csv: the next few days in every league it
     covers, with referees and bookmaker odds, under the same team names as the
     results files. Updated a few times a week.
  2. Understat's season schedule (top 5 leagues): every remaining match, which
     covers the days football-data hasn't posted yet.
Both give kick-off times in UK time; `upcoming` converts them to this
computer's time zone. The football-data file is cached for FIXTURES_TTL_HOURS.
"""
from __future__ import annotations

import io
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import teams
from .data import DEFAULT_CACHE, _decode, _download, _parse_dates, current_season

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
FIXTURES_TTL_HOURS = 3
SOURCE_TZ = "Europe/London"
COLUMNS = ["league", "kickoff", "home", "away", "referee", "source"]
# fixtures.csv odds -> our markets: market average first, then Bet365
ODDS_COLUMNS = {
    "odds:1": ["AvgH", "B365H"], "odds:X": ["AvgD", "B365D"], "odds:2": ["AvgA", "B365A"],
    "odds:over_2.5": ["Avg>2.5", "B365>2.5"], "odds:under_2.5": ["Avg<2.5", "B365<2.5"],
}


def parse_football_data(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.dropna(subset=["Div", "HomeTeam", "AwayTeam"])
    times = pd.to_timedelta(df["Time"].astype(str).str.strip() + ":00", errors="coerce") \
        if "Time" in df else pd.Series(pd.NaT, index=df.index)
    out = pd.DataFrame({
        "league": df["Div"].astype(str).str.strip(),
        "kickoff": _parse_dates(df["Date"]) + times.fillna(pd.Timedelta(hours=15)),
        "home": df["HomeTeam"].astype(str).str.strip(),
        "away": df["AwayTeam"].astype(str).str.strip(),
        "referee": df["Referee"].astype(str).str.strip() if "Referee" in df else None,
        "source": "football-data.co.uk",
    })
    out.loc[out["referee"].isin(["nan", "None", ""]), "referee"] = None
    for dst, candidates in ODDS_COLUMNS.items():
        col = pd.Series(float("nan"), index=df.index)
        for src in candidates:
            if src in df:
                col = col.fillna(pd.to_numeric(df[src], errors="coerce"))
        out[dst] = col
    return out.dropna(subset=["kickoff"])


def parse_understat(dates: list[dict], league: str, known: list[str]) -> pd.DataFrame:
    """Unplayed matches from an Understat schedule, under football-data names."""
    rows = []
    for d in dates:
        if d.get("isResult"):
            continue
        try:
            home, away = teams.resolve(d["h"]["title"], known), teams.resolve(d["a"]["title"], known)
        except KeyError:
            continue
        rows.append({"league": league, "kickoff": pd.Timestamp(d["datetime"]), "home": home,
                     "away": away, "referee": None, "source": "Understat"})
    return pd.DataFrame(rows, columns=COLUMNS)


def _football_data(cache_dir: Path, refresh: bool) -> pd.DataFrame:
    cache = cache_dir / "fixtures_fd.csv"
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < FIXTURES_TTL_HOURS * 3600
    if not fresh or refresh:
        try:
            raw = pd.read_csv(io.StringIO(_decode(_download(FIXTURES_URL))), on_bad_lines="skip")
            cache.parent.mkdir(parents=True, exist_ok=True)
            raw.to_csv(cache, index=False)
        except Exception:
            if not cache.exists():
                raise
    return parse_football_data(pd.read_csv(cache))


def select(fx: pd.DataFrame, now: pd.Timestamp, days: int, tz=None) -> pd.DataFrame:
    """Kick-offs (converted from UK time to `tz`, default this computer's) after
    `now` and before the end of day `days` (1 = today only). Where both sources
    list a match, the first row wins, so pass football-data rows first.
    """
    tz = tz or datetime.now().astimezone().tzinfo
    fx = fx.copy()
    fx["kickoff"] = (pd.to_datetime(fx["kickoff"])
                     .dt.tz_localize(SOURCE_TZ, ambiguous="NaT", nonexistent="shift_forward")
                     .dt.tz_convert(tz).dt.tz_localize(None))
    end = now.normalize() + pd.Timedelta(days=days)
    fx = fx[(fx["kickoff"] > now) & (fx["kickoff"] < end)]
    fx = fx.drop_duplicates(["league", "home", "away"], keep="first")
    fx["date"] = fx["kickoff"].dt.normalize()
    return fx.sort_values(["kickoff", "league", "home"]).reset_index(drop=True)


def known_teams(matches: pd.DataFrame) -> dict[str, list[str]]:
    """Each league's teams in its latest season of results."""
    out = {}
    for league, g in matches.groupby("league"):
        latest = g[g["season"] == g["season"].max()]
        out[league] = sorted(set(latest["home"]) | set(latest["away"]))
    return out


def upcoming(leagues: list[str], days: int, known: dict[str, list[str]],
             now: pd.Timestamp | None = None, cache_dir: Path = DEFAULT_CACHE,
             refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """(fixtures in the next `days` days, notes about sources that failed)."""
    from .xg import UNDERSTAT_LEAGUES, _understat_league_json

    now = now or pd.Timestamp.now()
    frames, notes = [], []
    try:
        fd = _football_data(cache_dir, refresh)
        frames.append(fd[fd["league"].isin(leagues)])
    except Exception as exc:
        notes.append(f"football-data.co.uk fixtures unavailable ({exc})")
    for league in leagues:
        if league not in UNDERSTAT_LEAGUES or league not in known:
            continue
        try:
            dates = _understat_league_json(league, current_season(now.date()))["dates"]
            frames.append(parse_understat(dates, league, known[league]))
        except Exception as exc:
            notes.append(f"Understat schedule for {league} unavailable ({exc})")
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS + ["date"]), notes
    return select(pd.concat(frames, ignore_index=True), now, days), notes
