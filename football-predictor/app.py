"""Football Predictor web app.  Run:  streamlit run app.py"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from predictor import backtest, calibration, data, markets, predict, tracker, value
from predictor.model import LeagueModel

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "data" / "settings.json"
BACKTEST_CSV = ROOT / "output" / "backtest.csv"

# Chart colours (validated categorical slot 1, sequential blue ramp, status colours)
BLUE = "#2a78d6"
SEQ_LOW, SEQ_HIGH = "#cde2fb", "#0d366b"
GOOD = "#0ca30c"

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

tab_match, tab_list, tab_bets, tab_ratings, tab_report = st.tabs(
    ["Match analysis", "Fixture list", "Bet tracker", "Team ratings", "Model report"])


# ---------------------------------------------------------------- match analysis

with tab_match:
    teams_list = current_teams(model_today)
    c1, c2, c3, c4 = st.columns([2, 2, 1.2, 1.6])
    home = c1.selectbox("Home team", teams_list, index=0)
    away = c2.selectbox("Away team", teams_list, index=min(1, len(teams_list) - 1))
    match_day = c3.date_input("Match date", value=date.today())
    refs = ["(unknown)"] + sorted(model_today.referee_factor)
    referee = c4.selectbox("Referee", refs, help="Only some leagues publish referees. Affects cards.")

    with st.expander("Team news (lineups, injuries, rotation)", expanded=False):
        st.caption("Scale each team's expected goals for news the ratings can't see. "
                   "Rough guide: main striker out 0.85–0.90, heavy rotation 0.90, "
                   "several defenders out → raise the *opponent* to 1.05–1.10.")
        n1, n2 = st.columns(2)
        home_adj = n1.slider(f"{home} attack", 0.70, 1.30, 1.00, 0.05)
        away_adj = n2.slider(f"{away} attack", 0.70, 1.30, 1.00, 0.05)

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

        if odds:
            check = pd.DataFrame([{
                "Market": markets.label(mk), "Your odds": o, "Model": probs[mk],
                "Bookmaker": book.get(mk), "Edge": 100 * value.edge(probs[mk], o),
                "Verdict": verdict(mk, probs[mk], o, bankroll),
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

        bets = value.find_value(probs, odds)
        if bets:
            st.success(f"{len(bets)} value bet(s) found")
            for b in bets:
                bc1, bc2 = st.columns([4, 1])
                stake_amt = round(b.stake_pct * bankroll, 2)
                bc1.markdown(f"**{markets.label(b.market)}** @ {b.odds:.2f} — model {b.prob:.1%}, "
                             f"edge {b.edge:+.1%}, stake **{stake_amt:,.0f}** ({b.stake_pct:.1%})")
                if b.edge > 0.15:
                    bc1.caption("⚠️ Very large edge: usually means news the model doesn't know. Check lineups first.")
                if bc2.button("Log bet", key=f"log::{league}::{home}::{away}::{b.market}"):
                    tracker.add({"match_date": str(match_day), "league": league, "home": home, "away": away,
                                 "market": b.market, "odds": b.odds, "stake": stake_amt,
                                 "model_prob": round(b.prob, 4), "edge": round(b.edge, 4)})
                    st.toast(f"Logged {markets.label(b.market)} @ {b.odds}")
        elif odds:
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
    st.caption("Upload a CSV with columns `league, date, home, away` and optionally `referee, home_adj, "
               "away_adj` and odds columns like `odds:1`, `odds:over_2.5`, `odds:btts_yes`.")
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
            } for r in results])
            pcols = ["Home", "Draw", "Away", "Over 1.5", "Over 2.5", "BTTS"]
            st.dataframe(summary, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="percent") for c in pcols})
            st.download_button("Download all market probabilities",
                               predict.to_table(results).to_csv(index=False).encode(),
                               "predictions.csv", "text/csv")


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
