"""Command line: python -m predictor {predict,upcoming,review,backtest,ratings} ..."""
from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd

from . import backtest, calibration, data, fixtures, predict, review
from .model import LeagueModel


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m predictor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("predict", help="predict fixtures from a CSV and flag value bets")
    p.add_argument("fixtures", type=Path)
    p.add_argument("--out", type=Path, default=Path("output/predictions.csv"))
    p.add_argument("--bankroll", type=float, help="your total betting bankroll, to print stake amounts")

    u = sub.add_parser("upcoming", help="fetch the next days' fixtures online and predict them")
    u.add_argument("--leagues", nargs="+", default=data.TOP5, choices=sorted(data.LEAGUES))
    u.add_argument("--days", type=int, default=3, help="1 = today only")
    u.add_argument("--out", type=Path, default=Path("output/upcoming.csv"))
    u.add_argument("--bankroll", type=float, help="your total betting bankroll, to print stake amounts")

    v = sub.add_parser("review", help="grade a day's picks against the final scores")
    v.add_argument("--date", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD, default today")
    v.add_argument("--leagues", nargs="+", default=data.TOP5, choices=sorted(data.LEAGUES))

    b = sub.add_parser("backtest", help="walk-forward test on past seasons")
    b.add_argument("--leagues", nargs="+", default=data.TOP5)
    b.add_argument("--seasons", nargs="+", type=int, default=[data.current_season() - 2, data.current_season() - 1],
                   help="season start years to test, e.g. 2024 2025")
    b.add_argument("--out", type=Path, default=Path("output/backtest.csv"))
    b.add_argument("--save-calibration", action="store_true",
                   help="refit the calibration in models/calibration.json from these results")

    r = sub.add_parser("ratings", help="show current team ratings for a league")
    r.add_argument("league", choices=sorted(data.LEAGUES))

    args = ap.parse_args()
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 200)

    if args.cmd == "predict":
        predict.run(predict.read_fixtures(args.fixtures), args.out, args.bankroll)

    elif args.cmd == "upcoming":
        now = data.current_season()
        matches = data.load_matches(args.leagues, list(range(now - 3, now + 1)))
        fx, notes = fixtures.upcoming(args.leagues, args.days, fixtures.known_teams(matches))
        for note in notes:
            print(f"note: {note}")
        if fx.empty:
            print(f"No fixtures found in the next {args.days} day(s).")
        else:
            predict.run(predict.normalise_fixtures(fx), args.out, args.bankroll, matches)

    elif args.cmd == "review":
        match_table, pick_table, s, pending = review.review(args.leagues, args.date)
        print(f"{args.date:%A %d %B %Y}: {s['finished']} finished, {len(pending)} not finished yet")
        if not match_table.empty:
            print(match_table.drop(columns=["Kick-off", "Model Brier", "Bookmaker Brier"]).to_string(index=False))
            print()
            print(pick_table.to_string(index=False))
            print()
            for key, val in s.items():
                print(f"{key}: {val}")

    elif args.cmd == "backtest":
        first = min(args.seasons)
        matches = data.load_matches(args.leagues, list(range(first - 3, max(args.seasons) + 1)))
        print(f"Backtesting {args.leagues} seasons {args.seasons} (refit every week, past data only)")
        res = backtest.run(matches, args.leagues, args.seasons)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(args.out, index=False)
        print("\nSCORECARD (skill_% > 0 means better than always guessing the league average)")
        print(backtest.scorecard(res).round(3).to_string())
        print("\nHIGH-CONFIDENCE PICKS (would 'safe' picks have made money?)")
        print(backtest.confidence_table(res).round(3).to_string(index=False))
        print("\nCALIBRATION over_2.5 (predicted vs actual)")
        print(backtest.calibration(res, "over_2.5").round(3).to_string())
        bets = backtest.betting(res)
        if bets is not None:
            print("\nVALUE BETS AT HISTORICAL CLOSING ODDS (flat 1 unit each)")
            print(bets.round(3).to_string())
        else:
            print("\n(no historical odds in this data, so no profit test; "
                  "football-data.co.uk files include them)")
        print(f"\nPer-match predictions saved to {args.out}")
        if args.save_calibration:
            calibration.save(calibration.fit(res), note=f"fitted on {args.leagues} seasons {args.seasons}")
            print(f"Calibration saved to {calibration.DEFAULT_PATH}")

    elif args.cmd == "ratings":
        now = data.current_season()
        matches = data.load_matches([args.league], list(range(now - 3, now + 1)))
        lm = LeagueModel.fit(matches, args.league, pd.Timestamp.today())
        print(f"{data.LEAGUES[args.league]} ratings using results up to {lm.history['date'].max():%Y-%m-%d}")
        print(f"home advantage: x{math.exp(lm.goals.home_adv):.2f} goals")
        print(lm.goals.table().round(3).to_string())


if __name__ == "__main__":
    main()
