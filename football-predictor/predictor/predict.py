"""Predict upcoming fixtures and flag value bets against your bookmaker's odds."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import data, teams, value
from .model import LeagueModel

HEADLINE = ["1", "X", "2", "1X", "X2", "over_1.5", "over_2.5", "under_2.5",
            "over_3.5", "btts_yes", "btts_no", "home_over_0.5", "away_over_0.5",
            "corners_over_9.5", "cards_over_3.5"]
STALE_DAYS = 21


def read_fixtures(path: Path) -> pd.DataFrame:
    fx = pd.read_csv(path)
    missing = {"league", "home", "away"} - set(fx.columns)
    if missing:
        raise ValueError(f"fixtures file is missing columns: {sorted(missing)}")
    fx["date"] = pd.to_datetime(fx.get("date", pd.Timestamp.today().normalize()))
    for col, default in (("home_adj", 1.0), ("away_adj", 1.0)):
        fx[col] = pd.to_numeric(fx.get(col, default), errors="coerce").fillna(default)
    if "referee" not in fx:
        fx["referee"] = None
    return fx


def run(fixtures: pd.DataFrame, out_csv: Path | None = None, bankroll: float | None = None) -> pd.DataFrame:
    leagues = sorted(fixtures["league"].unique())
    now = data.current_season()
    matches = data.load_matches(leagues, list(range(now - 3, now + 1)))

    rows = []
    models: dict[str, LeagueModel] = {}
    for _, fx in fixtures.iterrows():
        league = fx["league"]
        if league not in models:
            models[league] = LeagueModel.fit(matches, league, fx["date"])
            last = models[league].history["date"].max()
            if (fx["date"] - last).days > STALE_DAYS:
                print(f"\n!! WARNING: latest {league} result in the data is {last:%Y-%m-%d}. "
                      f"Predictions ignore everything since then. Check your internet access "
                      f"to football-data.co.uk before betting.")
        lm = models[league]
        known = lm.goals.teams
        try:
            home, away = teams.resolve(fx["home"], known), teams.resolve(fx["away"], known)
        except KeyError as exc:
            print(f"\nskipping {fx['home']} v {fx['away']}: {exc}")
            continue
        referee = fx["referee"] if isinstance(fx["referee"], str) else None
        pred = lm.predict(home, away, referee, fx["home_adj"], fx["away_adj"])
        ctx = lm.context(home, away)
        odds = {c.split(":", 1)[1]: float(fx[c]) for c in fixtures.columns
                if c.startswith("odds:") and pd.notna(fx[c])}
        bets = value.find_value(pred["probs"], odds)

        _print_fixture(fx, home, away, pred, ctx, bets, bankroll)
        row = {"date": fx["date"].date(), "league": league, "home": home, "away": away,
               "xg_home": round(pred["xg_home"], 2), "xg_away": round(pred["xg_away"], 2)}
        row.update({f"p:{k}": round(v, 4) for k, v in pred["probs"].items()})
        row["value_bets"] = "; ".join(f"{b.market}@{b.odds} edge {b.edge:+.1%} stake {b.stake_pct:.1%}"
                                      for b in bets)
        rows.append(row)

    result = pd.DataFrame(rows)
    if out_csv is not None and not result.empty:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(out_csv, index=False)
        print(f"\nAll market probabilities written to {out_csv}")
    return result


def _print_fixture(fx, home, away, pred, ctx, bets, bankroll):
    print("\n" + "=" * 72)
    print(f"{fx['date']:%a %d %b %Y}  [{data.LEAGUES.get(fx['league'], fx['league'])}]  {home} v {away}")
    print(f"Expected goals {pred['xg_home']:.2f} - {pred['xg_away']:.2f}   "
          f"likely scores: " + ", ".join(f"{s} ({p:.0%})" for s, p in pred["scores"]))
    if "exp_corners" in pred:
        print(f"Expected corners {pred['exp_corners']:.1f}   expected cards {pred.get('exp_cards', float('nan')):.1f}"
              + (f" (referee x{pred['referee_factor']:.2f})" if "referee_factor" in pred else ""))
    print(f"Form (last 5, oldest first): {home} {ctx['home_form']} | {away} {ctx['away_form']}")
    if ctx["h2h"]:
        print("Head-to-head: " + " | ".join(ctx["h2h"]))
    probs = pred["probs"]
    cells = [f"{m:>16} {probs[m]:5.1%} @{1 / probs[m]:5.2f}" for m in HEADLINE if m in probs]
    print("Model probability and fair odds:")
    for i in range(0, len(cells), 3):
        print("  " + " ".join(cells[i:i + 3]))
    if bets:
        print("VALUE (bookmaker odds above fair odds):")
        for b in bets:
            stake = f"  stake {b.stake_pct:.1%} of bankroll"
            if bankroll:
                stake += f" = {b.stake_pct * bankroll:,.0f}"
            print(f"  * {b.market:<16} odds {b.odds:<5} fair {b.fair_odds:.2f}  edge {b.edge:+.1%}{stake}")
    elif any(c.startswith("odds:") for c in fx.index):
        print("No value at these odds: no bet.")
