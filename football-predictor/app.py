"""Football Predictor web app.  Run:  streamlit run app.py"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from predictor import (absences, acca, backtest, calibration, data, doctor, fixtures, history, markets, news,
                       picks, predict, review, safety, slip, sportybet, tracker, value, xg)
from predictor.model import LeagueModel

ROOT = Path(__file__).resolve().parent
BACKTEST_CSV = ROOT / "output" / "backtest.csv"
# On the server (deploy/): friends log in through nginx, which passes the login
# name in X-Remote-User. Shared mode hides everything that changes the model or
# shared data, and keeps each person's bankroll and bet log separate.
SHARED = os.environ.get("PREDICTOR_SHARED") == "1"


def current_user() -> str:
    if not SHARED:
        return "local"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", st.context.headers.get("X-Remote-User") or "") or "guest"


def user_dir() -> Path:
    return ROOT / "data" / "users" / current_user() if SHARED else ROOT / "data"

# Chart colours (validated categorical slot 1, sequential blue ramp, status colours)
BLUE = "#2a78d6"
SEQ_LOW, SEQ_HIGH = "#cde2fb", "#0d366b"
GOOD = "#0ca30c"

absences_leagues = {"E0", "SP1", "I1", "D1", "F1"}
PICKER_DAYS = 7           # how far ahead the Match analysis fixture picker looks
MEGA_DAYS = 14            # longest window for Bet of the day's "Mega odds" tickets

ODDS_MARKETS = [
    "1", "X", "2", "1X", "X2", "12",
    "over_1.5", "under_1.5", "over_2.5", "under_2.5", "over_3.5", "under_3.5",
    "btts_yes", "btts_no", "home_over_0.5", "away_over_0.5", "home_over_1.5", "away_over_1.5",
    "cards_over_3.5", "cards_under_3.5", "cards_over_4.5", "cards_under_4.5",
    "corners_over_9.5", "corners_under_9.5",
]

st.set_page_config(page_title="Football Predictor", page_icon="⚽", layout="wide")
# Loading screen: turns every spinner into a full-screen bouncing-football overlay.
st.markdown(f"<style>{(ROOT / 'assets' / 'loader.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)


# ---------------------------------------------------------------- data/model

@st.cache_data(ttl=6 * 3600, show_spinner="Loading match data…")
def load_matches(leagues: tuple[str, ...], refresh_token: int) -> pd.DataFrame:
    now = data.current_season()
    return data.load_matches(list(leagues), list(range(now - 3, now + 1)),
                             refresh_current=refresh_token > 0)


@st.cache_resource(show_spinner="Fitting model…", max_entries=32)
def league_model(league: str, as_of: date, refresh_token: int) -> LeagueModel:
    return LeagueModel.fit(load_matches((league,), refresh_token), league, pd.Timestamp(as_of))


@st.cache_data(ttl=6 * 3600, show_spinner="Loading player data…")
def squad_shares(league: str, team: str, season: int, fd_teams: tuple[str, ...]) -> pd.DataFrame:
    return absences.team_shares(league, team, season, list(fd_teams))


@st.cache_data(ttl=news.NEWS_TTL_HOURS * 3600, show_spinner="Checking team news…")
def fixture_news(league: str, season: int, day: str, home: str, away: str,
                 fd_teams: tuple[str, ...], key_token: str) -> news.FixtureNews:
    return news.fixture_news(league, season, day, home, away, list(fd_teams))


@st.cache_data(ttl=600, show_spinner="Grading picks against the scores…")
def review_day(leagues: tuple[str, ...], day: date, refresh_token: int):
    return review.review(list(leagues), day, load_matches(leagues, refresh_token))


@st.cache_data(ttl=6 * 3600, show_spinner="Loading 10 seasons of past matches (the first time takes a minute)…")
def league_archive(league: str, refresh_token: int) -> pd.DataFrame:
    return history.archive(league)


@st.cache_data(ttl=fixtures.FIXTURES_TTL_HOURS * 3600, show_spinner="Fetching fixtures…")
def upcoming_fixtures(leagues: tuple[str, ...], days: int, today: date,
                      refresh_token: int) -> tuple[pd.DataFrame, list[str]]:
    known = fixtures.known_teams(load_matches(leagues, refresh_token))
    return fixtures.upcoming(list(leagues), days, known, refresh=refresh_token > 0)


@st.cache_data(ttl=600, show_spinner="Getting SportyBet odds…")
def sportybet_events(league: str, known: tuple[str, ...]) -> pd.DataFrame:
    return sportybet.events(league, list(known))


def sportybet_odds(leagues: tuple[str, ...], known: dict[str, list[str]], notes: list[str]) -> pd.DataFrame:
    """SportyBet's upcoming events with odds, for every league it covers."""
    frames = []
    for lg in leagues:
        try:
            frames.append(sportybet_events(lg, tuple(known.get(lg, []))))
        except Exception as exc:
            notes.append(f"SportyBet odds unavailable for {data.LEAGUES.get(lg, lg)} ({exc}); using the "
                         "bookmaker average.")
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=600, show_spinner="Analysing fixtures…")
def analyse_upcoming(leagues: tuple[str, ...], days: int, today: date, refresh_token: int,
                     key_token: str, sportybet_only: bool = False) -> tuple[list[dict], list[str]]:
    """Predict the next `days` days' fixtures, at SportyBet's odds where it lists the match.

    Matches SportyBet lists that the fixture sources don't have yet are added.
    With `sportybet_only`, matches SportyBet doesn't price are skipped (tickets
    can't use them), which saves time over long windows."""
    fx, notes = upcoming_fixtures(leagues, days, today, refresh_token)
    notes = list(notes)
    matches = load_matches(leagues, refresh_token)
    sb = sportybet_odds(leagues, fixtures.known_teams(matches), notes)
    fx = sportybet.merge_odds(fx, sb)
    now = pd.Timestamp.now()
    fx = sportybet.add_unlisted(fx, sb, now, now.normalize() + pd.Timedelta(days=days))
    if sportybet_only:
        fx = fx[fx["odds_source"] == "SportyBet"]
    if fx.empty:
        return [], notes
    results, warnings = predict.analyse(predict.normalise_fixtures(fx), matches)
    return results, notes + warnings


@st.cache_data(ttl=120, show_spinner="Reading the booking code…")
def booking_code(code: str, refresh_token: int) -> tuple[list[dict], int]:
    leagues = tuple(sorted(lg for lg in data.LEAGUES if lg in sportybet.TOURNAMENTS))
    return sportybet.load_code(code, fixtures.known_teams(load_matches(leagues, refresh_token)))


def book_on_sportybet(legs: list[slip.Leg]) -> tuple[dict | None, pd.DataFrame]:
    """Booking code for the slip, and each leg's current SportyBet odds against its value range."""
    rows, selections = [], []
    for leg in legs:
        known = fixtures.known_teams(load_matches((leg.league,), st.session_state.refresh)).get(leg.league, [])
        ev = sportybet_events(leg.league, tuple(known))
        hit = ev[(ev["home"] == leg.home) & (ev["away"] == leg.away)] if not ev.empty else ev
        window = safety.bettable_odds(leg.market, leg.prob)
        row = {"Match": f"{leg.home} v {leg.away}", "Pick": markets.label(leg.market), "Slip odds": leg.odds,
               "SportyBet now": None, "Bet at odds": f"{window[0]:.2f}–{window[1]:.2f}" if window else "–"}
        if hit.empty or leg.market not in sportybet.MARKETS:
            row["Status"] = "Not on SportyBet: add it by hand" if hit.empty else "Market not supported: add by hand"
        else:
            sb_odds = hit.iloc[0].get(f"odds:{leg.market}")
            row["SportyBet now"] = sb_odds if pd.notna(sb_odds) else None
            row["Status"] = ("Market closed on SportyBet" if row["SportyBet now"] is None
                             else "✅ Still value" if window and window[0] <= sb_odds <= window[1]
                             else "Below the value range: consider removing" if window and sb_odds < window[0]
                             else "Above the range: check the news" if window else "No value range")
            if row["SportyBet now"] is not None:
                selections.append(sportybet.selection(hit.iloc[0]["event_id"], leg.market))
        rows.append(row)
    return (sportybet.book(selections) if selections else None), pd.DataFrame(rows)


def add_to_slip(leg: slip.Leg) -> None:
    legs = st.session_state.setdefault("slip", [])
    if any((l.home, l.away, l.market) == (leg.home, leg.away, leg.market) for l in legs):
        st.toast("Already on the slip")
        return
    legs.append(leg)
    st.toast(f"Added to slip: {leg.home} v {leg.away}, {markets.label(leg.market)}")


def load_settings() -> dict:
    try:
        return json.loads((user_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        return {"bankroll": 50000.0}


def save_settings(s: dict) -> None:
    path = user_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s))


def current_teams(lm: LeagueModel) -> list[str]:
    """Teams in the latest season of the data (relegated sides drop out)."""
    h = lm.history
    latest = h[h["season"] == h["season"].max()]
    return sorted(set(latest["home"]) | set(latest["away"]))


def pct(x: float) -> str:
    return "" if x is None or x != x else f"{x:.1%}"


def verdict(market: str, prob: float, odds: float | None, bankroll: float) -> str:
    if not odds:
        return ""
    if market.startswith(value.NO_SKILL_PREFIXES):
        return "Not bettable: model has no proven skill here"
    bets = value.find_value({market: prob}, {market: odds})
    if bets:
        b = bets[0]
        return f"✅ VALUE: stake {b.stake_pct:.1%} ({b.stake_pct * bankroll:,.0f})"
    e = value.edge(prob, odds)
    return "No value" if e < value.MIN_EDGE else "Edge but outside safety limits"


def odds_window(market: str, prob: float) -> str:
    w = safety.bettable_odds(market, prob)
    return f"{w[0]:.2f}–{w[1]:.2f}" if w else "–"


def fixture_odds(fx: pd.Series | None) -> dict[str, float]:
    """Bookmaker odds that came with a fetched fixture, by market."""
    if fx is None:
        return {}
    return {c.split(":", 1)[1]: float(fx[c]) for c in fx.index if c.startswith("odds:") and pd.notna(fx[c])}


def day_label(day: pd.Timestamp) -> str:
    offset = (day.date() - date.today()).days
    prefix = {0: "Today, ", 1: "Tomorrow, "}.get(offset, "")
    return f"{prefix}{day:%A} {day.day} {day:%B}"


def headline_metrics(pred: dict) -> None:
    probs = pred["probs"]
    m = st.columns(6)
    m[0].metric("xG home–away", f"{pred['xg_home']:.1f}–{pred['xg_away']:.1f}")
    m[1].metric("Home win", f"{probs['1']:.0%}")
    m[2].metric("Draw", f"{probs['X']:.0%}")
    m[3].metric("Away win", f"{probs['2']:.0%}")
    m[4].metric("Expected cards", f"{pred.get('exp_cards', float('nan')):.1f}",
                help=f"Referee factor ×{pred['referee_factor']:.2f}" if "referee_factor" in pred else None)
    m[5].metric("Expected corners", f"{pred.get('exp_corners', float('nan')):.1f}")


def score_heatmap(pred: dict, home: str, away: str) -> None:
    st.subheader("Likely scores")
    mat = pred["matrix"][:6, :6]
    heat = pd.DataFrame([{"home_goals": i, "away_goals": j, "prob": float(mat[i, j])}
                         for i in range(6) for j in range(6)])
    base = alt.Chart(heat).encode(
        x=alt.X("away_goals:O", title=f"{away} goals", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("home_goals:O", title=f"{home} goals", sort="descending"),
    )
    cells = base.mark_rect(cornerRadius=3, stroke="white", strokeWidth=2).encode(
        color=alt.Color("prob:Q", scale=alt.Scale(range=[SEQ_LOW, SEQ_HIGH]), legend=None),
        tooltip=[alt.Tooltip("home_goals:O", title=home), alt.Tooltip("away_goals:O", title=away),
                 alt.Tooltip("prob:Q", title="Probability", format=".1%")],
    )
    labels = base.mark_text(fontSize=11).encode(
        text=alt.Text("prob:Q", format=".0%"),
        color=alt.condition(alt.datum.prob > 0.06, alt.value("white"), alt.value("#0b0b0b")),
    )
    st.altair_chart((cells + labels).properties(height=300), width="stretch")


def form_and_h2h(league: str, home: str, away: str, before: date) -> None:
    st.subheader("Form & head-to-head")
    recent = load_matches((league,), st.session_state.refresh)
    try:
        past = history.combine(league_archive(league, st.session_state.refresh), recent)
    except Exception as exc:  # archive unreachable: fall back to the model's own seasons
        st.caption(f"Older seasons unavailable ({exc}); showing the model's own seasons only.")
        past = history.combine(recent, recent)
    when = pd.Timestamp(before)
    cols = st.columns(2)
    for col, team in zip(cols, (home, away)):
        f = history.form(past, team, when)
        col.markdown(f"**{team}**, last {len(f)} (newest first): `{''.join(f['Result']) or '–'}`")
        col.dataframe(f, hide_index=True, width="stretch")
    h2h = history.head_to_head(past, home, away, when)
    if h2h.empty:
        st.markdown(f"**Head-to-head:** no league meetings in the last {history.H2H_SEASONS} seasons.")
    else:
        st.markdown(f"**Head-to-head, last {len(h2h)} meetings:** {history.record(h2h, home, away)}")
        st.dataframe(h2h, hide_index=True, width="stretch")
    st.caption(f"League matches over the last {history.H2H_SEASONS} seasons, including the division above or "
               "below; cup and European games aren't in the data. Shown for context: the probabilities use "
               "team ratings built from every recent match, not just these few.")


def best_picks_table(pick_list: list[picks.Pick], withheld: str | None, book_odds: dict[str, float],
                     source: str | None = None) -> None:
    st.subheader("Best picks")
    if not pick_list:
        st.caption("No pick: nothing the model rates likely enough at odds worth playing.")
        return
    if withheld:
        st.warning(f"Withheld: {withheld}. These are the model's leans, not picks to bet.")
    where = "SportyBet" if source == "SportyBet" else "Market odds"
    rows = []
    for p in pick_list:
        lo, hi = p.odds_range
        o = book_odds.get(p.market)
        now = ("Check SportyBet" if o is None else "✅ Value" if lo <= o <= hi
               else "Odds too low" if o < lo else "Edge too big: check the news")
        rows.append({"Pick": markets.label(p.market), "Model": p.prob, "Bet at odds": f"{lo:.2f}–{hi:.2f}",
                     where: o, "Verdict": now})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Model": st.column_config.NumberColumn(format="percent"),
        where: st.column_config.NumberColumn(format="%.2f", help="SportyBet's current odds" if where == "SportyBet"
                                             else "Bookmaker average, where posted"),
    }, column_order=["Pick", "Model", "Bet at odds"] + ([where, "Verdict"] if book_odds else []))
    st.caption(f"The most likely outcomes in markets where the backtest showed skill, skipping anything above "
               f"{picks.MAX_PICK_PROB:.0%} (too short to pay). Bet only if SportyBet's odds are inside the range: "
               "below it a pick can win often and still lose money.")


def top_pick_text(r: dict) -> str:
    if not r["picks"]:
        return "–"
    p = r["picks"][0]
    lo, hi = p.odds_range
    o = r["odds"].get(p.market)
    price = (f"at {lo:.2f}+" if o is None else f"{o:.2f} ✅" if lo <= o <= hi
             else f"{o:.2f}, needs {lo:.2f}+" if o < lo else f"{o:.2f}, edge too big")
    text = f"{markets.label(p.market)} {p.prob:.0%} · {price}"
    return f"⛔ {text}" if r["withheld"] else text


def chance_text(p: float) -> str:
    """'8.0%' for everyday chances, '1 in 9,300' for tiny ones."""
    return f"{p:.1%}" if p >= 0.01 else f"1 in {float(f'{1 / p:.2g}'):,.0f}"


def pick_names(leg: acca.Leg) -> tuple[str, str]:
    """(SportyBet market, pick) for a ticket leg, in SportyBet's own words."""
    market, pick = slip.sportybet_name(leg.market)
    if leg.market.startswith(("home_", "away_")):   # SportyBet names team-goals markets after the team
        team = leg.result["home"] if leg.market.startswith("home_") else leg.result["away"]
        market, pick = f"{team} Over/Under", f"{team} {pick.lower()}"
    return market, pick


def show_ticket(ticket: list[acca.Leg], key: str) -> None:
    """Metrics, legs, booking code and add-to-slip for one Bet-of-the-day ticket."""
    s = acca.summary(ticket)
    k = st.columns(4)
    k[0].metric("Total odds", f"{s['odds']:,.2f}", help=f"{s['legs']} legs")
    k[1].metric("Chance it wins", chance_text(s["chance"]), help=f"About 1 in {1 / s['chance']:,.0f}, "
                "by SportyBet's own probabilities")
    k[2].metric("Model's estimate", chance_text(s["model_chance"]),
                help="The model is less accurate than the bookmaker's odds (backtest), so it's a second opinion")
    k[3].metric("Back per ₦100, on average", f"₦{100 * s['expected_return']:.0f}",
                help="Over many tickets like this, by SportyBet's own prices. Below ₦100 means a loss on average.")
    days =pd.Series([leg.result["fx"]["kickoff"].date() for leg in ticket]).value_counts().sort_index()
    if len(days) > 1:
        st.caption("Spread over " + " · ".join(f"{d:%a %d %b} ({n} leg{'s' if n > 1 else ''})"
                                               for d, n in days.items()))
    st.dataframe(pd.DataFrame([{
        "Kick-off": f"{leg.result['fx']['kickoff']:%a %d %b %H:%M}",
        "League": data.LEAGUES.get(leg.result["league"], leg.result["league"]), "Match": leg.match,
        "SportyBet market": pick_names(leg)[0], "Pick": pick_names(leg)[1],
        "Odds": leg.odds, "SportyBet chance": leg.book_prob, "Model chance": leg.model_prob,
        "News": f"✓ {leg.result['news'].source}" if leg.result["news"].found else "✗ checked by you",
    } for leg in ticket]), hide_index=True, width="stretch", column_config={
        "Odds": st.column_config.NumberColumn(format="%.2f"),
        "SportyBet chance": st.column_config.NumberColumn(format="percent"),
        "Model chance": st.column_config.NumberColumn(format="percent")})
    sig = tuple((leg.match, leg.market) for leg in ticket)
    bookings = st.session_state.setdefault("bookings", {})
    b1, b2 = st.columns(2)
    if b1.button("Get SportyBet booking code", type="primary", key=f"book::{key}"):
        try:
            bookings[key] = (sig, sportybet.book(
                [sportybet.selection(leg.result["fx"]["event_id"], leg.market) for leg in ticket]))
        except Exception as exc:
            bookings.pop(key, None)
            st.error(f"SportyBet didn't answer ({exc}). Add the picks above on sportybet.com and press "
                     "**Book Bet** there.")
    if b2.button("Add the legs to the bet slip", key=f"slip::{key}"):
        for leg in ticket:
            r = leg.result
            add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], r["home"], r["away"],
                                 leg.market, leg.odds, leg.model_prob))
    booked = bookings.get(key)
    if booked and booked[0] == sig:
        code = booked[1]
        st.success(f"SportyBet booking code: **{code['code']}** · [open it on SportyBet]({code['url']})")
        st.code(code["code"], language=None)
        if code["unavailable"]:
            st.warning(f"{len(code['unavailable'])} leg(s) were no longer available and were left out: "
                       "check the ticket on SportyBet before you stake.")
        st.caption("Load the code on SportyBet, check the total odds (prices move), set your stake and confirm there.")


def ticket_title(name: str, ticket: list[acca.Leg]) -> str:
    s = acca.summary(ticket)
    return f"{name} · {s['legs']} legs · {s['odds']:,.2f} odds · {chance_text(s['chance'])} chance"


def playable_picks(r: dict) -> list[picks.Pick]:
    """Best picks whose current odds are inside their value range, unless the fixture is withheld."""
    if r["withheld"]:
        return []
    return [p for p in r["picks"] if p.market in r["odds"] and p.odds_range[0] <= r["odds"][p.market] <= p.odds_range[1]]


def match_details(r: dict) -> None:
    """Full read-out for one analysed fixture from the Fixtures tab."""
    pred, fn, home, away = r["pred"], r["news"], r["home"], r["away"]
    probs = pred["probs"]
    headline_metrics(pred)
    if fn.found:
        st.success(f"Team news ({fn.source}): {home} {len(fn.home.out)} out, {len(fn.home.doubtful)} doubtful · "
                   f"{away} {len(fn.away.out)} out, {len(fn.away.doubtful)} doubtful.")
    else:
        st.warning(f"No team news found ({fn.note}), so picks for this match are withheld. Add an API-Football "
                   "key in the sidebar, or check the news yourself in **Match analysis**.")
    for side, team in (("home", home), ("away", away)):
        out, mult = pred["missing"][side]
        if out:
            st.caption(f"{team} missing {', '.join(out)}: expected goals ×{mult:.2f}")

    on_sporty = r["fx"].get("odds_source") == "SportyBet"
    where = "SportyBet" if on_sporty else "Market odds"
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Every market")
        table = pd.DataFrame([{
            "Market": markets.label(mk), "Model": probs[mk], "Fair odds": 1 / probs[mk],
            "Bet at odds": odds_window(mk, probs[mk]), where: r["odds"].get(mk),
        } for mk in ODDS_MARKETS if mk in probs])
        st.dataframe(table, hide_index=True, width="stretch", height=440, column_config={
            "Model": st.column_config.NumberColumn(format="percent"),
            "Fair odds": st.column_config.NumberColumn(format="%.2f"),
            "Bet at odds": st.column_config.TextColumn(
                help="SportyBet odds in this range are a value bet that passes the play-safe rules. "
                     f"Higher odds mean an edge over {safety.MAX_EDGE:.0%}: the model is probably missing news."),
            where: st.column_config.NumberColumn(format="%.2f", help="SportyBet's current odds" if on_sporty
                                                 else "Bookmaker average (football-data.co.uk)"),
        })
        for b, reason in r["skipped"]:
            st.warning(f"Withheld **{markets.label(b.market)}** @ {b.odds:.2f}: {reason}")
        for b in r["bets"]:
            bc1, bc2 = st.columns([5, 1])
            bc1.markdown(f"✅ **{markets.label(b.market)}** @ {b.odds:.2f} "
                         f"({'SportyBet' if on_sporty else 'bookmaker average'}) — model {b.prob:.1%}, "
                         f"edge {b.edge:+.1%}, stake {b.stake_pct:.1%} of bankroll")
            if bc2.button("Add to slip", key=f"fxslip::{r['league']}::{home}::{away}::{b.market}"):
                add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], home, away, b.market, b.odds, b.prob))
    with right:
        best_picks_table(r["picks"], r["withheld"], r["odds"], r["fx"].get("odds_source"))
        score_heatmap(pred, home, away)
    form_and_h2h(r["league"], home, away, r["fx"]["kickoff"].date())


# ---------------------------------------------------------------- sidebar

settings = load_settings()
BETS = user_dir() / "bets.csv"
NEWS_KEY = news.api_key() or ""   # set by the owner only (API_FOOTBALL_KEY), never in the page
if "refresh" not in st.session_state:
    st.session_state.refresh = 0

with st.sidebar:
    st.title("⚽ Football Predictor")
    if SHARED:
        st.caption(f"Signed in as **{current_user()}**")
    league = st.selectbox("League", list(data.LEAGUES), format_func=lambda c: f"{data.LEAGUES[c]} ({c})")
    bankroll = st.number_input("Bankroll", min_value=0.0, value=float(settings.get("bankroll", 50000)),
                               step=1000.0, help="Your total betting money. Stakes are a % of this.")
    if bankroll != settings.get("bankroll"):
        settings["bankroll"] = bankroll
        save_settings(settings)
    if not SHARED and st.button("Refresh data", help="Download the latest results, xG and fixtures"):
        st.session_state.refresh += 1
        st.cache_data.clear()
        st.cache_resource.clear()
        xg.clear_cache()
    st.caption(f"Value rules: edge ≥ {value.MIN_EDGE:.0%}, odds ≤ {value.MAX_ODDS}, "
               f"stake = ¼ Kelly capped at {value.MAX_STAKE:.0%} of bankroll.")
    st.caption("Bet only what you can afford to lose. 18+.")

try:
    model_today = league_model(league, date.today(), st.session_state.refresh)
except Exception as exc:  # no data reachable for this league
    st.error(f"Could not load {data.LEAGUES[league]} data: {exc}")
    st.stop()

last_result = model_today.history["date"].max()
stale_days = (pd.Timestamp.today() - last_result).days
if stale_days > predict.STALE_DAYS:
    st.warning(f"Latest {data.LEAGUES[league]} result in the data is **{last_result:%d %b %Y}** "
               f"({stale_days} days ago). Predictions ignore everything since then. "
               "If the season is running, press **Refresh data** or check your connection to football-data.co.uk.")

tab_match, tab_list, tab_botd, tab_code, tab_results, tab_slip, tab_bets, tab_ratings, tab_report = st.tabs(
    ["Match analysis", "Fixtures", "Bet of the day", "Check a code", "Results", "Bet slip", "Bet tracker",
     "Team ratings", "Model report"])


# ---------------------------------------------------------------- match analysis

with tab_match:
    teams_list = current_teams(model_today)
    fx_here, _ = upcoming_fixtures((league,), PICKER_DAYS, date.today(), st.session_state.refresh)
    fx_here = fx_here[(fx_here["kickoff"] > pd.Timestamp.now()) & fx_here["home"].isin(teams_list)
                      & fx_here["away"].isin(teams_list)].reset_index(drop=True)
    sb_notes: list[str] = []
    sb_here = sportybet_odds((league,), {league: teams_list}, sb_notes)
    now_here = pd.Timestamp.now()
    fx_here = sportybet.add_unlisted(sportybet.merge_odds(fx_here, sb_here), sb_here, now_here,
                                     now_here.normalize() + pd.Timedelta(days=PICKER_DAYS))
    for note in sb_notes:
        st.caption(note)
    fx_labels = [f"{k:%a %d %b, %H:%M} · {h} v {a}"
                 for k, h, a in zip(fx_here["kickoff"], fx_here["home"], fx_here["away"])]
    pick = st.selectbox("Fixture", range(len(fx_labels) + 1),
                        format_func=lambda i: fx_labels[i] if i < len(fx_labels) else "Other match: pick the teams",
                        help=f"{data.LEAGUES[league]} matches in the next {PICKER_DAYS} days, kick-off in your "
                             "time. Change the league in the sidebar.")
    fixture = fx_here.iloc[pick] if pick < len(fx_labels) else None
    book_odds = fixture_odds(fixture)
    on_sporty = fixture is not None and fixture.get("odds_source") == "SportyBet"
    refs = ["(unknown)"] + sorted(model_today.referee_factor)
    c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.6])
    if fixture is None:
        home = c1.selectbox("Home team", teams_list, index=0)
        away = c2.selectbox("Away team", teams_list, index=min(1, len(teams_list) - 1))
        match_day = c3.date_input("Match date", value=date.today())
        ref_index = 0
    else:
        home, away, match_day = fixture["home"], fixture["away"], fixture["kickoff"].date()
        c1.text_input("Home team", home, disabled=True)
        c2.text_input("Away team", away, disabled=True)
        c3.text_input("Kick-off", f"{fixture['kickoff']:%d %b, %H:%M}", disabled=True)
        ref_index = refs.index(fixture["referee"]) if fixture["referee"] in refs else 0
    referee = c4.selectbox("Referee", refs, index=ref_index,
                           help="Only some leagues publish referees. Affects cards.")

    season_now = int(model_today.history["season"].max())
    fn = fixture_news(league, season_now, f"{match_day:%Y-%m-%d}", home, away,
                      tuple(model_today.goals.teams), NEWS_KEY)
    if fn.found:
        st.success(f"Team news checked ({fn.source}): {home} {len(fn.home.out)} out, {len(fn.home.doubtful)} doubtful · "
                   f"{away} {len(fn.away.out)} out, {len(fn.away.doubtful)} doubtful. "
                   "Players who are out are applied below.")
        nf = news.team_news_frame(fn, home, away)
        if not nf.empty:
            with st.expander("Injuries and suspensions"):
                st.dataframe(nf, hide_index=True, width="stretch")
        manual_ok = False
    else:
        st.warning(f"No team news found ({fn.note}). Picks for this match are **withheld** until news is "
                   "available. Add an API-Football key in the sidebar, or check the news yourself.")
        manual_ok = st.checkbox("I've checked the team news myself and entered missing players below")

    with st.expander("Team news (missing players, rotation)", expanded=fn.found):
        st.caption("Pick players who are **out**. Each one lowers their team's expected goals by that player's share "
                   "of the team's attack (their xG + chances created per 90, from Understat), half-covered "
                   "by the replacement. Use the extra slider for anything else, e.g. heavy rotation 0.90, "
                   "or raise a team to 1.05–1.10 when the *opponent* is missing key defenders.")
        n1, n2 = st.columns(2)
        adj, all_shares = {}, {}
        for col, team, tn in ((n1, home, fn.home), (n2, away, fn.away)):
            shares = squad_shares(league, team, season_now, tuple(model_today.goals.teams)) \
                if league in absences_leagues else pd.DataFrame(columns=["player", "share"])
            if shares.empty:
                col.caption(f"No player data for {team} (Understat covers the top 5 leagues).")
                out = []
            else:
                label = {r.player: f"{r.player} ({r.share:.0%} of attack)" for r in shares.itertuples()}
                news_out = absences.resolve_players(tn.out, shares)[0]
                out = col.multiselect(f"{team}: missing players", list(shares["player"]), default=news_out,
                                      format_func=label.get, key=f"out::{league}::{team}::{match_day}::{fn.source}")
            all_shares[team] = shares
            auto = absences.multiplier(shares, out)
            extra = col.slider(f"{team}: extra adjustment", 0.70, 1.30, 1.00, 0.05, key=f"adj::{league}::{team}")
            adj[team] = auto * extra
            col.caption(f"{team} expected goals ×{adj[team]:.2f}")
        home_adj, away_adj = round(adj[home], 3), round(adj[away], 3)

    if home == away:
        st.info("Pick two different teams.")
        st.stop()

    lm = league_model(league, match_day, st.session_state.refresh)
    pred = lm.predict(home, away, None if referee == "(unknown)" else referee, home_adj, away_adj)
    probs = pred["probs"]
    headline_metrics(pred)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Model vs. your odds")
        st.caption(("**Your odds** start at SportyBet's current prices; change any to your own bookmaker's. "
                    if on_sporty else "Type the odds your bookmaker (e.g. SportyBet) offers in the **Your odds** "
                                      "column. ")
                   + "Fair odds = the price at which a bet breaks even. **Bet at odds** = the range where a bet "
                     "is value and passes the play-safe rules."
                   + (" **Market odds** = bookmaker average; SportyBet often pays a little less."
                      if book_odds and not on_sporty else ""))
        # The editor's input must stay identical between reruns or Streamlit drops
        # typed values, so build it once per match setup and carry odds across.
        saved = st.session_state.setdefault(f"odds::{league}::{home}::{away}", {})
        editor_key = (f"editor::{league}::{home}::{away}::{match_day}::{referee}::{home_adj}::{away_adj}"
                      f"::{len(book_odds)}")
        if f"base::{editor_key}" not in st.session_state:
            st.session_state[f"base::{editor_key}"] = pd.DataFrame([{
                "market": mk, "Market": markets.label(mk), "Model": probs[mk], "Fair odds": 1 / probs[mk],
                "Bet at odds": odds_window(mk, probs[mk]), "Market odds": book_odds.get(mk, np.nan),
                "Your odds": saved.get(mk, book_odds.get(mk, np.nan) if on_sporty else np.nan),
            } for mk in ODDS_MARKETS if mk in probs])
        edited = st.data_editor(
            st.session_state[f"base::{editor_key}"], hide_index=True, width="stretch", height=440,
            column_order=["Market", "Model", "Fair odds", "Bet at odds"]
                         + (["Market odds"] if book_odds and not on_sporty else []) + ["Your odds"],
            disabled=["Market", "Model", "Fair odds", "Bet at odds", "Market odds"],
            column_config={
                "Model": st.column_config.NumberColumn(format="percent", help="Calibrated model probability"),
                "Fair odds": st.column_config.NumberColumn(format="%.2f"),
                "Bet at odds": st.column_config.TextColumn(
                    help=f"Odds above this range mean an edge over {safety.MAX_EDGE:.0%}: "
                         "the model is probably missing news, so the pick is withheld."),
                "Market odds": st.column_config.NumberColumn(format="%.2f",
                                                             help="Bookmaker average (football-data.co.uk)"),
                "Your odds": st.column_config.NumberColumn(min_value=1.01, max_value=100.0, step=0.01, format="%.2f"),
            },
            key=editor_key)
        odds = {mk: float(o) for mk, o in zip(edited["market"], edited["Your odds"]) if pd.notna(o)}
        saved.clear()
        saved.update(odds)
        book = value.market_probs(odds)
        bets, skipped = safety.screen(value.find_value(probs, odds), fn, all_shares[home], all_shares[away], manual_ok)
        withheld = {b.market for b, _ in skipped}

        if odds:
            check = pd.DataFrame([{
                "Market": markets.label(mk), "Your odds": o, "Model": probs[mk],
                "Bookmaker": book.get(mk), "Edge": 100 * value.edge(probs[mk], o),
                "Verdict": "⛔ Withheld (see below)" if mk in withheld else verdict(mk, probs[mk], o, bankroll),
            } for mk, o in odds.items()])
            st.dataframe(check, hide_index=True, width="stretch", column_config={
                "Your odds": st.column_config.NumberColumn(format="%.2f"),
                "Model": st.column_config.NumberColumn(format="percent"),
                "Bookmaker": st.column_config.NumberColumn(
                    format="percent", help="Bookmaker's own probability with its margin removed "
                                           "(needs odds for every outcome of that market)"),
                "Edge": st.column_config.NumberColumn(format="%+.1f%%", help="Expected return per unit staked"),
                "Verdict": st.column_config.TextColumn(width="medium"),
            }, column_order=["Market", "Your odds", "Model", "Bookmaker", "Edge", "Verdict"])

        for b, reason in skipped:
            st.warning(f"Withheld **{markets.label(b.market)}** @ {b.odds:.2f}: {reason}")
        if bets:
            st.success(f"{len(bets)} value bet(s) found")
            for b in bets:
                bc1, bc2, bc3 = st.columns([4, 1, 1])
                stake_amt = round(b.stake_pct * bankroll, 2)
                bc1.markdown(f"**{markets.label(b.market)}** @ {b.odds:.2f} — model {b.prob:.1%}, "
                             f"edge {b.edge:+.1%}, stake **{stake_amt:,.0f}** ({b.stake_pct:.1%})")
                if bc2.button("Log bet", key=f"log::{league}::{home}::{away}::{b.market}"):
                    tracker.add({"match_date": str(match_day), "league": league, "home": home, "away": away,
                                 "market": b.market, "odds": b.odds, "stake": stake_amt,
                                 "model_prob": round(b.prob, 4), "edge": round(b.edge, 4)}, BETS)
                    st.toast(f"Logged {markets.label(b.market)} @ {b.odds}")
                if bc3.button("Add to slip", key=f"slip::{league}::{home}::{away}::{b.market}"):
                    add_to_slip(slip.Leg(str(match_day), league, home, away, b.market, b.odds, b.prob))
        elif odds and not skipped:
            st.info("No value at these odds. Not betting is the right call.")

    with right:
        best_picks_table(picks.best_picks(probs),
                         safety.fixture_reason(fn, all_shares[home], all_shares[away], manual_ok), book_odds,
                         "SportyBet" if on_sporty else None)
        score_heatmap(pred, home, away)
    form_and_h2h(league, home, away, match_day)


# ---------------------------------------------------------------- fixtures

with tab_list:
    st.subheader("Upcoming fixtures")
    f1, f2 = st.columns([4, 1])
    fx_leagues = f1.multiselect("Competitions", list(data.LEAGUES), default=data.TOP5,
                                format_func=lambda c: data.LEAGUES[c])
    fx_days = f2.selectbox("When", [1, 2, 3, 5, 7], index=2,
                           format_func=lambda d: "Today" if d == 1 else f"Next {d} days")
    if not fx_leagues:
        st.info("Pick at least one competition.")
    else:
        upcoming, fx_notes = analyse_upcoming(tuple(sorted(fx_leagues)), fx_days, date.today(),
                                              st.session_state.refresh, NEWS_KEY)
        upcoming = [r for r in upcoming if r["fx"]["kickoff"] > pd.Timestamp.now()]
        for note in fx_notes:
            st.warning(note)
        if not upcoming:
            st.info("No matches in that window. football-data.co.uk posts fixtures a few days ahead, and "
                    "Understat has the full schedule for the top 5 leagues.")
        else:
            st.caption("Kick-off in your time zone. **Odds** are SportyBet's current prices where it lists the "
                       "match, otherwise the bookmaker average from football-data.co.uk. **Top pick** = the model's "
                       "most likely outcome worth playing, with its odds (✅ = inside the value range; ⛔ = withheld "
                       "by the play-safe rules). **Value** uses those odds and the play-safe rules. "
                       "Pick a match below the tables for the full analysis.")
            st.warning("Backtest, Oct 2026: on 2,158 past matches the model hadn't seen, its value bets lost 8% at "
                       "bookmaker closing odds, and its top picks won 74% against 76% expected. The probabilities are "
                       "honest; the edge over bookmakers isn't proven. Stake small or not at all until your tracked "
                       "bets say otherwise.")
            rows = []
            for r in upcoming:
                p, o = r["pred"]["probs"], r["odds"]
                if r["bets"]:
                    verdict_txt = ", ".join(f"✅ {markets.label(b.market)} @{b.odds:.2f} ({b.edge:+.0%})"
                                            for b in r["bets"])
                elif r["skipped"]:
                    verdict_txt = "Withheld: " + r["skipped"][0][1].split(" (")[0]
                else:
                    verdict_txt = "–" if o else "No odds yet"
                rows.append({
                    "day": r["fx"]["kickoff"].normalize(), "Time": f"{r['fx']['kickoff']:%H:%M}",
                    "League": data.LEAGUES.get(r["league"], r["league"]), "Match": f"{r['home']} v {r['away']}",
                    "xG": f"{r['pred']['xg_home']:.1f}–{r['pred']['xg_away']:.1f}",
                    "1": p["1"], "X": p["X"], "2": p["2"], "Over 2.5": p["over_2.5"], "BTTS": p["btts_yes"],
                    "Odds 1·X·2": " · ".join(f"{o[k]:.2f}" for k in ("1", "X", "2"))
                                  if all(k in o for k in ("1", "X", "2")) else "–",
                    "Odds from": {"SportyBet": "SportyBet", "Bookmaker average": "Average"}.get(
                        r["fx"].get("odds_source"), "–"),
                    "Top pick": top_pick_text(r),
                    "Value": verdict_txt,
                    "News": f"✓ {r['news'].source}" if r["news"].found else "✗ none",
                })
            table = pd.DataFrame(rows)
            pcfg = {c: st.column_config.NumberColumn(format="percent")
                    for c in ("1", "X", "2", "Over 2.5", "BTTS")}
            pcfg["Top pick"] = st.column_config.TextColumn(width="medium")
            pcfg["Value"] = st.column_config.TextColumn(width="large")
            for day, g in table.groupby("day", sort=True):
                st.markdown(f"**{day_label(day)}** · {len(g)} matches")
                st.dataframe(g.drop(columns="day"), hide_index=True, width="stretch", column_config=pcfg)

            all_bets = [(r, b) for r in upcoming for b in r["bets"]]
            playable = [(r, p) for r in upcoming for p in playable_picks(r)]
            d1, d3, d2 = st.columns(3)
            if all_bets and d1.button(f"Add all {len(all_bets)} value bets to the slip", type="primary",
                                      key="fx_add_all"):
                for r, b in all_bets:
                    add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], r["home"], r["away"],
                                         b.market, b.odds, b.prob))
            if playable and d3.button(f"Add {len(playable)} playable picks to the slip", key="fx_add_picks",
                                      help="Best picks whose current odds are inside their value range, "
                                           "from matches that pass the play-safe rules"):
                for r, p in playable:
                    add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], r["home"], r["away"],
                                         p.market, r["odds"][p.market], p.prob))
            d2.download_button("Download all market probabilities",
                               predict.to_table(upcoming).to_csv(index=False).encode(),
                               "upcoming_predictions.csv", "text/csv", key="fx_download")

            st.divider()
            st.subheader("Match details")
            names = [f"{r['fx']['kickoff']:%a %d %b, %H:%M} · {data.LEAGUES.get(r['league'], r['league'])} · "
                     f"{r['home']} v {r['away']}" for r in upcoming]
            chosen = st.selectbox("Match", range(len(upcoming)), format_func=names.__getitem__)
            match_details(upcoming[chosen])

    with st.expander("Analyse your own list with your bookmaker's odds (CSV)"):
        st.caption("Upload a CSV with columns `league, date, home, away` and optionally `referee`, "
                   "`home_missing` / `away_missing` (players out, e.g. `Haaland; De Bruyne`), `home_adj`, "
                   "`away_adj` and odds columns like `odds:1`, `odds:over_2.5`, `odds:btts_yes`.")
        example = (ROOT / "examples" / "fixtures_example.csv").read_bytes()
        st.download_button("Download template", example, "fixtures_template.csv", "text/csv")
        upload = st.file_uploader("Fixtures CSV", type="csv")
        if upload is not None:
            fx_csv = predict.read_fixtures(upload)
            all_leagues = tuple(sorted(fx_csv["league"].unique()))
            with st.spinner("Predicting…", show_time=True):
                results, warnings = predict.analyse(fx_csv, load_matches(all_leagues, st.session_state.refresh))
            for w in warnings:
                st.warning(w)
            if results:
                summary = pd.DataFrame([{
                    "Date": r["fx"]["date"].date(), "League": r["league"],
                    "Match": f"{r['home']} v {r['away']}",
                    "xG": f"{r['pred']['xg_home']:.2f}–{r['pred']['xg_away']:.2f}",
                    "Home": r["pred"]["probs"]["1"], "Draw": r["pred"]["probs"]["X"],
                    "Away": r["pred"]["probs"]["2"],
                    "Over 1.5": r["pred"]["probs"]["over_1.5"], "Over 2.5": r["pred"]["probs"]["over_2.5"],
                    "BTTS": r["pred"]["probs"]["btts_yes"],
                    "Value bets": ", ".join(f"{markets.label(b.market)} @{b.odds} ({b.edge:+.0%}, "
                                            f"stake {b.stake_pct * bankroll:,.0f})" for b in r["bets"]) or "–",
                    "Withheld": "; ".join(f"{markets.label(b.market)}: {why}" for b, why in r["skipped"]) or "–",
                } for r in results])
                pcols = ["Home", "Draw", "Away", "Over 1.5", "Over 2.5", "BTTS"]
                st.dataframe(summary, hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="percent") for c in pcols})
                csv_bets = [(r, b) for r in results for b in r["bets"]]
                d1, d2 = st.columns(2)
                if csv_bets and d1.button(f"Add all {len(csv_bets)} value bets to the slip", type="primary",
                                          key="csv_add_all"):
                    for r, b in csv_bets:
                        add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], r["home"], r["away"],
                                             b.market, b.odds, b.prob))
                d2.download_button("Download all market probabilities",
                                   predict.to_table(results).to_csv(index=False).encode(),
                                   "predictions.csv", "text/csv", key="csv_download")


# ---------------------------------------------------------------- bet of the day

with tab_botd:
    st.subheader("Bet of the day")
    botd_mode = st.radio("Ticket type", ["Daily", "Mega odds"], horizontal=True, key="botd_mode",
                         captions=["Today or tomorrow", f"Big odds from up to {MEGA_DAYS} days of matches"])
    st.caption("Accumulators from every league SportyBet and the model both cover. Each leg must be likely by "
               "**both** SportyBet's own odds and the model, pass the play-safe rules, and come from a different "
               "match. Among those, each ticket is the combination with the highest chance that every leg wins, "
               "judged by SportyBet's odds (they predicted results better than the model in the backtest). A few "
               "well-priced legs beat many very short ones: every leg adds the bookmaker's margin.")
    g1, g2 = st.columns(2)
    if botd_mode == "Daily":
        botd_day = g1.selectbox("Day", [0, 1], format_func=lambda d: "Today" if d == 0 else "Tomorrow",
                                key="botd_day")
    else:
        mega_days = g1.slider("Days ahead", 2, MEGA_DAYS, 7, key="mega_days",
                              help="SportyBet lists matches about a week ahead, so later days usually add nothing yet")
    botd_min = g2.slider("Each leg at least", 0.50, 0.85, 0.65, 0.05, format="%.2f", key="botd_min",
                         help="Minimum chance per leg, by both SportyBet's odds and the model")
    sb_leagues = [lg for lg in data.LEAGUES if lg in sportybet.TOURNAMENTS]
    botd_leagues = st.multiselect("Competitions", sb_leagues, default=sb_leagues,
                                  format_func=lambda c: data.LEAGUES[c], key="botd_leagues")
    botd_news = st.checkbox("I've checked the team news for matches no news source covers (marked ✗)",
                            key="botd_news",
                            help="The play-safe rule is no news, no bet. Free team news only covers the Premier "
                                 "League, so without this the ticket can only use Premier League matches.")
    botd_notes: list[str] = []
    if botd_leagues and botd_mode == "Mega odds":
        everything, botd_notes = analyse_upcoming(tuple(sorted(botd_leagues)), MEGA_DAYS, date.today(),
                                                  st.session_state.refresh, NEWS_KEY, sportybet_only=True)
        now = pd.Timestamp.now()
        window = [r for r in everything
                  if now < r["fx"]["kickoff"] < now.normalize() + pd.Timedelta(days=mega_days)]
        pool = acca.candidates(window, botd_min, botd_news)
        match_days = sorted({r["fx"]["kickoff"].date() for r in window})
        st.caption(f"{len(window)} matches on SportyBet in the next {mega_days} days, on {len(match_days)} match days"
                   + (f" (the last on {match_days[-1]:%a %d %b})" if match_days else "")
                   + f"; {len(pool)} possible legs from {len({leg.match for leg in pool})} matches. SportyBet lists "
                   "matches about a week ahead.")
        mega_target = st.number_input("Total odds", min_value=50.0, max_value=100_000.0, value=1000.0, step=500.0,
                                      key="mega_target")
        st.warning(f"Big odds mean a small chance, whichever legs are picked. Even if SportyBet's prices were perfectly "
                   f"fair, a {mega_target:,.0f}-odds ticket would win 1 time in {mega_target:,.0f}, and every leg's "
                   "margin makes it rarer still. The builder finds the least-bad ticket: the one with the highest "
                   "chance for those odds. On average you get back far less than you stake (see **Back per ₦100**). "
                   "Treat it like a lottery ticket and stake only what you'd be fine losing every time, at most "
                   f"{slip.ACCA_MAX_STAKE:.0%} of your bankroll (₦{bankroll * slip.ACCA_MAX_STAKE:,.0f}).")
        tickets = acca.alternatives(pool, mega_target, max_legs=acca.MEGA_MAX_LEGS)
        if not tickets:
            st.warning(f"No ticket reaches {mega_target:,.0f} odds with these settings (the most these legs can make is "
                       f"about {acca.reach(pool, acca.MEGA_MAX_LEGS):,.0f}). Try lowering the per-leg minimum or the "
                       "total odds, more days or more competitions"
                       + ("" if botd_news else ", or ticking the team-news box") + ".")
        for i, ticket in enumerate(tickets):
            with st.expander(ticket_title("Mega ticket" if i == 0 else f"Alternative {i + 1}", ticket),
                             expanded=i == 0):
                show_ticket(ticket, f"mega-{i}")
        if tickets:
            st.caption(f"Tickets use up to {acca.MEGA_MAX_LEGS} legs and never share a match. SportyBet may cap how "
                       "many selections one ticket can hold: if booking fails, lower the total odds.")
    elif botd_leagues:
        day = date.today() + timedelta(days=botd_day)
        everything, botd_notes = analyse_upcoming(tuple(sorted(botd_leagues)), 2, date.today(),
                                                  st.session_state.refresh, NEWS_KEY)
        todays = [r for r in everything
                  if r["fx"]["kickoff"].date() == day and r["fx"]["kickoff"] > pd.Timestamp.now()]
        pool = acca.candidates(todays, botd_min, botd_news)
        listed = sum(r["fx"].get("odds_source") == "SportyBet" for r in todays)
        st.caption(f"{len(todays)} matches {'today' if botd_day == 0 else 'tomorrow'} not yet started, {listed} on "
                   f"SportyBet; {len(pool)} possible legs from {len({leg.match for leg in pool})} matches.")
        st.warning("A ticket loses if any one leg loses, and by SportyBet's own prices every accumulator returns less "
                   "than you stake on average (each ticket shows how much). Treat these as entertainment and keep "
                   f"each stake to at most {slip.ACCA_MAX_STAKE:.0%} of your bankroll "
                   f"(₦{bankroll * slip.ACCA_MAX_STAKE:,.0f}).")

        st.markdown("#### Best from all leagues")
        botd_target = st.number_input("Total odds", min_value=2.0, max_value=1000.0, value=10.0, step=1.0,
                                      key="botd_target")
        tickets = acca.alternatives(pool, botd_target)
        if not tickets:
            st.warning(f"No ticket reaches {botd_target:,.0f} odds with these settings (the most these legs can make "
                       f"is about {acca.reach(pool):,.1f}). Try lowering the per-leg minimum or the total odds, "
                       "another day, **Mega odds** (several days), more competitions"
                       + ("" if botd_news else ", or ticking the team-news box") + ".")
        for i, ticket in enumerate(tickets):
            with st.expander(ticket_title("Best ticket" if i == 0 else f"Alternative {i + 1}", ticket),
                             expanded=i == 0):
                show_ticket(ticket, f"all-{i}")
        if 0 < len(tickets) < 3:
            st.caption(f"Only {len(tickets)} ticket(s): the matches left can't make another {botd_target:.0f}-odds "
                       "ticket without reusing a match.")

        st.markdown("#### One per league")
        league_target = st.number_input("Total odds per league", min_value=1.5, max_value=20.0,
                                        value=acca.LEAGUE_TARGET, step=0.5, key="botd_league_target")
        per_league = acca.by_league(pool, league_target)
        for lg in [lg for lg in data.LEAGUES if lg in per_league]:
            with st.expander(ticket_title(data.LEAGUES[lg], per_league[lg])):
                show_ticket(per_league[lg], f"league-{lg}")
        no_bet = [data.LEAGUES[lg] for lg in data.LEAGUES
                  if lg in {r["league"] for r in todays} and lg not in per_league]
        if no_bet:
            st.caption("No solid bet today: " + ", ".join(no_bet) + "."
                       + ("" if botd_news else " Without the team-news box only the Premier League can qualify."))
    for note in botd_notes:
        st.caption(note)


# ---------------------------------------------------------------- check a code

with tab_code:
    st.subheader("Check a booking code")
    st.caption("Paste any SportyBet booking code. The app reads its legs (no login), shows what SportyBet keeps on "
               "each one and flags the weak ones, then rebuilds the ticket for the highest chance at your total odds.")
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    code_in = c1.text_input("SportyBet booking code", key="code_input", placeholder="e.g. NMNQPY")
    if c2.button("Load", type="primary", key="code_load") and code_in.strip():
        st.session_state.code_loaded = code_in.strip().upper()
    code = st.session_state.get("code_loaded")
    code_legs, code_gone, code_notes = [], 0, []
    if code:
        try:
            code_legs, code_gone = booking_code(code, st.session_state.refresh)
        except Exception as exc:
            st.error(f"SportyBet couldn't load **{code}** ({exc}). Check the code and try again.")
    if code_legs:
        code_leagues = tuple(sorted(lg for lg in data.LEAGUES if lg in sportybet.TOURNAMENTS))
        code_all, code_notes = analyse_upcoming(code_leagues, MEGA_DAYS, date.today(), st.session_state.refresh,
                                                NEWS_KEY, sportybet_only=True)
        code_by_event = {r["fx"].get("event_id"): r for r in code_all if r["fx"].get("event_id")}
        code_news = st.checkbox("I've checked the team news for matches no news source covers", key="code_news",
                                help="The play-safe rule is no news, no bet. Free team news only covers the Premier "
                                     "League, so without this other legs count as a problem and can't be added.")
        check = doctor.analyse(code_legs, code_by_event, code_news)
        before = doctor.summary([leg["odds"] for leg in code_legs], check["book_prob"].tolist())
        k = st.columns(4)
        k[0].metric("Total odds", f"{before['odds']:,.2f}", help=f"{before['legs']} legs")
        k[1].metric("Chance it wins", chance_text(before["chance"]),
                    help=f"About 1 in {1 / before['chance']:,.0f}, by SportyBet's own probabilities")
        k[2].metric("Back per ₦100, on average", f"₦{100 * before['expected_return']:.0f}",
                    help="Over many tickets like this, by SportyBet's own numbers. Below ₦100 means a loss on average.")
        k[3].metric("Legs with problems", f"{sum(bool(p) for p in check['problems'])} of {len(code_legs)}")
        if code_gone:
            st.warning(f"{code_gone} selection(s) on this code are no longer offered by SportyBet and aren't shown.")
        legs_table = pd.DataFrame({
            "Keep": doctor.default_keep(check),
            "Kick-off": [f"{leg['kickoff']:%a %d %b %H:%M}" for leg in code_legs],
            "Competition": [leg["tournament"] for leg in code_legs],
            "Match": [f"{leg['sb_home']} v {leg['sb_away']}" for leg in code_legs],
            "Pick": [leg["label"] for leg in code_legs],
            "Odds": [leg["odds"] for leg in code_legs],
            "SportyBet chance": check["book_prob"],
            "SportyBet keeps": check["margin"],
            "Model chance": check["model_prob"],
            "Problems": ["; ".join(p) or "–" for p in check["problems"]],
            "Notes": ["; ".join(n) for n in check["notes"]],
        })
        edited = st.data_editor(
            legs_table, hide_index=True, width="stretch", key=f"code_editor::{code}::{code_news}",
            disabled=[c for c in legs_table.columns if c != "Keep"], column_config={
                "Keep": st.column_config.CheckboxColumn(help="Untick a leg to let the app replace it"),
                "Odds": st.column_config.NumberColumn(format="%.2f"),
                "SportyBet chance": st.column_config.NumberColumn(format="percent"),
                "SportyBet keeps": st.column_config.NumberColumn(
                    format="percent", help="1 − odds × SportyBet's own probability: the margin on this leg"),
                "Model chance": st.column_config.NumberColumn(format="percent")})
        code_keep = edited["Keep"].tolist()

        st.markdown("#### Improved ticket")
        i1, i2, i3 = st.columns(3)
        code_target = i1.number_input("Total odds to aim for", min_value=1.1, max_value=100_000.0,
                                      value=float(round(before["odds"], 2)), key=f"code_target::{code}")
        code_min = i2.slider("Each new leg at least", 0.50, 0.85, 0.65, 0.05, format="%.2f", key="code_min",
                             help="Minimum chance per new leg, by both SportyBet's probabilities and the model")
        code_today = date.today()
        code_last = max(max(leg["kickoff"] for leg in code_legs).date(), code_today)
        code_until = i3.date_input("New legs from matches up to",
                                   value=min(code_last, code_today + timedelta(days=MEGA_DAYS)),
                                   min_value=code_today, max_value=code_today + timedelta(days=MEGA_DAYS),
                                   key=f"code_until::{code}",
                                   help="The code's last kick-off by default, so the new ticket settles no later")
        if st.toggle("Replace every leg: the best ticket at these odds", key=f"code_fresh::{code}",
                     help="Ignore the Keep column and rebuild the whole ticket from the matches below"):
            code_keep = [False] * len(code_legs)
        code_now = pd.Timestamp.now()
        code_window = [r for r in code_all
                       if code_now < r["fx"]["kickoff"] < pd.Timestamp(code_until) + pd.Timedelta(days=1)]
        code_pool = acca.candidates(code_window, code_min, code_news)
        st.caption("Improving means the highest chance at your total odds, by SportyBet's own probabilities: the legs "
                   "you keep stay, and the rest is rebuilt from legs that SportyBet and the model both rate at least "
                   "that likely and that pass the play-safe rules. Every leg still carries a margin, so the ticket "
                   "returns less than you stake on average unless a leg is genuinely mispriced.")
        improved = doctor.improve(code_legs, code_keep, code_pool, code_target)
        if improved is None:
            room = acca.reach(code_pool, max(acca.MEGA_MAX_LEGS - sum(code_keep), 0))
            st.warning(f"No ticket reaches {code_target:,.0f} odds from the legs you kept plus these matches (new legs "
                       f"can add about ×{room:,.0f} at most). Lower the total odds or the per-leg minimum, keep more "
                       "legs, allow later matches" + ("" if code_news else ", or tick the team-news box") + ".")
        else:
            kept, fill = improved
            after = doctor.summary([leg["odds"] for leg in kept] + [leg.odds for leg in fill],
                                   [p for p, keep in zip(check["book_prob"], code_keep) if keep]
                                   + [leg.book_prob for leg in fill])
            a = st.columns(4)
            a[0].metric("Total odds", f"{after['odds']:,.2f}", delta=f"{after['odds'] - before['odds']:+,.2f}",
                        delta_color="off")
            a[1].metric("Chance it wins", chance_text(after["chance"]),
                        delta=f"{after['chance'] / before['chance'] - 1:+.0%} vs the code")
            a[2].metric("Back per ₦100, on average", f"₦{100 * after['expected_return']:.0f}",
                        delta=round(100 * (after["expected_return"] - before["expected_return"])))
            a[3].metric("Legs", f"{after['legs']}", help=f"{len(kept)} kept from the code, {len(fill)} new")
            new_rows = [{"": "Kept", "when": leg["kickoff"], "Competition": leg["tournament"],
                         "Match": f"{leg['sb_home']} v {leg['sb_away']}", "Pick": leg["label"], "Odds": leg["odds"],
                         "SportyBet chance": doctor.leg_prob(leg)} for leg in kept]
            new_rows += [{"": "New", "when": leg.result["fx"]["kickoff"],
                          "Competition": data.LEAGUES.get(leg.result["league"], leg.result["league"]),
                          "Match": leg.match, "Pick": " · ".join(pick_names(leg)), "Odds": leg.odds,
                          "SportyBet chance": leg.book_prob} for leg in fill]
            new_table = pd.DataFrame(new_rows).sort_values("when")
            new_table.insert(1, "Kick-off", [f"{t:%a %d %b %H:%M}" for t in new_table["when"]])
            st.dataframe(new_table.drop(columns="when"), hide_index=True, width="stretch", column_config={
                "Odds": st.column_config.NumberColumn(format="%.2f"),
                "SportyBet chance": st.column_config.NumberColumn(format="percent")})
            code_sig = (code, tuple(leg["event_id"] for leg in kept),
                        tuple((leg.result["fx"]["event_id"], leg.market) for leg in fill))
            if st.button("Get new booking code", type="primary", key="code_book"):
                try:
                    st.session_state.code_booking = (code_sig, sportybet.book(
                        [sportybet.raw_selection(leg) for leg in kept]
                        + [sportybet.selection(leg.result["fx"]["event_id"], leg.market) for leg in fill]))
                except Exception as exc:
                    st.session_state.pop("code_booking", None)
                    st.error(f"SportyBet didn't answer ({exc}). Add the picks above on sportybet.com and press "
                             "**Book Bet** there.")
            booked = st.session_state.get("code_booking")
            if booked and booked[0] == code_sig:
                st.success(f"New SportyBet booking code: **{booked[1]['code']}** · "
                           f"[open it on SportyBet]({booked[1]['url']})")
                st.code(booked[1]["code"], language=None)
                if booked[1]["unavailable"]:
                    st.warning(f"{len(booked[1]['unavailable'])} leg(s) were no longer available and were left out: "
                               "check the ticket on SportyBet before you stake.")
                st.caption("Load the code on SportyBet, check the total odds (prices move), set your stake and "
                           "confirm there.")
    for note in code_notes:
        st.caption(note)


# ---------------------------------------------------------------- results

with tab_results:
    st.subheader("How did the picks do?")
    st.caption("Predictions are rebuilt from results before the chosen day, so the model never sees that day's "
               "scores (team news is as of now). Scores from ESPN, minutes after full time.")
    r1, r2 = st.columns([1, 4])
    review_date = r1.date_input("Day", value=date.today(), max_value=date.today(), key="review_date")
    review_leagues = r2.multiselect("Competitions", [lg for lg in data.LEAGUES if lg in review.ESPN_SLUGS],
                                    default=data.TOP5, format_func=lambda c: data.LEAGUES[c], key="review_leagues")
    if review_leagues:
        try:
            m_table, p_table, rs, pending = review_day(tuple(sorted(review_leagues)), review_date,
                                                       st.session_state.refresh)
        except Exception as exc:
            st.error(f"Couldn't get the scores: {exc}")
            m_table, rs, pending = pd.DataFrame(), {"finished": 0}, pd.DataFrame()
        if rs["finished"] == 0:
            st.info("No finished matches for that day yet.")
        else:
            k = st.columns(4)
            k[0].metric("Result called right", f"{rs['model_calls_right']} / {rs['finished']}",
                        help="The model's most likely of home win / draw / away win")
            if rs.get("bookmaker_calls_right", (0, 0))[1]:
                bk, n = rs["bookmaker_calls_right"]
                k[1].metric("Bookmaker favourite right", f"{bk} / {n}",
                            help=f"Model on the same {n} games: {rs['model_calls_right_same_games']}")
            for col, kind in ((k[2], "Top pick"), (k[3], "Value bet")):
                g = rs.get(kind)
                if g:
                    col.metric(f"{kind}s won", f"{g['won']} / {g['total']}",
                               help=f"The model expected {g['expected']:.1f} wins"
                                    + (f"; profit {g['profit_units']:+.2f} units at level stakes"
                                       if g.get("profit_units") is not None else ""))
            if rs.get("brier"):
                mb, bb = rs["brier"]
                st.caption(f"Probability accuracy on match results (Brier score, lower is better): model {mb:.3f}, "
                           f"bookmakers {bb:.3f}. One day is a handful of games: luck dominates until a few "
                           "hundred.")
            if rs.get("Value bet (withheld)"):
                w = rs["Value bet (withheld)"]
                st.caption(f"Withheld by the play-safe rules: {w['won']} of {w['total']} would have won "
                           f"({w['profit_units']:+.2f} units). Judge the rules over months, not days.")
            show = m_table.drop(columns=["Model Brier", "Bookmaker Brier"]).copy()
            show["Kick-off"] = show["Kick-off"].dt.strftime("%H:%M")
            show["Withheld"] = show["Withheld"].fillna("").str.split(" (", regex=False).str[0]
            for c in ("Model right", "Bookmaker right", "Top pick won"):
                show[c] = show[c].map({True: "✅", False: "❌"}).fillna("–")
            st.dataframe(show, hide_index=True, width="stretch")
            with st.expander("Every pick and value bet"):
                pt = p_table.copy() if not p_table.empty else pd.DataFrame(columns=["Won"])
                pt["Won"] = pt["Won"].map({True: "✅", False: "❌"})
                st.dataframe(pt, hide_index=True, width="stretch", column_config={
                    "Model": st.column_config.NumberColumn(format="percent"),
                    "Odds": st.column_config.NumberColumn(format="%.2f", help="Bookmaker average before kick-off")})
        if len(pending):
            st.caption(f"Not finished yet: {', '.join(f'{h} v {a}' for h, a in zip(pending['home'], pending['away']))}.")


# ---------------------------------------------------------------- bet slip

with tab_slip:
    st.subheader("Bet slip")
    legs: list[slip.Leg] = st.session_state.setdefault("slip", [])
    if not legs:
        st.info("Empty. Use **Add to slip** on value bets in Match analysis or Fixtures.")
    else:
        slip_sig = tuple((l.home, l.away, l.market) for l in legs)
        if st.button("Get SportyBet booking code", type="primary", key="book_sporty",
                     help="Uses SportyBet's own Book Bet service, as a visitor would: no login, no bet placed."):
            try:
                st.session_state.booking = (slip_sig, *book_on_sportybet(legs))
            except Exception as exc:
                st.session_state.booking = None
                st.error(f"SportyBet didn't answer ({exc}). Add the selections from the copy list below on "
                         "sportybet.com and press **Book Bet** there.")
        booking = st.session_state.get("booking")
        if booking and booking[0] == slip_sig:
            _, booked, checks = booking
            if booked:
                st.success(f"SportyBet booking code: **{booked['code']}** · [open it on SportyBet]({booked['url']})")
                st.code(booked["code"], language=None)
                st.caption("Load the code on SportyBet, choose singles or a multiple, set your stake and confirm "
                           "there. Odds move: SportyBet shows the current price before you confirm.")
                if booked["unavailable"]:
                    st.warning(f"{len(booked['unavailable'])} selection(s) weren't available on SportyBet and "
                               "were left out.")
            else:
                st.warning("None of these selections are open on SportyBet right now.")
            st.dataframe(checks, hide_index=True, width="stretch", column_config={
                "Slip odds": st.column_config.NumberColumn(format="%.2f"),
                "SportyBet now": st.column_config.NumberColumn(format="%.2f")})
        table = pd.DataFrame([{
            "Remove": False, "Date": l.date, "Match": f"{l.home} v {l.away}",
            "SportyBet market": slip.sportybet_name(l.market)[0], "Pick": slip.sportybet_name(l.market)[1],
            "Odds": l.odds, "Model": l.prob, "Edge": 100 * l.edge,
        } for l in legs])
        edited_slip = st.data_editor(table, hide_index=True, width="stretch", disabled=list(table.columns[1:]),
                                     column_config={
                                         "Odds": st.column_config.NumberColumn(format="%.2f"),
                                         "Model": st.column_config.NumberColumn(format="percent"),
                                         "Edge": st.column_config.NumberColumn(format="%+.1f%%")},
                                     key=f"slip_editor::{len(legs)}")
        s1, s2, s3 = st.columns(3)
        if s1.button("Remove ticked"):
            st.session_state.slip = [l for l, rm in zip(legs, edited_slip["Remove"]) if not rm]
            st.rerun()
        if s2.button("Clear slip"):
            st.session_state.slip = []
            st.rerun()

        info = slip.summary(legs, bankroll)
        st.markdown("**Singles (recommended)**")
        q1, q2 = st.columns(2)
        q1.metric("Total stake", f"{info['singles_stake']:,.0f}")
        q2.metric("Expected profit", f"{info['singles_expected_profit']:+,.0f}",
                  help="Average over many repeats if the model's probabilities are right")
        st.markdown("**As one accumulator**")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Total odds", f"{info['acca_odds']:,.2f}")
        a2.metric("Win chance", f"{info['acca_prob']:.1%}")
        a3.metric("Edge", f"{info['acca_edge']:+.1%}")
        a4.metric("Suggested stake", f"{info['acca_stake']:,.0f}", help="Quarter Kelly, capped at 1% of bankroll")
        for w in info["warnings"]:
            st.warning(w)
        st.markdown("**Copy list**")
        st.code(slip.to_text(legs), language=None)
        if s3.button("Log all as singles in tracker"):
            for l in legs:
                tracker.add({"match_date": l.date, "league": l.league, "home": l.home, "away": l.away,
                             "market": l.market, "odds": l.odds,
                             "stake": round(value.kelly_stake(l.prob, l.odds) * bankroll, 2),
                             "model_prob": round(l.prob, 4), "edge": round(l.edge, 4)}, BETS)
            st.toast(f"Logged {len(legs)} bets")


# ---------------------------------------------------------------- bet tracker

with tab_bets:
    st.subheader("Bet tracker")
    bets_df = tracker.load(BETS)
    s = tracker.summary(bets_df)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Bets", f"{s['bets']}", help=f"{s['pending']} pending")
    k2.metric("Profit", f"{s['profit']:,.0f}")
    k3.metric("ROI", pct(s["roi"]), help="Profit ÷ money staked on settled bets")
    k4.metric("Hit rate", pct(s["hit_rate"]))
    k5.metric("Avg CLV", pct(s["avg_clv"]),
              help="Closing-line value: how much better your odds were than the odds at kickoff. "
                   "Consistently positive CLV is the best early sign of a real edge.")

    if s["settled"] >= 2:
        hist = tracker.with_profit(bets_df)
        hist = hist[hist["result"].isin(["won", "lost", "void"])].copy()
        hist["bet #"] = range(1, len(hist) + 1)
        hist["Cumulative profit"] = hist["profit"].cumsum()
        line = alt.Chart(hist).mark_line(color=BLUE, strokeWidth=2).encode(
            x=alt.X("bet #:Q", title="Settled bets"),
            y=alt.Y("Cumulative profit:Q"),
        )
        points = alt.Chart(hist).mark_circle(color=BLUE, size=60).encode(
            x="bet #:Q", y="Cumulative profit:Q",
            tooltip=["bet #", "home", "away", "market", "odds", "stake", "result",
                     alt.Tooltip("Cumulative profit:Q", format=",.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#8a8984", strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart((zero + line + points).properties(height=260), width="stretch")
        if s["settled"] < 200:
            st.caption(f"{s['settled']} settled bets. Results mean little until about 200; luck dominates before that.")

    if bets_df.empty:
        st.info("No bets yet. Use **Log bet** on a value bet in Match analysis, or add one below.")
    st.markdown("**Your bets** (edit result and closing odds, then save)")
    edited_bets = st.data_editor(
        bets_df, hide_index=True, width="stretch", num_rows="dynamic",
        column_config={
            "result": st.column_config.SelectboxColumn(options=tracker.RESULTS, required=True),
            "closing_odds": st.column_config.NumberColumn(help="Odds just before kickoff, for CLV"),
            "id": st.column_config.NumberColumn(disabled=True),
            "placed_at": st.column_config.TextColumn(disabled=True),
        }, key="bets_editor")
    if st.button("Save changes"):
        edited_bets["result"] = edited_bets["result"].fillna("pending")
        tracker.save(edited_bets, BETS)
        st.success("Saved")
        st.rerun()

    with st.expander("Add a bet manually"):
        with st.form("manual_bet", clear_on_submit=True):
            f1, f2, f3 = st.columns(3)
            mh = f1.text_input("Home")
            ma = f2.text_input("Away")
            mm = f3.selectbox("Market", ODDS_MARKETS, format_func=markets.label)
            f4, f5, f6 = st.columns(3)
            mo = f4.number_input("Odds", min_value=1.01, value=1.80, step=0.01)
            ms = f5.number_input("Stake", min_value=0.0, value=round(bankroll * 0.01, 0), step=100.0)
            md = f6.date_input("Match date", value=date.today())
            if st.form_submit_button("Add bet") and mh and ma:
                tracker.add({"match_date": str(md), "league": league, "home": mh, "away": ma,
                             "market": mm, "odds": mo, "stake": ms}, BETS)
                st.rerun()


# ---------------------------------------------------------------- ratings

with tab_ratings:
    st.subheader(f"{data.LEAGUES[league]} team ratings")
    st.caption(f"From results up to {last_result:%d %b %Y}. Attack: goals scored vs. an average team "
               f"(+0.20 ≈ 22% more). Defence: goals conceded (lower is better). "
               f"Home advantage ×{np.exp(model_today.goals.home_adv):.2f} goals.")
    tbl = model_today.goals.table().reset_index(names="Team")
    tbl = tbl[tbl["Team"].isin(current_teams(model_today))]
    tbl["Defensive strength"] = -tbl["defence"]
    scatter = alt.Chart(tbl).encode(
        x=alt.X("attack:Q", title="Attack (better →)"),
        y=alt.Y("Defensive strength:Q", title="Defence (better ↑)"),
    )
    chart = scatter.mark_circle(size=90, color=BLUE, opacity=0.9).encode(
        tooltip=["Team", alt.Tooltip("attack:Q", format="+.2f"), alt.Tooltip("defence:Q", format="+.2f"),
                 alt.Tooltip("net:Q", format="+.2f")]
    ) + scatter.mark_text(align="left", dx=7, fontSize=11).encode(text="Team")
    rules = alt.Chart(pd.DataFrame({"v": [0]}))
    chart = rules.mark_rule(color="#c3c2b7").encode(x="v:Q") + rules.mark_rule(color="#c3c2b7").encode(y="v:Q") + chart
    st.altair_chart(chart.properties(height=480), width="stretch")
    st.dataframe(tbl[["Team", "attack", "defence", "net"]].round(3), hide_index=True, width="stretch")


# ---------------------------------------------------------------- model report

with tab_report:
    st.subheader("How good is the model?")
    st.caption("Walk-forward backtest: for every past week the model is refitted on earlier matches only, "
               "then scored on that week. This is the honest test.")
    if SHARED:
        st.caption("Results of the owner's latest backtest. Backtests and calibration run on the server's command "
                   "line, not from here.")
    else:
        b1, b2 = st.columns([3, 1])
        seasons = b1.multiselect("Seasons to test",
                                 list(range(data.current_season() - 5, data.current_season() + 1)),
                                 default=[data.current_season() - 2, data.current_season() - 1])
        bt_leagues = b1.multiselect("Leagues", list(data.LEAGUES), default=data.TOP5,
                                    format_func=lambda c: data.LEAGUES[c])
        refit_cal = b2.checkbox("Update calibration from results", value=False)
    if not SHARED and b2.button("Run backtest", type="primary") and seasons and bt_leagues:
        with st.spinner("Running backtest (about 30 s per league per season)…", show_time=True):
            hist = data.load_matches(bt_leagues, list(range(min(seasons) - 3, max(seasons) + 1)))
            res = backtest.run(hist, bt_leagues, seasons)
            BACKTEST_CSV.parent.mkdir(parents=True, exist_ok=True)
            res.to_csv(BACKTEST_CSV, index=False)
            if refit_cal:
                calibration.save(calibration.fit(res), note=f"fitted on {bt_leagues} seasons {seasons}")
                st.cache_resource.clear()

    if not BACKTEST_CSV.exists():
        st.info("No backtest yet." + ("" if SHARED else " Press **Run backtest**."))
    else:
        res = pd.read_csv(BACKTEST_CSV, parse_dates=["date"])
        st.caption(f"{res[['date', 'home', 'away']].drop_duplicates().shape[0]:,} matches, "
                   f"leagues {', '.join(sorted(res['league'].unique()))}, seasons "
                   f"{', '.join(str(x) for x in sorted(res['season'].unique()))}")

        st.markdown("**Scorecard** (skill > 0 means better than guessing the league average every time)")
        sc = backtest.scorecard(res).reset_index()
        sc["market"] = sc["market"].map(lambda m: m if m.startswith("1X2") else markets.label(m))
        st.dataframe(sc, hide_index=True, width="stretch", column_config={
            "base_rate": st.column_config.NumberColumn("How often it happens", format="percent"),
            "accuracy": st.column_config.NumberColumn("Accuracy", format="percent"),
            "log_loss": st.column_config.NumberColumn("Log loss", format="%.3f"),
            "baseline_ll": st.column_config.NumberColumn("Baseline log loss", format="%.3f"),
            "skill_%": st.column_config.NumberColumn("Skill", format="%.1f%%"),
        })

        st.markdown("**Calibration**: when the model says X%, does it happen X% of the time?")
        cal_market = st.selectbox("Market", backtest.BINARY_MARKETS, index=1, format_func=markets.label)
        cal = backtest.calibration(res, cal_market).reset_index(drop=True)
        cal = cal[cal["matches"] >= 15]
        diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(
            color="#8a8984", strokeDash=[4, 4]).encode(x="x:Q", y="y:Q")
        calc = alt.Chart(cal).encode(
            x=alt.X("predicted:Q", title="Model probability", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%")),
            y=alt.Y("actual:Q", title="Actually happened", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%")),
        )
        calc = calc.mark_line(color=BLUE, strokeWidth=2) + calc.mark_circle(color=BLUE).encode(
            size=alt.Size("matches:Q", legend=None, scale=alt.Scale(range=[40, 300])),
            tooltip=[alt.Tooltip("predicted:Q", format=".1%"), alt.Tooltip("actual:Q", format=".1%"), "matches"])
        st.altair_chart((diag + calc).properties(height=340), width="stretch")
        st.caption("Dashed line = perfect. Dots below it: the model was too confident. "
                   "These are raw backtest numbers; the live app also applies the saved calibration.")

        st.markdown("**'Safe' picks**: hit rate when the model was very confident, and the lowest odds "
                    "that would still have made a profit")
        conf = backtest.confidence_table(res)
        conf["market"] = conf["market"].map(
            lambda m: markets.label(m.split(" / ")[0]) + (" (or under)" if " / " in m else ""))
        st.dataframe(conf, hide_index=True, width="stretch", column_config={
            "min_prob": st.column_config.NumberColumn("Model at least", format="percent"),
            "avg_model_prob": st.column_config.NumberColumn("Avg model prob", format="percent"),
            "hit_rate": st.column_config.NumberColumn("Won", format="percent"),
            "breakeven_odds": st.column_config.NumberColumn("Break-even odds", format="%.2f"),
        })

        bets_bt = backtest.betting(res)
        st.markdown("**Profit test at historical closing odds**")
        if bets_bt is None:
            st.info("This data has no historical odds. Run the backtest on data from football-data.co.uk "
                    "(press Refresh data first) to get the profit test.")
        else:
            st.dataframe(bets_bt.reset_index(), hide_index=True, width="stretch")
