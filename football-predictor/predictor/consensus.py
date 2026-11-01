"""One bookmaker against the market: does a price above the market's fair
price win money, with no model involved?

The market's fair price is the average odds across bookmakers with the margin
removed. When one bookmaker pays more than that, the bet has an edge if the
market average is right. This replays that rule on football-data.co.uk's
historical odds:
  - Bet365 against the average: the realistic case of one soft bookmaker
    (like SportyBet) being out of line with the rest.
  - Best price against the average (the "Kaunitz" rule): optimistic, because
    the best price can be a stale quote nobody could actually take.
Pre-match prices are all collected at the same moment, so the rule only uses
what was known when betting. Closing-line value (the price against the fair
closing price) is reported too: it is a far less noisy sign of a real edge
than profit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data, markets

# football-data.co.uk columns per odds source, in MARKETS order.
SOURCES = {
    "B365": ("B365H", "B365D", "B365A", "B365>2.5", "B365<2.5"),
    "Avg": ("AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"),
    "Max": ("MaxH", "MaxD", "MaxA", "Max>2.5", "Max<2.5"),
    "PS": ("PSH", "PSD", "PSA", "P>2.5", "P<2.5"),
    "B365C": ("B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5"),
    "AvgC": ("AvgCH", "AvgCD", "AvgCA", "AvgC>2.5", "AvgC<2.5"),
    "MaxC": ("MaxCH", "MaxCD", "MaxCA", "MaxC>2.5", "MaxC<2.5"),
    "PSC": ("PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5"),
}
MARKETS = ("1", "X", "2", "over_2.5", "under_2.5")
GROUPS = (("1", "X", "2"), ("over_2.5", "under_2.5"))
CLOSING = ("PSC", "AvgC")    # fair closing price: Pinnacle first, else the market average
THRESHOLDS = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)
# A strategy only counts as promising with at least this many bets in the
# seasons it is judged on, ROI above zero by 2 standard errors and positive
# average closing-line value.
MIN_BETS = 150


def load(leagues: list[str], seasons: list[int], cache_dir=data.DEFAULT_CACHE) -> pd.DataFrame:
    """Finished matches with every source's odds as `<source>:<market>` columns."""
    frames = []
    for league in leagues:
        for season in seasons:
            try:
                raw = data._fetch_raw(league, season, cache_dir, refresh=False)
            except RuntimeError as exc:
                print(f"warning: {exc}")
                continue
            raw = raw.dropna(subset=["HomeTeam", "AwayTeam"])
            out = pd.DataFrame({
                "date": data._parse_dates(raw["Date"]), "league": league, "season": season,
                "home": raw["HomeTeam"].astype(str).str.strip(),
                "away": raw["AwayTeam"].astype(str).str.strip(),
                "hg": pd.to_numeric(raw["FTHG"], errors="coerce"),
                "ag": pd.to_numeric(raw["FTAG"], errors="coerce"),
            })
            for source, cols in SOURCES.items():
                for market, col in zip(MARKETS, cols):
                    out[f"{source}:{market}"] = pd.to_numeric(raw[col], errors="coerce") if col in raw else np.nan
            frames.append(out.dropna(subset=["date", "hg", "ag"]))
    if not frames:
        raise RuntimeError("No match data could be loaded.")
    return pd.concat(frames, ignore_index=True)


def _power(implied: np.ndarray) -> np.ndarray:
    """Margin removal by the power method: fair_i = implied_i ** k, with k set
    so they sum to one. It takes more margin off long shots than favourites, as
    bookmakers price them (the favourite-longshot bias). Plain normalising
    spreads the margin evenly, which makes long shots look likelier than they
    are and invents "edges" on them."""
    lo, hi = np.full(len(implied), 0.5), np.full(len(implied), 5.0)
    for _ in range(50):
        k = (lo + hi) / 2
        over = (implied ** k[:, None]).sum(axis=1) > 1
        lo, hi = np.where(over, k, lo), np.where(over, hi, k)
    return implied ** ((lo + hi) / 2)[:, None]


def fair(df: pd.DataFrame, source: str, method: str = "power") -> pd.DataFrame:
    """Margin-removed probabilities from one source (NaN where a market's
    outcomes aren't all priced). method "proportional" is value.market_probs'
    plain normalising; "power" corrects for the favourite-longshot bias."""
    out = pd.DataFrame(index=df.index)
    for group in GROUPS:
        implied = pd.DataFrame({m: 1 / df[f"{source}:{m}"].where(df[f"{source}:{m}"] > 1) for m in group})
        if method == "power":
            probs = pd.DataFrame(_power(implied.to_numpy()), index=df.index, columns=list(group))
        else:
            probs = implied.div(implied.sum(axis=1, min_count=len(group)), axis=0)
        for m in group:
            out[m] = probs[m]
    return out


def edges(df: pd.DataFrame, book: str = "B365", reference: str = "Avg", method: str = "power") -> pd.DataFrame:
    """One row per (match, market) that `book` priced: its price, the
    reference's fair probability, the edge, the result and closing-line value."""
    ref = fair(df, reference, method)
    close = fair(df, CLOSING[0], method)
    for source in CLOSING[1:]:
        close = close.fillna(fair(df, source, method))
    rows = pd.concat([pd.DataFrame({
        "date": df["date"], "league": df["league"], "season": df["season"],
        "home": df["home"], "away": df["away"], "hg": df["hg"], "ag": df["ag"], "market": m,
        "price": df[f"{book}:{m}"], "p_ref": ref[m], "p_close": close[m],
    }) for m in MARKETS], ignore_index=True)
    rows = rows[(rows["price"] > 1) & rows["p_ref"].notna()].copy()
    rows["won"] = [markets.outcome(m, {"hg": h, "ag": a})
                   for m, h, a in zip(rows["market"], rows["hg"], rows["ag"])]
    rows["edge"] = rows["price"] * rows["p_ref"] - 1
    rows["clv"] = rows["price"] * rows["p_close"] - 1
    rows["profit"] = np.where(rows["won"] == 1, rows["price"] - 1, -1.0)
    return rows.drop(columns=["hg", "ag"]).reset_index(drop=True)


def stats(bets: pd.DataFrame, price_col: str = "price") -> dict:
    """Bets, hit rate, ROI with its standard error, and closing-line value."""
    profit = bets["profit"]
    clv = bets["clv"].dropna() if "clv" in bets else pd.Series(dtype=float)
    n = len(bets)
    return {
        "bets": n,
        "hit_rate": bets["won"].mean() if n else np.nan,
        "avg_odds": bets[price_col].mean() if n else np.nan,
        "roi_%": 100 * profit.mean() if n else np.nan,
        "roi_se_%": 100 * profit.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan,
        "clv_%": 100 * clv.mean() if len(clv) else np.nan,
        "beat_close_%": 100 * (clv > 0).mean() if len(clv) else np.nan,
    }


def promising(s: dict) -> bool:
    """The decision rule fixed before looking at results (see MIN_BETS)."""
    clv_ok = np.isnan(s["clv_%"]) or s["clv_%"] > 0
    return bool(s["bets"] >= MIN_BETS and s["roi_%"] - 2 * s["roi_se_%"] > 0 and clv_ok)


def summary(rows: pd.DataFrame, thresholds=THRESHOLDS) -> pd.DataFrame:
    """Stats for betting every row whose edge is at least each threshold."""
    out = [{"min_edge": t, **stats(rows[rows["edge"] >= t])} for t in thresholds]
    return pd.DataFrame(out).set_index("min_edge")


def breakdown(rows: pd.DataFrame, min_edge: float, key: str) -> pd.DataFrame:
    bets = rows[rows["edge"] >= min_edge]
    return pd.DataFrame({k: stats(g) for k, g in bets.groupby(key)}).T


def pick_threshold(rows: pd.DataFrame, thresholds=THRESHOLDS) -> float:
    """The threshold with the best ROI among those with enough bets."""
    s = summary(rows, thresholds)
    s = s[s["bets"] >= MIN_BETS]
    return float(s["roi_%"].idxmax()) if not s.empty else float(thresholds[-1])


def margins(df: pd.DataFrame) -> pd.DataFrame:
    """Average bookmaker margin per league (%): what a bet has to overcome."""
    out = pd.DataFrame({"league": df["league"]})
    for source in ("B365", "Avg", "PS"):
        for name, group in (("1X2", GROUPS[0]), ("O/U 2.5", GROUPS[1])):
            out[f"{source} {name}"] = 100 * (sum(1 / df[f"{source}:{m}"].where(df[f"{source}:{m}"] > 1)
                                                 for m in group) - 1)
    return out.groupby("league").mean()
