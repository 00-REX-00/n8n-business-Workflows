"""Save SportyBet's current odds, and football-data.co.uk's market odds for the
same fixtures, so SportyBet's prices can be backtested later.

There is no record of SportyBet's past prices anywhere, so nothing about
SportyBet itself can be tested until we collect our own. Each run appends one
row per upcoming event to a monthly CSV in data/odds_log/. Run it a few times
a day (deploy/odds-snapshot.timer does on the server); the last snapshot
before kick-off stands in for SportyBet's closing price. Times are UTC.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import data, fixtures, sportybet

LOG_DIR = data.DEFAULT_CACHE.parent / "odds_log"
# Fixed column order, so rows from different runs line up in one file.
SB_COLUMNS = (["taken_at", "league", "event_id", "kickoff", "home", "away", "sb_home", "sb_away"]
              + [f"odds:{m}" for m in sportybet.MARKETS])
FD_ODDS = [f"{book}{o}" for book in ("B365", "Avg", "Max", "PS") for o in ("H", "D", "A")] \
    + [f"{book}{o}2.5" for book in ("B365", "Avg", "Max", "P") for o in (">", "<")]
FD_COLUMNS = ["taken_at", "Div", "Date", "Time", "HomeTeam", "AwayTeam", "Referee"] + FD_ODDS


def take(leagues: list[str], cache_dir: Path = data.DEFAULT_CACHE,
         now: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """(SportyBet events, football-data fixtures, notes about what failed)."""
    now = now or pd.Timestamp.now(tz="UTC").tz_localize(None)
    notes = []
    matches = data.load_matches(leagues, [data.current_season()], cache_dir,
                                refresh_current=False, with_xg=False)
    known = fixtures.known_teams(matches)

    frames = []
    for league in leagues:
        try:
            ev = sportybet.events(league, known.get(league, []), keep_unknown=True)
        except Exception as exc:  # SportyBet down or blocking: keep the other leagues
            notes.append(f"SportyBet {league}: {exc}")
            continue
        if not ev.empty:
            frames.append(ev)
    sb = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SB_COLUMNS)
    if not sb.empty:   # parse_events gives kick-offs in this computer's time
        sb["kickoff"] = (sb["kickoff"].dt.tz_localize(datetime.now().astimezone().tzinfo)
                         .dt.tz_convert("UTC").dt.tz_localize(None))
    sb["taken_at"] = now

    try:
        fixtures._football_data(cache_dir, refresh=False)   # refreshes the cached file when it's old
        fd = pd.read_csv(cache_dir / "fixtures_fd.csv")
        fd = fd[fd["Div"].isin(leagues)].copy()
    except Exception as exc:
        notes.append(f"football-data.co.uk fixtures: {exc}")
        fd = pd.DataFrame(columns=FD_COLUMNS)
    fd["taken_at"] = now
    return sb.reindex(columns=SB_COLUMNS), fd.reindex(columns=FD_COLUMNS), notes


def append(df: pd.DataFrame, kind: str, columns: list[str], log_dir: Path = LOG_DIR) -> Path:
    """Add rows to this month's `<kind>_YYYY-MM.csv`, writing the header once."""
    log_dir.mkdir(parents=True, exist_ok=True)
    month = pd.Timestamp(df["taken_at"].iloc[0]) if len(df) else pd.Timestamp.now()
    path = log_dir / f"{kind}_{month:%Y-%m}.csv"
    df.reindex(columns=columns).to_csv(path, mode="a", header=not path.exists(), index=False)
    return path


def save(sb: pd.DataFrame, fd: pd.DataFrame, log_dir: Path = LOG_DIR) -> list[Path]:
    return [append(df, kind, cols, log_dir)
            for df, kind, cols in ((sb, "sportybet", SB_COLUMNS), (fd, "footballdata", FD_COLUMNS))
            if not df.empty]


def load_log(kind: str = "sportybet", log_dir: Path = LOG_DIR) -> pd.DataFrame:
    """Every saved snapshot of one kind."""
    files = sorted(log_dir.glob(f"{kind}_*.csv"))
    if not files:
        return pd.DataFrame(columns=SB_COLUMNS if kind == "sportybet" else FD_COLUMNS)
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    for col in ("taken_at", "kickoff"):
        if col in df:
            df[col] = pd.to_datetime(df[col])
    return df


def closing(log: pd.DataFrame) -> pd.DataFrame:
    """Each SportyBet event's last saved prices before kick-off."""
    before = log[log["taken_at"] < log["kickoff"]]
    return before.sort_values("taken_at").groupby("event_id").tail(1).reset_index(drop=True)
