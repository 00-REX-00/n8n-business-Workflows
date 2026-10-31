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


def parse_events(tournaments: list[dict], league: str, known: list[str]) -> pd.DataFrame:
    """One row per event: SportyBet event id, kick-off (local), our team names, odds:<market>."""
    local = datetime.now().astimezone().tzinfo
    rows = []
    for t in tournaments:
        for e in t.get("events", []):
            try:
                home = teams.resolve(e["homeTeamName"], known)
                away = teams.resolve(e["awayTeamName"], known)
            except KeyError:
                continue
            row = {"league": league, "event_id": e["eventId"], "home": home, "away": away,
                   "kickoff": pd.Timestamp(e["estimateStartTime"], unit="ms", tz="UTC")
                                .tz_convert(local).tz_localize(None)}
            for m in e.get("markets", []):
                if m.get("status", 0) != 0:   # suspended or closed
                    continue
                for o in m.get("outcomes", []):
                    ours = _BY_ID.get((m["id"], m.get("specifier") or "", o["id"]))
                    if ours and o.get("isActive", 1) and o.get("odds"):
                        row[f"odds:{ours}"] = float(o["odds"])
            rows.append(row)
    return pd.DataFrame(rows)


def events(league: str, known: list[str]) -> pd.DataFrame:
    """Upcoming SportyBet events (with odds) for one league."""
    if league not in TOURNAMENTS:
        return pd.DataFrame()
    market_ids = ",".join(sorted({m for m, _, _ in MARKETS.values()}, key=int))
    frames, page = [], 1
    while True:
        data = _call("factsCenter/pcUpcomingEvents", sportId="sr:sport:1", marketId=market_ids, pageSize=100,
                     pageNum=page, option=1, tournamentId=f"sr:tournament:{TOURNAMENTS[league]}")
        frames.append(parse_events(data.get("tournaments", []), league, known))
        if page * 100 >= data.get("totalNum", 0):
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
    odds_cols = [c for c in sb.columns if c.startswith("odds:")]
    for c in odds_cols:
        if c not in fx:
            fx[c] = float("nan")
    keyed = sb.drop_duplicates(["league", "home", "away"]).set_index(["league", "home", "away"])
    for i, r in fx.iterrows():
        key = (r["league"], r["home"], r["away"])
        if key not in keyed.index:
            continue
        s = keyed.loc[key]
        for c in [c for c in fx.columns if c.startswith("odds:")]:
            fx.at[i, c] = float("nan")   # don't mix sources within one match
        for c in odds_cols:
            fx.at[i, c] = s[c]
        fx.at[i, "odds_source"] = "SportyBet"
        fx.at[i, "event_id"] = s["event_id"]
    return fx


def selection(event_id: str, market: str) -> dict:
    market_id, specifier, outcome_id = MARKETS[market]
    return {"eventId": event_id, "marketId": market_id, "specifier": specifier or None, "outcomeId": outcome_id}


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
