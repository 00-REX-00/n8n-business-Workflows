"""Football Predictor web app.  Run:  streamlit run app.py"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from predictor import absences, backtest, calibration, data, markets, news, predict, safety, slip, tracker, value
from predictor.model import LeagueModel

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "data" / "settings.json"
BACKTEST_CSV = ROOT / "output" / "backtest.csv"

# Chart colours (validated categorical slot 1, sequential blue ramp, status colours)
BLUE = "#2a78d6"
SEQ_LOW, SEQ_HIGH = "#cde2fb", "#0d366b"
GOOD = "#0ca30c"

absences_leagues = {"E0", "SP1", "I1", "D1", "F1"}

ODDS_MARKETS = [
    "1", "X", "2", "1X", "X2", "12",
    "over_1.5", "under_1.5", "over_2.5", "under_2.5", "over_3.5", "under_3.5",
    "btts_yes", "btts_no", "home_over_0.5", "away_over_0.5", "home_over_1.5", "away_over_1.5",
    "cards_over_3.5", "cards_under_3.5", "cards_over_4.5", "cards_under_4.5",
    "corners_over_9.5", "corners_under_9.5",
]

st.set_page_config(page_title="Football Predictor", page_icon="⚽", layout="wide")


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


def add_to_slip(leg: slip.Leg) -> None:
    legs = st.session_state.setdefault("slip", [])
    if any((l.home, l.away, l.market) == (leg.home, leg.away, leg.market) for l in legs):
        st.toast("Already on the slip")
        return
    legs.append(leg)
    st.toast(f"Added to slip: {leg.home} v {leg.away}, {markets.label(leg.market)}")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {"bankroll": 50000.0}


def save_settings(s: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s))


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


# ---------------------------------------------------------------- sidebar

settings = load_settings()
if "refresh" not in st.session_state:
    st.session_state.refresh = 0

with st.sidebar:
    st.title("⚽ Football Predictor")
    league = st.selectbox("League", list(data.LEAGUES), format_func=lambda c: f"{data.LEAGUES[c]} ({c})")
    bankroll = st.number_input("Bankroll", min_value=0.0, value=float(settings.get("bankroll", 50000)),
                               step=1000.0, help="Your total betting money. Stakes are a % of this.")
    if bankroll != settings.get("bankroll"):
        settings["bankroll"] = bankroll
        save_settings(settings)
    key_in = st.text_input("API-Football key", value=settings.get("api_football_key", ""), type="password",
                           help="For team news (injuries, suspensions) in every league. Free key: "
                                "dashboard.api-football.com. Premier League news also works without it (FPL).")
    if key_in != settings.get("api_football_key", ""):
        settings["api_football_key"] = key_in
        save_settings(settings)
    if st.button("Refresh data", help="Download the latest results from football-data.co.uk"):
        st.session_state.refresh += 1
        st.cache_data.clear()
        st.cache_resource.clear()
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

tab_match, tab_list, tab_slip, tab_bets, tab_ratings, tab_report = st.tabs(
    ["Match analysis", "Fixture list", "Bet slip", "Bet tracker", "Team ratings", "Model report"])


# ---------------------------------------------------------------- match analysis

with tab_match:
    teams_list = current_teams(model_today)
    c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.6])
    home = c1.selectbox("Home team", teams_list, index=0)
    away = c2.selectbox("Away team", teams_list, index=min(1, len(teams_list) - 1))
    match_day = c3.date_input("Match date", value=date.today())
    refs = ["(unknown)"] + sorted(model_today.referee_factor)
    referee = c4.selectbox("Referee", refs, help="Only some leagues publish referees. Affects cards.")

    season_now = int(model_today.history["season"].max())
    fn = fixture_news(league, season_now, f"{match_day:%Y-%m-%d}", home, away,
                      tuple(model_today.goals.teams), settings.get("api_football_key", ""))
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
    ctx = lm.context(home, away)

    m = st.columns(6)
    m[0].metric("xG home–away", f"{pred['xg_home']:.1f}–{pred['xg_away']:.1f}")
    m[1].metric("Home win", f"{probs['1']:.0%}")
    m[2].metric("Draw", f"{probs['X']:.0%}")
    m[3].metric("Away win", f"{probs['2']:.0%}")
    m[4].metric("Expected cards", f"{pred.get('exp_cards', float('nan')):.1f}",
                help=f"Referee factor ×{pred['referee_factor']:.2f}" if "referee_factor" in pred else None)
    m[5].metric("Expected corners", f"{pred.get('exp_corners', float('nan')):.1f}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Model vs. your odds")
        st.caption("Type the odds your bookmaker (e.g. SportyBet) offers in the **Your odds** column. "
                   "Fair odds = the price at which a bet breaks even.")
        # The editor's input must stay identical between reruns or Streamlit drops
        # typed values, so build it once per match setup and carry odds across.
        saved = st.session_state.setdefault(f"odds::{league}::{home}::{away}", {})
        editor_key = f"editor::{league}::{home}::{away}::{match_day}::{referee}::{home_adj}::{away_adj}"
        if f"base::{editor_key}" not in st.session_state:
            st.session_state[f"base::{editor_key}"] = pd.DataFrame([{
                "market": mk, "Market": markets.label(mk), "Model": probs[mk], "Fair odds": 1 / probs[mk],
                "Your odds": saved.get(mk, np.nan),
            } for mk in ODDS_MARKETS if mk in probs])
        edited = st.data_editor(
            st.session_state[f"base::{editor_key}"], hide_index=True, width="stretch", height=440,
            column_order=["Market", "Model", "Fair odds", "Your odds"],
            disabled=["Market", "Model", "Fair odds"],
            column_config={
                "Model": st.column_config.NumberColumn(format="percent", help="Calibrated model probability"),
                "Fair odds": st.column_config.NumberColumn(format="%.2f"),
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
                                 "model_prob": round(b.prob, 4), "edge": round(b.edge, 4)})
                    st.toast(f"Logged {markets.label(b.market)} @ {b.odds}")
                if bc3.button("Add to slip", key=f"slip::{league}::{home}::{away}::{b.market}"):
                    add_to_slip(slip.Leg(str(match_day), league, home, away, b.market, b.odds, b.prob))
        elif odds and not skipped:
            st.info("No value at these odds. Not betting is the right call.")

    with right:
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

        st.subheader("Form & head-to-head")
        st.markdown(f"**{home}** last 5: `{ctx['home_form'] or '–'}`  \n**{away}** last 5: `{ctx['away_form'] or '–'}`")
        if ctx["h2h"]:
            st.markdown("\n".join(f"- {g}" for g in reversed(ctx["h2h"])))
        st.caption("Shown for context. The probabilities use team ratings built from every recent match, "
                   "not just these few games.")


# ---------------------------------------------------------------- fixture list

with tab_list:
    st.subheader("Analyse a list of fixtures")
    st.caption("Upload a CSV with columns `league, date, home, away` and optionally `referee`, "
               "`home_missing` / `away_missing` (players out, e.g. `Haaland; De Bruyne`), `home_adj`, "
               "`away_adj` and odds columns like `odds:1`, `odds:over_2.5`, `odds:btts_yes`.")
    example = (ROOT / "examples" / "fixtures_example.csv").read_bytes()
    st.download_button("Download template", example, "fixtures_template.csv", "text/csv")
    upload = st.file_uploader("Fixtures CSV", type="csv")
    if upload is not None:
        fixtures = predict.read_fixtures(upload)
        all_leagues = tuple(sorted(fixtures["league"].unique()))
        with st.spinner("Predicting…"):
            results, warnings = predict.analyse(fixtures, load_matches(all_leagues, st.session_state.refresh))
        for w in warnings:
            st.warning(w)
        if results:
            summary = pd.DataFrame([{
                "Date": r["fx"]["date"].date(), "League": r["league"],
                "Match": f"{r['home']} v {r['away']}",
                "xG": f"{r['pred']['xg_home']:.2f}–{r['pred']['xg_away']:.2f}",
                "Home": r["pred"]["probs"]["1"], "Draw": r["pred"]["probs"]["X"], "Away": r["pred"]["probs"]["2"],
                "Over 1.5": r["pred"]["probs"]["over_1.5"], "Over 2.5": r["pred"]["probs"]["over_2.5"],
                "BTTS": r["pred"]["probs"]["btts_yes"],
                "Value bets": ", ".join(f"{markets.label(b.market)} @{b.odds} ({b.edge:+.0%}, "
                                        f"stake {b.stake_pct * bankroll:,.0f})" for b in r["bets"]) or "–",
                "Withheld": "; ".join(f"{markets.label(b.market)}: {why}" for b, why in r["skipped"]) or "–",
            } for r in results])
            pcols = ["Home", "Draw", "Away", "Over 1.5", "Over 2.5", "BTTS"]
            st.dataframe(summary, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="percent") for c in pcols})
            all_bets = [(r, b) for r in results for b in r["bets"]]
            d1, d2 = st.columns(2)
            if all_bets and d1.button(f"Add all {len(all_bets)} value bets to the slip", type="primary"):
                for r, b in all_bets:
                    add_to_slip(slip.Leg(str(r["fx"]["date"].date()), r["league"], r["home"], r["away"],
                                         b.market, b.odds, b.prob))
            d2.download_button("Download all market probabilities",
                               predict.to_table(results).to_csv(index=False).encode(),
                               "predictions.csv", "text/csv")


# ---------------------------------------------------------------- bet slip

with tab_slip:
    st.subheader("Bet slip")
    legs: list[slip.Leg] = st.session_state.setdefault("slip", [])
    if not legs:
        st.info("Empty. Use **Add to slip** on value bets in Match analysis or Fixture list.")
    else:
        st.markdown("**To get a SportyBet booking code:** add these selections on sportybet.com/ng "
                    "(same market names below), open the betslip, and press **Book Bet**. SportyBet "
                    "has no public API, so the code can't be created from here.")
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
                             "model_prob": round(l.prob, 4), "edge": round(l.edge, 4)})
            st.toast(f"Logged {len(legs)} bets")


# ---------------------------------------------------------------- bet tracker

with tab_bets:
    st.subheader("Bet tracker")
    bets_df = tracker.load()
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
        tracker.save(edited_bets)
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
                             "market": mm, "odds": mo, "stake": ms})
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
    b1, b2 = st.columns([3, 1])
    seasons = b1.multiselect("Seasons to test", list(range(data.current_season() - 5, data.current_season() + 1)),
                             default=[data.current_season() - 2, data.current_season() - 1])
    bt_leagues = b1.multiselect("Leagues", list(data.LEAGUES), default=data.TOP5,
                                format_func=lambda c: data.LEAGUES[c])
    refit_cal = b2.checkbox("Update calibration from results", value=False)
    if b2.button("Run backtest", type="primary") and seasons and bt_leagues:
        with st.spinner("Running backtest (about 30 s per league per season)…"):
            hist = data.load_matches(bt_leagues, list(range(min(seasons) - 3, max(seasons) + 1)))
            res = backtest.run(hist, bt_leagues, seasons)
            BACKTEST_CSV.parent.mkdir(parents=True, exist_ok=True)
            res.to_csv(BACKTEST_CSV, index=False)
            if refit_cal:
                calibration.save(calibration.fit(res), note=f"fitted on {bt_leagues} seasons {seasons}")
                st.cache_resource.clear()

    if not BACKTEST_CSV.exists():
        st.info("No backtest yet. Press **Run backtest**.")
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
