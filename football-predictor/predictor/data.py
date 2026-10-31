"""Load historical match data (results, match stats, closing odds).

Primary source: football-data.co.uk (free CSVs, results + shots + corners +
cards + referee + bookmaker odds, including Pinnacle closing odds).
Fallback: the GitHub mirror at github.com/datasets/football-datasets, which has
results and match stats for the top 5 leagues but no odds.
"""
from __future__ import annotations

import io
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

# football-data.co.uk league codes. The top 5 also exist on the GitHub mirror.
LEAGUES = {
    "E0": "Premier League",
    "SP1": "La Liga",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
    # Second wave (football-data.co.uk only)
    "E1": "Championship",
    "N1": "Eredivisie",
    "P1": "Primeira Liga",
    "B1": "Belgian Pro League",
    "T1": "Super Lig",
    "SC0": "Scottish Premiership",
    "D2": "2. Bundesliga",
    "I2": "Serie B",
    "SP2": "La Liga 2",
    "F2": "Ligue 2",
    "G1": "Greek Super League",
}
TOP5 = ["E0", "SP1", "I1", "D1", "F1"]

MIRROR_SLUGS = {
    "E0": "premier-league",
    "SP1": "la-liga",
    "I1": "serie-a",
    "D1": "bundesliga",
    "F1": "ligue-1",
}

FD_URL = "https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"
MIRROR_URL = (
    "https://raw.githubusercontent.com/datasets/football-datasets/master/"
    "datasets/{slug}/season-{code}.csv"
)

DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "data" / "raw"

# Odds columns in football-data.co.uk files, best first: Pinnacle closing,
# market-average closing, Bet365 pre-match.
ODDS_PREFERENCE = {
    "odds:1": ["PSCH", "AvgCH", "B365H"],
    "odds:X": ["PSCD", "AvgCD", "B365D"],
    "odds:2": ["PSCA", "AvgCA", "B365A"],
    "odds:over_2.5": ["PC>2.5", "AvgC>2.5", "B365>2.5"],
    "odds:under_2.5": ["PC<2.5", "AvgC<2.5", "B365<2.5"],
}

STAT_COLUMNS = {
    "FTHG": "hg", "FTAG": "ag", "HTHG": "hthg", "HTAG": "htag",
    "HS": "hs", "AS": "as", "HST": "hst", "AST": "ast",
    "HF": "hf", "AF": "af", "HC": "hc", "AC": "ac",
    "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
}


def season_code(start_year: int) -> str:
    """2025 -> '2526'."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def current_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "football-predictor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _fetch_raw(league: str, season: int, cache_dir: Path, refresh: bool) -> pd.DataFrame:
    code = season_code(season)
    cache = cache_dir / f"{league}_{code}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache)

    urls = [FD_URL.format(code=code, league=league)]
    if league in MIRROR_SLUGS:
        urls.append(MIRROR_URL.format(slug=MIRROR_SLUGS[league], code=code))

    errors = []
    for url in urls:
        try:
            text = _decode(_download(url))
        except Exception as exc:  # network blocked, 404 for a future season, ...
            errors.append(f"{url}: {exc}")
            continue
        df = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
        return df
    raise RuntimeError(f"Could not load {league} {code}:\n  " + "\n  ".join(errors))


def _parse_dates(col: pd.Series) -> pd.Series:
    """football-data.co.uk uses dd/mm/yy or dd/mm/yyyy; the mirror uses ISO."""
    col = col.astype(str).str.strip()
    out = pd.to_datetime(col, format="%Y-%m-%d", errors="coerce")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        out = out.fillna(pd.to_datetime(col, format=fmt, errors="coerce"))
    return out


def _normalise(df: pd.DataFrame, league: str, season: int) -> pd.DataFrame:
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    out = pd.DataFrame({
        "date": _parse_dates(df["Date"]),
        "league": league,
        "season": season,
        "home": df["HomeTeam"].astype(str).str.strip(),
        "away": df["AwayTeam"].astype(str).str.strip(),
        "referee": df["Referee"].astype(str).str.strip() if "Referee" in df else None,
    })
    out.loc[out["referee"].isin(["nan", "None", ""]), "referee"] = None
    for src, dst in STAT_COLUMNS.items():
        out[dst] = pd.to_numeric(df[src], errors="coerce") if src in df else float("nan")
    for dst, candidates in ODDS_PREFERENCE.items():
        col = pd.Series(float("nan"), index=df.index)
        for src in candidates:
            if src in df:
                col = col.fillna(pd.to_numeric(df[src], errors="coerce"))
        out[dst] = col
    return out.dropna(subset=["date", "hg", "ag"])


def load_matches(
    leagues: list[str],
    seasons: list[int],
    cache_dir: Path = DEFAULT_CACHE,
    refresh_current: bool = True,
) -> pd.DataFrame:
    """All finished matches for the given leagues and season start years."""
    frames = []
    now = current_season()
    for league in leagues:
        for season in seasons:
            try:
                raw = _fetch_raw(league, season, cache_dir, refresh=refresh_current and season == now)
            except RuntimeError as exc:
                print(f"warning: {exc}")
                continue
            frames.append(_normalise(raw, league, season))
    if not frames:
        raise RuntimeError("No match data could be loaded.")
    matches = pd.concat(frames, ignore_index=True)
    return matches.sort_values(["date", "league", "home"]).reset_index(drop=True)
