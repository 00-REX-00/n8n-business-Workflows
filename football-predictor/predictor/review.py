"""Grade a day's picks against the final scores.

Predictions are rebuilt from results before that day, so the model never sees
the day's scores: they're the picks the app showed that morning, except that
team news is as of now. Scores come from ESPN's public scoreboard, which has
them minutes after full time (Understat and football-data lag by hours to days).
Bookmaker odds, where graded, are football-data.co.uk's pre-match averages.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime

import pandas as pd

from . import data, fixtures, markets, predict, teams, value

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day}"
ESPN_SLUGS = {
    "E0": "eng.1", "E1": "eng.2", "SP1": "esp.1", "SP2": "esp.2", "I1": "ita.1", "I2": "ita.2",
    "D1": "ger.1", "D2": "ger.2", "F1": "fra.1", "F2": "fra.2", "N1": "ned.1", "P1": "por.1",
    "B1": "bel.1", "T1": "tur.1", "SC0": "sco.1", "G1": "gre.1",
}


def parse_espn(events: list[dict], league: str, known: list[str]) -> pd.DataFrame:
    """One row per match: kick-off (local), football-data team names, score if finished."""
    local = datetime.now().astimezone().tzinfo
    rows = []
    for e in events:
        side = {c["homeAway"]: c for c in e["competitions"][0]["competitors"]}
        names = []
        for c in (side["home"], side["away"]):
            t = c["team"]
            name = None
            for candidate in (t.get("displayName"), t.get("shortDisplayName"), t.get("name")):
                try:
                    name = teams.resolve(candidate, known) if candidate else None
                except KeyError:
                    continue
                if name:
                    break
            names.append(name)
        if None in names:
            continue
        status = e["status"]["type"]
        done = bool(status.get("completed"))
        rows.append({"league": league, "home": names[0], "away": names[1],
                     "kickoff": pd.Timestamp(e["date"]).tz_convert(local).tz_localize(None),
                     "hg": float(side["home"]["score"]) if done else float("nan"),
                     "ag": float(side["away"]["score"]) if done else float("nan"),
                     "status": status.get("description", "")})
    return pd.DataFrame(rows, columns=["league", "home", "away", "kickoff", "hg", "ag", "status"])


def scores(leagues: list[str], day: date, known: dict[str, list[str]]) -> pd.DataFrame:
    frames = []
    for league in leagues:
        if league not in ESPN_SLUGS or league not in known:
            continue
        req = urllib.request.Request(ESPN_URL.format(slug=ESPN_SLUGS[league], day=f"{day:%Y%m%d}"),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            frames.append(parse_espn(json.loads(resp.read())["events"], league, known[league]))
    return pd.concat(frames, ignore_index=True) if frames else parse_espn([], "", [])


def _with_odds(day_scores: pd.DataFrame) -> pd.DataFrame:
    """Add referee and pre-match bookmaker odds from football-data's fixtures file, where it has them.
    The cached copy comes first: a fresh one may already have dropped the day's matches."""
    cache = data.DEFAULT_CACHE / "fixtures_fd.csv"
    try:
        fd = fixtures.parse_football_data(pd.read_csv(cache)) if cache.exists() \
            else fixtures._football_data(data.DEFAULT_CACHE, refresh=False)
    except Exception:
        return day_scores
    extra = fd.drop(columns=["kickoff", "source"]).drop_duplicates(["league", "home", "away"])
    return day_scores.merge(extra, on=["league", "home", "away"], how="left")


def grade(results: list[dict], day_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(one row per match, one row per pick or value bet) for finished matches."""
    match_rows, pick_rows = [], []
    for r in results:
        s = day_scores[(day_scores["league"] == r["league"]) & (day_scores["home"] == r["home"])
                       & (day_scores["away"] == r["away"])]
        if s.empty or s["hg"].isna().all():
            continue
        s = s.iloc[0]
        row = {"hg": s["hg"], "ag": s["ag"]}
        p, odds = r["pred"]["probs"], r["odds"]
        won = lambda mk: markets.outcome(mk, row) == 1.0  # noqa: E731
        call = max(("1", "X", "2"), key=p.get)
        book = value.market_probs(odds)
        fav = min(("1", "X", "2"), key=odds.get) if all(k in odds for k in ("1", "X", "2")) else None
        actual = {mk: float(won(mk)) for mk in ("1", "X", "2")}
        top = r["picks"][0] if r["picks"] else None
        match_rows.append({
            "Kick-off": s["kickoff"], "League": data.LEAGUES.get(r["league"], r["league"]),
            "Match": f"{r['home']} v {r['away']}", "Score": f"{s['hg']:.0f}-{s['ag']:.0f}",
            "Model 1/X/2": f"{p['1']:.0%} / {p['X']:.0%} / {p['2']:.0%}",
            "Model call": markets.label(call), "Model right": won(call),
            "Bookmaker call": markets.label(fav) if fav else None, "Bookmaker right": won(fav) if fav else None,
            "Top pick": f"{markets.label(top.market)} ({top.prob:.0%})" if top else None,
            "Top pick won": won(top.market) if top else None, "Withheld": r["withheld"],
            "Model Brier": sum((p[k] - actual[k]) ** 2 for k in actual),
            "Bookmaker Brier": sum((book[k] - actual[k]) ** 2 for k in actual) if "1" in book else None,
        })
        match = f"{r['home']} v {r['away']} {s['hg']:.0f}-{s['ag']:.0f}"
        for i, pk in enumerate(r["picks"]):
            pick_rows.append({"Match": match, "Kind": "Top pick" if i == 0 else f"Pick {i + 1}",
                              "Market": markets.label(pk.market), "Model": pk.prob,
                              "Odds": odds.get(pk.market), "Won": won(pk.market), "Withheld": bool(r["withheld"])})
        for b, why in [(b, None) for b in r["bets"]] + list(r["skipped"]):
            pick_rows.append({"Match": match, "Kind": "Value bet" if why is None else "Value bet (withheld)",
                              "Market": markets.label(b.market), "Model": b.prob, "Odds": b.odds,
                              "Won": won(b.market), "Withheld": why is not None})
    return pd.DataFrame(match_rows), pd.DataFrame(pick_rows)


def summary(match_table: pd.DataFrame, pick_table: pd.DataFrame) -> dict:
    out = {"finished": len(match_table)}
    if match_table.empty:
        return out
    out["model_calls_right"] = int(match_table["Model right"].sum())
    graded = match_table.dropna(subset=["Bookmaker right"])
    out["bookmaker_calls_right"] = (int(graded["Bookmaker right"].sum()), len(graded))
    out["model_calls_right_same_games"] = int(graded["Model right"].sum())
    out["brier"] = (graded["Model Brier"].mean(), graded["Bookmaker Brier"].mean()) if len(graded) else None
    for kind in ("Top pick", "Value bet", "Value bet (withheld)"):
        k = pick_table[pick_table["Kind"] == kind] if not pick_table.empty else pick_table
        if len(k):
            priced = k.dropna(subset=["Odds"])
            out[kind] = {"won": int(k["Won"].sum()), "total": len(k), "expected": float(k["Model"].sum()),
                         "profit_units": float((priced["Won"] * priced["Odds"] - 1).sum()) if len(priced) else None,
                         "priced": len(priced)}
    allp = pick_table[pick_table["Kind"].str.startswith(("Top pick", "Pick"))] if not pick_table.empty else pick_table
    if len(allp):
        out["All best picks"] = {"won": int(allp["Won"].sum()), "total": len(allp), "expected": float(allp["Model"].sum())}
    return out


def review(leagues: list[str], day: date, matches: pd.DataFrame | None = None):
    """(match table, pick table, summary, matches not finished yet) for one day."""
    now = data.current_season()
    if matches is None:
        matches = data.load_matches(leagues, list(range(now - 3, now + 1)))
    day_scores = _with_odds(scores(leagues, day, fixtures.known_teams(matches)))
    if day_scores.empty:
        return pd.DataFrame(), pd.DataFrame(), {"finished": 0}, day_scores
    fx = day_scores.drop(columns=["hg", "ag", "status"]).assign(date=pd.Timestamp(day))
    results, _ = predict.analyse(predict.normalise_fixtures(fx), matches)
    match_table, pick_table = grade(results, day_scores)
    if not match_table.empty:
        match_table = match_table.sort_values(["Kick-off", "League"]).reset_index(drop=True)
    pending = day_scores[day_scores["hg"].isna()]
    return match_table, pick_table, summary(match_table, pick_table), pending
