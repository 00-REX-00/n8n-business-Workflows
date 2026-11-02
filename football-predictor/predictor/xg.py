"""Expected goals (xG) per match and per player, from Understat.

Understat publishes xG for the top 5 leagues (plus Russia) from 2014-15.
On your machine this module reads understat.com directly. If that fails,
the Premier League falls back to the Understat copy kept in the
vaastav/Fantasy-Premier-League GitHub repository (team files, up to 2024-25),
and player data falls back to vibedatascience/understat_players_aggregated.
Everything is cached in data/raw.
"""
from __future__ import annotations

import functools
import gzip
import io
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

from . import teams
from .data import DEFAULT_CACHE, _decode, _download, current_season

UNDERSTAT_LEAGUES = {"E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga", "I1": "Serie_A", "F1": "Ligue_1"}
PLAYERS_MIRROR_LEAGUES = {"E0": "EPL", "SP1": "La_Liga", "D1": "Bundesliga", "I1": "Serie_A", "F1": "Ligue_1"}

VAASTAV_URL = ("https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/"
               "{tag}/understat/understat_{team}.csv")
PLAYERS_MIRROR_URL = ("https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/"
                      "main/understat_players_aggregated_2014_td.csv")


# ---------------------------------------------------------------- understat.com

# One league season's reply feeds xG, player shares and the fixture list, often
# within the same minute, so it is kept in memory for a while. A failure is
# remembered too: during an Understat outage, every team's player lookup would
# otherwise retry (and wait on DNS timeouts) one after another.
PAYLOAD_TTL_SECONDS = 3 * 3600
FAILURE_TTL_SECONDS = 30 * 60
PLAYERS_TTL_HOURS = 12   # this season's player totals change once a round
_payloads: dict[tuple[str, int], tuple[float, dict]] = {}
_failures: dict[tuple[str, int], tuple[float, str]] = {}


def clear_cache() -> None:
    _payloads.clear()
    _failures.clear()
    _players_mirror.cache_clear()


def _understat_league_json(league: str, season: int) -> dict:
    """{'dates': [...], 'players': [...]} for one Understat league season."""
    hit = _payloads.get((league, season))
    if hit and time.time() - hit[0] < PAYLOAD_TTL_SECONDS:
        return hit[1]
    failed = _failures.get((league, season))
    if failed and time.time() - failed[0] < FAILURE_TTL_SECONDS:
        raise RuntimeError(f"Understat unavailable, not retrying for {FAILURE_TTL_SECONDS // 60} minutes "
                           f"({failed[1]})")
    try:
        payload = _fetch_understat_league_json(league, season)
    except Exception as exc:
        _failures[(league, season)] = (time.time(), str(exc))
        raise
    _failures.pop((league, season), None)
    _payloads[(league, season)] = (time.time(), payload)
    return payload


def _fetch_understat_league_json(league: str, season: int) -> dict:
    """Understat has served this both as an AJAX endpoint and as JSON embedded in
    the league page; try both.
    """
    code = UNDERSTAT_LEAGUES[league]
    try:
        req = urllib.request.Request(
            f"https://understat.com/getLeagueData/{code}/{season}",
            headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest",
                     "Referer": f"https://understat.com/league/{code}/{season}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":  # Understat gzips the reply even when not asked to
            raw = gzip.decompress(raw)
        payload = json.loads(raw)
        if payload.get("dates"):
            return payload
    except Exception:
        pass
    html = _decode(_download(f"https://understat.com/league/{code}/{season}"))
    out = {}
    for var, key in (("datesData", "dates"), ("playersData", "players")):
        m = re.search(var + r"\s*=\s*JSON\.parse\('(.*?)'\)", html)
        if m:
            out[key] = json.loads(m.group(1).encode().decode("unicode_escape"))
    if not out.get("dates"):
        raise RuntimeError("no xG data found in Understat page")
    return out


def _from_understat(league: str, season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    payload = _understat_league_json(league, season)
    matches = pd.DataFrame([{
        "date": pd.Timestamp(d["datetime"]).normalize(),
        "u_home": d["h"]["title"], "u_away": d["a"]["title"],
        "xg_h": float(d["xG"]["h"]), "xg_a": float(d["xG"]["a"]),
    } for d in payload["dates"] if d.get("isResult") and d["xG"]["h"] is not None])
    players = pd.DataFrame(payload.get("players", []))
    return matches, players


# ---------------------------------------------------------------- GitHub mirrors

def _from_vaastav(season: int, fd_teams: list[str]) -> pd.DataFrame:
    """Premier League team xG from the vaastav repo (home rows only)."""
    tag = f"{season}-{(season + 1) % 100:02d}"
    rows = []
    for team in fd_teams:
        name = UNDERSTAT_NAMES.get(team, team).replace(" ", "_")
        try:
            df = pd.read_csv(io.BytesIO(_download(VAASTAV_URL.format(tag=tag, team=name))))
        except Exception:
            continue
        for _, r in df[df["h_a"] == "h"].iterrows():
            rows.append({"date": pd.Timestamp(r["date"]).normalize(), "home": team,
                         "xg_h": float(r["xG"]), "xg_a": float(r["xGA"])})
    return pd.DataFrame(rows)


# football-data.co.uk name -> Understat name, where they differ and the
# fuzzy matcher can't tell (used when we must build Understat file names).
UNDERSTAT_NAMES = {
    "Man City": "Manchester City", "Man United": "Manchester United",
    "Wolves": "Wolverhampton Wanderers", "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United", "West Brom": "West Bromwich Albion",
}


# ---------------------------------------------------------------- public API

def _match_names(u_names: list[str], fd_names: list[str]) -> dict[str, str]:
    out = {}
    for u in set(u_names):
        try:
            out[u] = teams.resolve(u, fd_names)
        except KeyError:
            pass
    return out


def attach_xg(matches: pd.DataFrame, cache_dir: Path = DEFAULT_CACHE) -> pd.DataFrame:
    """Add xg_h / xg_a columns (NaN where unknown) to football-data matches."""
    frames, missing = [], []
    for (league, season), grp in matches.groupby(["league", "season"]):
        if league not in UNDERSTAT_LEAGUES:
            continue
        cache = cache_dir / f"xg_{league}_{season}.csv"
        if cache.exists() and season != current_season():
            xg = pd.read_csv(cache, parse_dates=["date"])
        else:
            fd_names = sorted(set(grp["home"]) | set(grp["away"]))
            try:
                um, _ = _from_understat(league, season)
                names = _match_names(list(um["u_home"]) + list(um["u_away"]), fd_names)
                um["home"], um["away"] = um["u_home"].map(names), um["u_away"].map(names)
                xg = um.dropna(subset=["home", "away"])[["date", "home", "away", "xg_h", "xg_a"]]
            except Exception:
                xg = _from_vaastav(season, fd_names) if league == "E0" else pd.DataFrame()
            if xg.empty:
                if cache.exists():
                    xg = pd.read_csv(cache, parse_dates=["date"])
                else:
                    missing.append(f"{league} {season}")
                    continue
            else:
                cache.parent.mkdir(parents=True, exist_ok=True)
                xg.to_csv(cache, index=False)
        xg["league"], xg["season"] = league, season
        frames.append(xg)

    if missing:
        print(f"note: no xG for {', '.join(missing)}; those use shots on target instead")
    matches = matches.drop(columns=["xg_h", "xg_a"], errors="ignore")
    if not frames:
        return matches.assign(xg_h=float("nan"), xg_a=float("nan"))
    xg = pd.concat(frames, ignore_index=True)
    # Understat dates are in local kick-off time; allow a day either side.
    merged = matches.reset_index().merge(xg[["league", "season", "home", "date", "xg_h", "xg_a"]],
                                         on=["league", "season", "home"], how="left", suffixes=("", "_x"))
    merged = merged[(merged["date_x"].isna()) | ((merged["date_x"] - merged["date"]).abs() <= pd.Timedelta(days=1))]
    merged = merged.sort_values("xg_h", na_position="last").drop_duplicates("index").set_index("index")
    out = matches.copy()
    out["xg_h"] = merged["xg_h"].reindex(out.index)
    out["xg_a"] = merged["xg_a"].reindex(out.index)
    return out


RECENT_DAYS = 10   # football-data.co.uk is at most a few days behind


def missing_results(fd: pd.DataFrame, dates: list[dict], league: str, season: int) -> pd.DataFrame:
    """Understat results from the last RECENT_DAYS before football-data's latest
    match that football-data doesn't have. A match football-data lists within
    3 days, either way round, counts as present: it is the authority on dates
    and home/away (Understat once had Rennes v PSG backwards).
    """
    fd_names = sorted(set(fd["home"]) | set(fd["away"]))
    since = fd["date"].max() - pd.Timedelta(days=RECENT_DAYS)
    played = [d for d in dates if d.get("isResult") and pd.Timestamp(d["datetime"]).normalize() > since]
    names = _match_names([d["h"]["title"] for d in played] + [d["a"]["title"] for d in played], fd_names)
    rows = []
    for d in played:
        home, away = names.get(d["h"]["title"]), names.get(d["a"]["title"])
        if home is None or away is None:
            continue
        day = pd.Timestamp(d["datetime"]).normalize()
        pair = fd[((fd["home"] == home) & (fd["away"] == away)) | ((fd["home"] == away) & (fd["away"] == home))]
        if ((pair["date"] - day).abs() <= pd.Timedelta(days=3)).any():
            continue
        if ((fd["home"] == home) & (fd["away"] == away)).any():  # this season's fixture, on another date
            continue
        rows.append({"date": day, "league": league, "season": season, "home": home, "away": away,
                     "referee": None, "hg": float(d["goals"]["h"]), "ag": float(d["goals"]["a"]),
                     "xg_h": float(d["xG"]["h"]), "xg_a": float(d["xG"]["a"])})
    return pd.DataFrame(rows)


def add_recent_results(matches: pd.DataFrame) -> pd.DataFrame:
    """Append this season's results Understat has but football-data hasn't added
    yet, so form and ratings include the latest round. Goals and xG only."""
    season = current_season()
    extra = []
    for league, grp in matches[matches["season"] == season].groupby("league"):
        if league not in UNDERSTAT_LEAGUES:
            continue
        try:
            extra.append(missing_results(grp, _understat_league_json(league, season)["dates"], league, season))
        except Exception:
            continue
    extra = [e for e in extra if not e.empty]
    if not extra:
        return matches
    out = pd.concat([matches, *extra], ignore_index=True)
    return out.sort_values(["date", "league", "home"]).reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def _players_mirror() -> pd.DataFrame:
    """The GitHub copy of every Understat season's player totals (large): fetched once per run."""
    return pd.read_csv(io.BytesIO(_download(PLAYERS_MIRROR_URL)))


def load_players(league: str, season: int, fd_teams: list[str], cache_dir: Path = DEFAULT_CACHE) -> pd.DataFrame:
    """Season player totals: team, player, minutes, npxG, xA (Understat).

    Called once per team, so the saved copy is used while fresh (past seasons
    always, this season for PLAYERS_TTL_HOURS) and, if Understat is down, the
    last saved copy beats the large mirror download."""
    cache = cache_dir / f"players_{league}_{season}.csv"
    if cache.exists() and (season != current_season()
                           or time.time() - cache.stat().st_mtime < PLAYERS_TTL_HOURS * 3600):
        return pd.read_csv(cache)
    try:
        _, raw = _from_understat(league, season)
        raw = raw.rename(columns={"team_title": "team"})
    except Exception:
        raw = pd.DataFrame()
    if raw.empty and cache.exists():
        return pd.read_csv(cache)
    if raw.empty:
        try:
            mirror = _players_mirror()
            raw = mirror[(mirror["league"] == PLAYERS_MIRROR_LEAGUES[league]) & (mirror["year"] == season)]
            raw = raw.rename(columns={"team_title": "team"})
        except Exception:
            raw = pd.DataFrame()
    if raw.empty:
        return pd.DataFrame(columns=["team", "player", "minutes", "games", "npxG", "xA"])

    df = pd.DataFrame({
        "team": raw["team"].astype(str),
        "player": raw["player_name"],
        "minutes": pd.to_numeric(raw["time"], errors="coerce"),
        "games": pd.to_numeric(raw["games"], errors="coerce"),
        "npxG": pd.to_numeric(raw["npxG"], errors="coerce"),
        "xA": pd.to_numeric(raw["xA"], errors="coerce"),
    })
    # players who moved mid-season are listed as "Team A,Team B": keep the last club
    df["team"] = df["team"].str.split(",").str[-1]
    names = _match_names(list(df["team"]), fd_teams)
    df["team"] = df["team"].map(names)
    df = df.dropna(subset=["team"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df
