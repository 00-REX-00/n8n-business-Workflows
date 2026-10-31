"""Command line: python -m predictor {predict,backtest,ratings} ..."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from . import backtest, data, predict
from .model import LeagueModel


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m predictor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("predict", help="predict fixtures from a CSV and flag value bets")
    p.add_argument("fixtures", type=Path)
    p.add_argument("--out", type=Path, default=Path("output/predictions.csv"))
    p.add_argument("--bankroll", type=float, help="your total betting bankroll, to print stake amounts")

    b = sub.add_parser("backtest", help="walk-forward test on past seasons")
    b.add_argument("--leagues", nargs="+", default=data.TOP5)
    b.add_argument("--seasons", nargs="+", type=int, default=[data.current_season() - 2, data.current_season() - 1],
                   help="season start years to test, e.g. 2024 2025")
    b.add_argument("--out", type=Path, default=Path("output/backtest.csv"))

    r = sub.add_parser("ratings", help="show current team ratings for a league")
    r.add_argument("league", choices=sorted(data.LEAGUES))

    args = ap.parse_args()
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 200)

    if args.cmd == "predict":
        predict.run(predict.read_fixtures(args.fixtures), args.out, args.bankroll)

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

    elif args.cmd == "ratings":
        now = data.current_season()
        matches = data.load_matches([args.league], list(range(now - 3, now + 1)))
        lm = LeagueModel.fit(matches, args.league, pd.Timestamp.today())
        print(f"{data.LEAGUES[args.league]} ratings using results up to {lm.history['date'].max():%Y-%m-%d}")
        print(f"home advantage: x{math.exp(lm.goals.home_adv):.2f} goals")
        print(lm.goals.table().round(3).to_string())


if __name__ == "__main__":
    main()
