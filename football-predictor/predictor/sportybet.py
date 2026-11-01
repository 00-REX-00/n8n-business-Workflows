"""SportyBet Nigeria: its current odds for our fixtures, and booking codes.

SportyBet has no public API. This reads the same data feed its website shows
and calls the same "Book Bet" service a visitor uses, so it can stop working
whenever SportyBet changes its site. It never logs in and never places a bet:
a booking code only loads selections into a betslip; you still choose the
stake and confirm on SportyBet yourself.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime

import pandas as pd

from . import teams, value

API = "https://www.sportybet.com/api/ng/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36",
           "Accept": "application/json", "Content-Type": "application/json",
           "Referer": "https://www.sportybet.com/ng/"}
TOURNAMENTS = {  # football-data league code -> SportyBet (Sportradar) tournament id
    "E0": 17, "SP1": 8, "I1": 23, "D1": 35, "F1": 34, "E1": 18, "N1": 37, "P1": 238,
    "B1": 38, "T1": 52, "SC0": 36, "D2": 44, "I2": 53, "SP2": 54, "F2": 182, "G1": 185,
}
# our market -> (SportyBet market id, specifier, outcome id)
MARKETS = {
    "1": ("1", "", "1"), "X": ("1", "", "2"), "2": ("1", "", "3"),
    "1X": ("10", "", "9"), "12": ("10", "", "10"), "X2": ("10", "", "11"),
    "dnb_1": ("11", "", "4"), "dnb_2": ("11", "", "5"),
    "btts_yes": ("29", "", "74"), "btts_no": ("29", "", "76"),
    **{f"{side}_{line}": ("18", f"total={line}", oid)
       for line in ("0.5", "1.5", "2.5", "3.5", "4.5") for side, oid in (("over", "12"), ("under", "13"))},
    **{f"{team}_{side}_{line}": (mid, f"total={line}", oid)
       for team, mid in (("home", "19"), ("away", "20")) for line in ("0.5", "1.5")
       for side, oid in (("over", "12"), ("under", "13"))},
}
_BY_ID = {v: k for k, v in MARKETS.items()}
# The feed sends at most 10 events per page whatever pageSize asks for, but
# pages by the requested size, so asking for more silently skips events.
PAGE_SIZE = 10
MAX_PAGES = 30
_LEAGUE_BY_TOURNAMENT = {f"sr:tournament:{t}": league for league, t in TOURNAMENTS.items()}


def implied_probs(odds: dict[str, float]) -> dict[str, float]:
    """SportyBet's own probability for each market, margin removed: 1X2 and
    two-way markets are normalised, double chance is built from 1X2."""
    out = {k: v for k, v in value.market_probs(odds).items() if not k.startswith("margin:")}
    if all(k in out for k in ("1", "X", "2")):
        out.update({"1X": out["1"] + out["X"], "X2": out["X"] + out["2"], "12": out["1"] + out["2"]})
    if odds.get("dnb_1", 0) > 1 and odds.get("dnb_2", 0) > 1:
        total = 1 / odds["dnb_1"] + 1 / odds["dnb_2"]
        out.update({"dnb_1": 1 / odds["dnb_1"] / total, "dnb_2": 1 / odds["dnb_2"] / total})
    return out


def _call(path: str, body: dict | None = None, **params) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers=HEADERS, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if payload.get("bizCode") != 10000:
        raise RuntimeError(f"SportyBet: {payload.get('message', payload)}")
    return payload.get("data") or {}


def _resolve(name: str, known: list[str]) -> str | None:
    try:
        return teams.resolve(name, known)
    except KeyError:
        return None


def parse_events(tournaments: list[dict], league: str, known: list[str],
                 keep_unknown: bool = False) -> pd.DataFrame:
    """One row per event: SportyBet event id, kick-off (local), our team names,
    SportyBet's own names (sb_home, sb_away), odds:<market> and prob:<market>.
    prob is SportyBet's own probability for the outcome, margin-free (each
    market's sum to 1), so odds x prob is its own expected return per unit.
    Events whose names we can't place are skipped, or kept with home/away None
    if `keep_unknown`."""
    local = datetime.now().astimezone().tzinfo
    rows = []
    for t in tournaments:
        for e in t.get("events", []):
            home, away = _resolve(e["homeTeamName"], known), _resolve(e["awayTeamName"], known)
            if (home is None or away is None) and not keep_unknown:
                continue
            row = {"league": league, "event_id": e["eventId"], "home": home, "away": away,
                   "sb_home": e["homeTeamName"], "sb_away": e["awayTeamName"],
                   "kickoff": pd.Timestamp(e["estimateStartTime"], unit="ms", tz="UTC")
                                .tz_convert(local).tz_localize(None)}
            for m in e.get("markets", []):
                if m.get("status", 0) != 0:   # suspended or closed
                    continue
                for o in m.get("outcomes", []):
                    ours = _BY_ID.get((m["id"], m.get("specifier") or "", o["id"]))
                    if ours and o.get("isActive", 1) and o.get("odds"):
                        row[f"odds:{ours}"] = float(o["odds"])
                        if o.get("probability"):
                            row[f"prob:{ours}"] = float(o["probability"])
            rows.append(row)
    return pd.DataFrame(rows)


def events(league: str, known: list[str], keep_unknown: bool = False) -> pd.DataFrame:
    """Upcoming SportyBet events (with odds) for one league."""
    if league not in TOURNAMENTS:
        return pd.DataFrame()
    market_ids = ",".join(sorted({m for m, _, _ in MARKETS.values()}, key=int))
    frames, page = [], 1
    while page <= MAX_PAGES:
        data = _call("factsCenter/pcUpcomingEvents", sportId="sr:sport:1", marketId=market_ids,
                     pageSize=PAGE_SIZE, pageNum=page, option=1,
                     tournamentId=f"sr:tournament:{TOURNAMENTS[league]}")
        frames.append(parse_events(data.get("tournaments", []), league, known, keep_unknown))
        if page * PAGE_SIZE >= (data.get("totalNum") or 0):
            break
        page += 1
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def merge_odds(fx: pd.DataFrame, sb: pd.DataFrame) -> pd.DataFrame:
    """Use SportyBet's odds for fixtures it lists (odds_source = "SportyBet"),
    keeping the bookmaker average elsewhere."""
    fx = fx.copy()
    fx["odds_source"] = ["Bookmaker average" if any(pd.notna(r.get(c)) for c in fx.columns if c.startswith("odds:"))
                         else None for _, r in fx.iterrows()]
    fx["event_id"] = None
    if sb.empty:
        return fx
    odds_cols = [c for c in sb.columns if c.startswith(("odds:", "prob:"))]
    for c in odds_cols:
        if c not in fx:
            fx[c] = float("nan")
    keyed = sb.drop_duplicates(["league", "home", "away"]).set_index(["league", "home", "away"])
    for i, r in fx.iterrows():
        key = (r["league"], r["home"], r["away"])
        if key not in keyed.index:
            continue
        s = keyed.loc[key]
        for c in [c for c in fx.columns if c.startswith(("odds:", "prob:"))]:
            fx.at[i, c] = float("nan")   # don't mix sources within one match
        for c in odds_cols:
            fx.at[i, c] = s[c]
        fx.at[i, "odds_source"] = "SportyBet"
        fx.at[i, "event_id"] = s["event_id"]
    return fx


def add_unlisted(fx: pd.DataFrame, sb: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Add SportyBet events kicking off in [start, end) that the fixture sources
    don't list yet (football-data posts only a few days ahead, Understat covers
    only the top 5), so a ticket can use every match SportyBet prices."""
    if sb.empty:
        return fx
    sb = sb[sb["home"].notna() & sb["away"].notna() & (sb["kickoff"] >= start) & (sb["kickoff"] < end)]
    listed = set(zip(fx["league"], fx["home"], fx["away"])) if not fx.empty else set()
    extra = sb[[k not in listed for k in zip(sb["league"], sb["home"], sb["away"])]]
    extra = extra.drop_duplicates(["league", "home", "away"])
    if extra.empty:
        return fx
    extra = extra.drop(columns=["sb_home", "sb_away"], errors="ignore").assign(
        date=extra["kickoff"].dt.normalize(), referee=None, source="SportyBet", odds_source="SportyBet")
    out = pd.concat([fx, extra], ignore_index=True)
    return out.sort_values(["kickoff", "league", "home"]).reset_index(drop=True)


def selection(event_id: str, market: str) -> dict:
    market_id, specifier, outcome_id = MARKETS[market]
    return {"eventId": event_id, "marketId": market_id, "specifier": specifier or None, "outcomeId": outcome_id}


def raw_selection(leg: dict) -> dict:
    """Booking selection for a leg read from a code, exactly as it was (any league or market)."""
    return {"eventId": leg["event_id"], "marketId": leg["market_id"], "specifier": leg["specifier"] or None,
            "outcomeId": leg["outcome_id"]}


def parse_code(data: dict, known: dict[str, list[str]]) -> tuple[list[dict], int]:
    """(one dict per leg, number of selections SportyBet says are no longer available)
    from a booking code's data. `known` maps our league codes to team names."""
    local = datetime.now().astimezone().tzinfo
    legs = []
    for e in data.get("outcomes", []):
        tournament = e.get("sport", {}).get("category", {}).get("tournament", {})
        league = _LEAGUE_BY_TOURNAMENT.get(tournament.get("id"))
        names = known.get(league, []) if league else []
        status = e.get("status", 0)
        state = ("Not started" if status == 0 else
                 f"Live {e.get('setScore', '')} ({e.get('playedSeconds', '')})" if status == 1 else
                 f"Closed ({e.get('matchStatus', status)})")
        for m in e.get("markets", []):
            specifier = m.get("specifier") or ""
            for o in m.get("outcomes", []):
                legs.append({
                    "event_id": e["eventId"], "league": league, "tournament": tournament.get("name", ""),
                    "sb_home": e["homeTeamName"], "sb_away": e["awayTeamName"],
                    "home": _resolve(e["homeTeamName"], names) if names else None,
                    "away": _resolve(e["awayTeamName"], names) if names else None,
                    "kickoff": pd.Timestamp(e["estimateStartTime"], unit="ms", tz="UTC")
                                 .tz_convert(local).tz_localize(None),
                    "started": status != 0, "state": state,
                    "market_id": m["id"], "specifier": specifier, "outcome_id": o["id"],
                    "market": _BY_ID.get((m["id"], specifier, o["id"])),
                    "label": f"{m.get('desc', '')}: {o.get('desc', '')}",
                    "odds": float(o["odds"]) if o.get("odds") else float("nan"),
                    "prob": float(o["probability"]) if o.get("probability") else float("nan"),
                    "active": bool(o.get("isActive", 1)) and m.get("status", 0) == 0,
                })
    return legs, len(data.get("unavailableOutcomes") or [])


def load_code(code: str, known: dict[str, list[str]]) -> tuple[list[dict], int]:
    """Read a SportyBet booking code (no login): see parse_code."""
    return parse_code(_call(f"orders/share/{urllib.parse.quote(code.strip().upper())}"), known)


def book(selections: list[dict]) -> dict:
    """Create a booking code. Returns {code, url, odds: [...], unavailable: [...]}."""
    data = _call("orders/share", {"selections": selections})
    odds = []
    for e in data.get("outcomes", []):
        for m in e.get("markets", []):
            for o in m.get("outcomes", []):
                odds.append({"event": f"{e['homeTeamName']} v {e['awayTeamName']}", "market": m.get("desc"),
                             "pick": o.get("desc"), "odds": float(o["odds"]) if o.get("odds") else None})
    return {"code": data["shareCode"], "url": data.get("shareURL", "").replace("http://", "https://"),
            "odds": odds, "unavailable": data.get("unavailableOutcomes", [])}
