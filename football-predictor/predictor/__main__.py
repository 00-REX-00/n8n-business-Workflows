"""Command line: python -m predictor {predict,upcoming,review,backtest,profit,consensus,snapshot,ratings} ..."""
from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd

from . import backtest, calibration, consensus, data, fixtures, predict, review, snapshot, value
from .model import LeagueModel


def _verdict(s: dict) -> str:
    if consensus.promising(s):
        return "PROMISING: passes the decision rule (still confirm with tracked bets)"
    return (f"not promising (needs >= {consensus.MIN_BETS} bets, ROI above zero by 2 standard errors "
            "and positive closing-line value)")


def _print_profit(res: pd.DataFrame, test_seasons: list[int], leagues: list[str]) -> None:
    """Out-of-sample profit test of the app's rules, per source and per league."""
    extra = consensus.load(leagues, sorted(set(res["season"])))
    bets, ll = backtest.profit_test(res, test_seasons, extra)
    fit = sorted(set(res["season"]) - set(test_seasons))
    print(f"\nPROFIT TEST: calibration fitted on seasons {fit}, rules replayed on {test_seasons} "
          "(edge >= 5%, prob >= 25%, odds <= 4, edge <= 15%; flat 1 unit)")
    for source, label in (("closing", "at closing odds (Pinnacle first)"),
                          ("bet365", "at Bet365 pre-match odds (closer to a soft bookmaker when you bet)")):
        b = bets[bets["source"] == source]
        if b.empty:
            continue
        total = consensus.stats(b)
        print(f"\n{label}: {total['bets']} bets, ROI {total['roi_%']:+.1f}% "
              f"(+/- {total['roi_se_%']:.1f} standard error)")
        print(pd.DataFrame({m: consensus.stats(g) for m, g in b.groupby("market")}).T.round(3).to_string())
    lg = ll.groupby("league")[["model", "closing_odds"]].mean()
    lg["model_minus_odds"] = lg["model"] - lg["closing_odds"]
    b365 = bets[bets["source"] == "bet365"]
    table = lg.join(pd.DataFrame({k: consensus.stats(g) for k, g in b365.groupby("league")}).T
                    [["bets", "roi_%", "roi_se_%", "clv_%"]].add_prefix("bet365_"), how="left")
    table["matches"] = ll.groupby("league").size()
    print("\nPER LEAGUE: 1X2 log loss (lower is better; model_minus_odds < 0 means the model beat the "
          "closing odds) and value bets at Bet365 pre-match odds")
    print(table.round(4).sort_values("model_minus_odds").to_string())
    passed = [k for k, g in b365.groupby("league") if consensus.promising(consensus.stats(g))]
    print(f"\nLeagues passing the decision rule at Bet365 prices: {', '.join(passed) or 'none'}")
    if not b365.empty:
        print(f"All leagues together at Bet365 prices: {_verdict(consensus.stats(b365))}")
    print(f"1X2 log loss over {len(ll)} matches: model {ll['model'].mean():.4f}, "
          f"closing odds {ll['closing_odds'].mean():.4f}")


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
    b.add_argument("--test-seasons", nargs="+", type=int,
                   help="also run the out-of-sample profit test on these seasons (calibration fitted on the rest)")

    pt = sub.add_parser("profit", help="out-of-sample profit test on saved backtest results")
    pt.add_argument("results", nargs="+", type=Path, help="backtest CSV files, e.g. output/backtest.csv")
    pt.add_argument("--test-seasons", nargs="+", type=int, required=True)

    c = sub.add_parser("consensus", help="does one bookmaker paying more than the market average win? (no model)")
    c.add_argument("--leagues", nargs="+", default=list(data.LEAGUES))
    c.add_argument("--seasons", nargs="+", type=int, default=list(range(2019, data.current_season() + 1)))
    c.add_argument("--judge-from", type=int, default=2024,
                   help="first season used only to judge; earlier seasons choose the threshold")

    s = sub.add_parser("snapshot", help="save SportyBet's and the market's current odds to data/odds_log/")
    s.add_argument("--leagues", nargs="+", default=list(data.LEAGUES), choices=sorted(data.LEAGUES))

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
        if args.test_seasons:
            _print_profit(res, args.test_seasons, args.leagues)

    elif args.cmd == "profit":
        res = pd.concat([pd.read_csv(p, parse_dates=["date"]) for p in args.results], ignore_index=True)
        _print_profit(res, args.test_seasons, sorted(set(res["league"])))

    elif args.cmd == "consensus":
        df = consensus.load(args.leagues, args.seasons)
        print(f"{len(df)} matches, {df['league'].nunique()} leagues, seasons {min(args.seasons)}-{max(args.seasons)}. "
              f"Thresholds are chosen on seasons before {args.judge_from} and judged on the rest. "
              f"Odds up to {value.MAX_ODDS} (the app's limit); fair prices by the power method.")
        print("\nAVERAGE BOOKMAKER MARGIN PER LEAGUE (%): what a bet has to overcome")
        print(consensus.margins(df).round(2).to_string())
        for book, label in (("B365", "BET365 vs THE MARKET'S FAIR PRICE (one soft bookmaker, like SportyBet)"),
                            ("Max", "BEST PRICE vs THE MARKET'S FAIR PRICE (optimistic: best prices can be stale)")):
            for method in ("proportional", "power"):
                rows = consensus.edges(df, book, "Avg", method)
                rows = rows[rows["price"] <= value.MAX_ODDS]
                choose, judge = rows[rows["season"] < args.judge_from], rows[rows["season"] >= args.judge_from]
                t = consensus.pick_threshold(choose)
                if method == "proportional":   # the simpler margin removal, for comparison
                    s = consensus.stats(judge[judge["edge"] >= t])
                    plain = (f"With plain margin removal instead: min_edge {t:.0%}, judged {s['bets']} bets, "
                             f"ROI {s['roi_%']:+.1f}% +/- {s['roi_se_%']:.1f}: {_verdict(s)}")
            print(f"\n{label}")
            print("Choosing seasons (bet when price x fair probability - 1 >= min_edge):")
            print(consensus.summary(choose).round(3).to_string())
            s = consensus.stats(judge[judge["edge"] >= t])
            print(f"Chosen min_edge {t:.0%}. Judged on seasons >= {args.judge_from}: {s['bets']} bets, "
                  f"ROI {s['roi_%']:+.1f}% +/- {s['roi_se_%']:.1f}, closing-line value {s['clv_%']:+.2f}% "
                  f"(beat the close {s['beat_close_%']:.0f}% of the time)")
            print(f"Verdict: {_verdict(s)}")
            print(plain)
            print("Judged seasons by league:")
            print(consensus.breakdown(judge, t, "league").round(3).to_string())
            print("Judged seasons by season:")
            print(consensus.breakdown(judge, t, "season").round(3).to_string())

    elif args.cmd == "snapshot":
        sb, fd, notes = snapshot.take(args.leagues)
        for note in notes:
            print(f"note: {note}")
        paths = snapshot.save(sb, fd)
        unmatched = int((sb["home"].isna() | sb["away"].isna()).sum())
        print(f"SportyBet: {len(sb)} events ({unmatched} with names we couldn't match); "
              f"football-data.co.uk: {len(fd)} fixtures. Saved to {', '.join(map(str, paths)) or 'nothing'}")
        if not paths:
            raise SystemExit(1)

    elif args.cmd == "ratings":
        now = data.current_season()
        matches = data.load_matches([args.league], list(range(now - 3, now + 1)))
        lm = LeagueModel.fit(matches, args.league, pd.Timestamp.today())
        print(f"{data.LEAGUES[args.league]} ratings using results up to {lm.history['date'].max():%Y-%m-%d}")
        print(f"home advantage: x{math.exp(lm.goals.home_adv):.2f} goals")
        print(lm.goals.table().round(3).to_string())


if __name__ == "__main__":
    main()
