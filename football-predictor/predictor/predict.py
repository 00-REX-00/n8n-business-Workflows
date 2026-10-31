"""Predict upcoming fixtures and flag value bets against your bookmaker's odds."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import absences, data, markets, news, picks, safety, teams, value
from .model import LeagueModel

HEADLINE = ["1", "X", "2", "1X", "X2", "over_1.5", "over_2.5", "under_2.5",
            "over_3.5", "btts_yes", "btts_no", "home_over_0.5", "away_over_0.5",
            "corners_over_9.5", "cards_over_3.5"]
STALE_DAYS = 21


def read_fixtures(path: Path) -> pd.DataFrame:
    return normalise_fixtures(pd.read_csv(path))


def normalise_fixtures(fx: pd.DataFrame) -> pd.DataFrame:
    """Fill the optional columns `analyse` expects, for a file or fetched fixtures."""
    fx = fx.copy()
    missing = {"league", "home", "away"} - set(fx.columns)
    if missing:
        raise ValueError(f"fixtures file is missing columns: {sorted(missing)}")
    fx["date"] = pd.to_datetime(fx.get("date", pd.Timestamp.today().normalize()))
    for col, default in (("home_adj", 1.0), ("away_adj", 1.0)):
        fx[col] = pd.to_numeric(fx[col], errors="coerce").fillna(default) if col in fx else default
    for col in ("referee", "home_missing", "away_missing"):
        if col not in fx:
            fx[col] = None
    return fx


def _shares(lm: LeagueModel, team: str) -> pd.DataFrame:
    if lm.league not in absences.UNDERSTAT_LEAGUES:
        return absences.attack_shares(pd.DataFrame(columns=["team"]), team)
    return absences.team_shares(lm.league, team, int(lm.history["season"].max()), lm.goals.teams)


def _missing(shares: pd.DataFrame, typed, from_news: list[str], team: str,
             warnings: list[str]) -> tuple[float, list[str]]:
    """Attack multiplier for players out: typed in the fixture file plus team news."""
    names = typed.replace(",", ";").split(";") if isinstance(typed, str) else []
    matched, unknown = absences.resolve_players(names, shares)
    if unknown:
        warnings.append(f"{team}: no player data for {', '.join(unknown)} (ignored)")
    matched += [p for p in absences.resolve_players(from_news, shares)[0] if p not in matched]
    return absences.multiplier(shares, matched), matched


def analyse(fixtures: pd.DataFrame, matches: pd.DataFrame | None = None) -> tuple[list[dict], list[str]]:
    """Predict every fixture. Returns (one dict per fixture, warnings)."""
    if matches is None:
        now = data.current_season()
        matches = data.load_matches(sorted(fixtures["league"].unique()), list(range(now - 3, now + 1)))

    results, warnings = [], []
    models: dict[str, LeagueModel] = {}
    for _, fx in fixtures.iterrows():
        league = fx["league"]
        if league not in models:
            models[league] = LeagueModel.fit(matches, league, fx["date"])
            last = models[league].history["date"].max()
            if (fx["date"] - last).days > STALE_DAYS:
                warnings.append(f"Latest {league} result in the data is {last:%Y-%m-%d}. Predictions "
                                f"ignore everything since then. Check your internet access to "
                                f"football-data.co.uk before betting.")
        lm = models[league]
        try:
            home, away = teams.resolve(fx["home"], lm.goals.teams), teams.resolve(fx["away"], lm.goals.teams)
        except KeyError as exc:
            warnings.append(f"Skipped {fx['home']} v {fx['away']}: {exc}")
            continue
        referee = fx["referee"] if isinstance(fx["referee"], str) else None
        fn = news.fixture_news(league, int(lm.history["season"].max()), f"{fx['date']:%Y-%m-%d}",
                               home, away, lm.goals.teams)
        h_sh, a_sh = _shares(lm, home), _shares(lm, away)
        h_mult, h_out = _missing(h_sh, fx["home_missing"], fn.home.out, home, warnings)
        a_mult, a_out = _missing(a_sh, fx["away_missing"], fn.away.out, away, warnings)
        pred = lm.predict(home, away, referee, fx["home_adj"] * h_mult, fx["away_adj"] * a_mult)
        pred["missing"] = {"home": (h_out, h_mult), "away": (a_out, a_mult)}
        odds = {c.split(":", 1)[1]: float(fx[c]) for c in fixtures.columns
                if c.startswith("odds:") and pd.notna(fx[c])}
        manual_ok = str(fx.get("news_checked", "")).strip().lower() in ("1", "yes", "true", "y")
        bets, skipped = safety.screen(value.find_value(pred["probs"], odds), fn, h_sh, a_sh, manual_ok)
        results.append({
            "fx": fx, "league": league, "home": home, "away": away, "pred": pred,
            "ctx": lm.context(home, away), "odds": odds, "news": fn,
            "bets": bets, "skipped": skipped, "picks": picks.best_picks(pred["probs"]),
            "withheld": safety.fixture_reason(fn, h_sh, a_sh, manual_ok),
        })
    return results, warnings


def to_table(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        pred = r["pred"]
        row = {"date": r["fx"]["date"].date(), "league": r["league"], "home": r["home"], "away": r["away"],
               "xg_home": round(pred["xg_home"], 2), "xg_away": round(pred["xg_away"], 2)}
        row.update({f"p:{k}": round(v, 4) for k, v in pred["probs"].items()})
        row["value_bets"] = "; ".join(f"{b.market}@{b.odds} edge {b.edge:+.1%} stake {b.stake_pct:.1%}"
                                      for b in r["bets"])
        rows.append(row)
    return pd.DataFrame(rows)


def run(fixtures: pd.DataFrame, out_csv: Path | None = None, bankroll: float | None = None,
        matches: pd.DataFrame | None = None) -> pd.DataFrame:
    results, warnings = analyse(fixtures, matches)
    for w in warnings:
        print(f"\n!! {w}")
    for r in results:
        _print_fixture(r["fx"], r["home"], r["away"], r["pred"], r["ctx"], r["bets"], bankroll, r["skipped"])
        if r["picks"]:
            tips = ", ".join(f"{markets.label(p.market)} {p.prob:.0%} (bet at {p.odds_range[0]:.2f}-"
                             f"{p.odds_range[1]:.2f})" for p in r["picks"])
            print(f"Best picks{' (withheld: ' + r['withheld'] + ')' if r['withheld'] else ''}: {tips}")
    table = to_table(results)
    if out_csv is not None and not table.empty:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(out_csv, index=False)
        print(f"\nAll market probabilities written to {out_csv}")
    return table


def _print_fixture(fx, home, away, pred, ctx, bets, bankroll, skipped=()):
    print("\n" + "=" * 72)
    when = f"{fx['kickoff']:%a %d %b %Y %H:%M}" if pd.notna(fx.get("kickoff")) else f"{fx['date']:%a %d %b %Y}"
    print(f"{when}  [{data.LEAGUES.get(fx['league'], fx['league'])}]  {home} v {away}")
    print(f"Expected goals {pred['xg_home']:.2f} - {pred['xg_away']:.2f}   "
          f"likely scores: " + ", ".join(f"{s} ({p:.0%})" for s, p in pred["scores"]))
    if "exp_corners" in pred:
        print(f"Expected corners {pred['exp_corners']:.1f}   expected cards {pred.get('exp_cards', float('nan')):.1f}"
              + (f" (referee x{pred['referee_factor']:.2f})" if "referee_factor" in pred else ""))
    if skipped:
        for b, reason in skipped:
            print(f"  skipped {b.market} @ {b.odds}: {reason}")
    for side, team in (("home", home), ("away", away)):
        out, mult = pred.get("missing", {}).get(side, ([], 1.0))
        if out:
            print(f"Missing for {team}: {', '.join(out)} -> attack x{mult:.2f}")
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
    elif skipped:
        print("No safe bets for this match (see skipped above).")
    elif any(c.startswith("odds:") for c in fx.index):
        print("No value at these odds: no bet.")
