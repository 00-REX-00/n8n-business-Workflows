"""Team news: who is injured, suspended or doubtful for a fixture.

Sources, tried in order:
  1. API-Football /injuries (all leagues; needs a free or paid key from
     dashboard.api-football.com, set as API_FOOTBALL_KEY or in the app).
  2. Fantasy Premier League (Premier League only; free, no key).

The rule is "no news, no bet": if no source answers for a fixture, its picks
are withheld. Responses are cached for NEWS_TTL_HOURS so the free API-Football
plan (100 requests/day) lasts: one request per league per match day.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import teams
from .data import DEFAULT_CACHE

NEWS_TTL_HOURS = 3
API_FOOTBALL_URL = "https://v3.football.api-sports.io/injuries?league={league}&season={season}&date={date}"
API_FOOTBALL_LEAGUES = {
    "E0": 39, "SP1": 140, "I1": 135, "D1": 78, "F1": 61,
    "E1": 40, "N1": 88, "P1": 94, "B1": 144, "T1": 203, "SC0": 179,
    "D2": 79, "I2": 136, "SP2": 141, "F2": 62, "G1": 197,
}
FPL_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
# FPL status codes: a available, d doubtful, i injured, s suspended,
# u unavailable (left club / on loan), n not eligible
FPL_OUT = {"i", "s", "u", "n"}


@dataclass
class TeamNews:
    out: list[str] = field(default_factory=list)        # will not play
    doubtful: list[str] = field(default_factory=list)   # may not play


@dataclass
class FixtureNews:
    found: bool
    source: str
    home: TeamNews
    away: TeamNews
    note: str = ""


def api_key() -> str | None:
    key = os.environ.get("API_FOOTBALL_KEY")
    if key:
        return key
    try:
        settings = json.loads((DEFAULT_CACHE.parent / "settings.json").read_text())
        return settings.get("api_football_key") or None
    except (OSError, ValueError):
        return None


def _cached_json(cache: Path, fetch) -> object:
    if cache.exists() and time.time() - cache.stat().st_mtime < NEWS_TTL_HOURS * 3600:
        return json.loads(cache.read_text())
    payload = fetch()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload))
    return payload


# ---------------------------------------------------------------- API-Football

def _api_football(league: str, season: int, day: str, key: str) -> list[dict]:
    # Refusals are cached like answers, so a plan that can't see this season
    # (the free plan only covers 2022-2024) isn't asked again for every fixture.
    def fetch():
        req = urllib.request.Request(
            API_FOOTBALL_URL.format(league=API_FOOTBALL_LEAGUES[league], season=season, date=day),
            headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        return {"errors": payload.get("errors") or None, "response": payload.get("response", [])}
    payload = _cached_json(DEFAULT_CACHE / f"news_apif_{league}_{day}.json", fetch)
    if payload.get("errors"):
        errors = payload["errors"]
        raise RuntimeError("; ".join(map(str, errors.values())) if isinstance(errors, dict) else str(errors))
    return payload["response"]


def parse_api_football(rows: list[dict], known_teams: list[str]) -> dict[str, TeamNews]:
    """Injury rows -> TeamNews per (our) team name. 'Missing Fixture' = out."""
    news: dict[str, TeamNews] = {}
    for row in rows:
        try:
            team = teams.resolve(row["team"]["name"], known_teams)
        except KeyError:
            continue
        t = news.setdefault(team, TeamNews())
        name = row["player"]["name"]
        (t.out if row["player"].get("type") == "Missing Fixture" else t.doubtful).append(name)
    return news


# ---------------------------------------------------------------- Fantasy Premier League

def _fpl() -> dict:
    return _cached_json(DEFAULT_CACHE / "news_fpl.json", lambda: json.loads(
        urllib.request.urlopen(urllib.request.Request(FPL_URL, headers={"User-Agent": "Mozilla/5.0"}),
                               timeout=30).read()))


def parse_fpl(payload: dict, known_teams: list[str]) -> dict[str, TeamNews]:
    team_names = {}
    for t in payload["teams"]:
        try:
            team_names[t["id"]] = teams.resolve(t["name"], known_teams)
        except KeyError:
            continue
    news: dict[str, TeamNews] = {}
    for p in payload["elements"]:
        team = team_names.get(p["team"])
        if team is None or p["status"] == "a":
            continue
        name = f"{p['first_name']} {p['second_name']}"
        t = news.setdefault(team, TeamNews())
        chance = p.get("chance_of_playing_next_round")
        if p["status"] in FPL_OUT or chance == 0:
            t.out.append(name)
        else:
            t.doubtful.append(name)
    return news


# ---------------------------------------------------------------- public

def fixture_news(league: str, season: int, day: str, home: str, away: str,
                 known_teams: list[str]) -> FixtureNews:
    """Team news for one fixture, or found=False if no source answered."""
    errors = []
    key = api_key()
    if key and league in API_FOOTBALL_LEAGUES:
        try:
            news = parse_api_football(_api_football(league, season, day, key), known_teams)
            return FixtureNews(True, "API-Football", news.get(home, TeamNews()), news.get(away, TeamNews()))
        except Exception as exc:
            errors.append(f"API-Football: {exc}")
    elif league in API_FOOTBALL_LEAGUES:
        errors.append("API-Football: no key set")
    if league == "E0":
        try:
            news = parse_fpl(_fpl(), known_teams)
            return FixtureNews(True, "Fantasy Premier League", news.get(home, TeamNews()),
                               news.get(away, TeamNews()))
        except Exception as exc:
            errors.append(f"FPL: {exc}")
    return FixtureNews(False, "", TeamNews(), TeamNews(), note="; ".join(errors) or "no news source for this league")


def team_news_frame(n: FixtureNews, home: str, away: str) -> pd.DataFrame:
    rows = [{"Team": team, "Player": p, "Status": status}
            for team, tn in ((home, n.home), (away, n.away))
            for status, players in (("Out", tn.out), ("Doubtful", tn.doubtful)) for p in players]
    return pd.DataFrame(rows, columns=["Team", "Player", "Status"])
