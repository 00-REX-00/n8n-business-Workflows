"""Log of bets placed, results and profit. Stored as a CSV in data/bets.csv."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "bets.csv"
COLUMNS = ["id", "placed_at", "match_date", "league", "home", "away", "market", "odds",
           "stake", "model_prob", "edge", "closing_odds", "result", "notes"]
RESULTS = ["pending", "won", "lost", "void"]


def load(path: Path = DEFAULT_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    for col in COLUMNS:
        if col not in df:
            df[col] = np.nan
    return df[COLUMNS]


def save(df: pd.DataFrame, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df[COLUMNS].to_csv(path, index=False)


def add(bet: dict, path: Path = DEFAULT_PATH) -> pd.DataFrame:
    df = load(path)
    row = {c: bet.get(c, np.nan) for c in COLUMNS}
    row["id"] = int(df["id"].max()) + 1 if len(df) else 1
    row["placed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    row["result"] = bet.get("result", "pending")
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save(df, path)
    return df


def with_profit(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    odds = pd.to_numeric(df["odds"], errors="coerce")
    stake = pd.to_numeric(df["stake"], errors="coerce").fillna(0)
    df["profit"] = np.select(
        [df["result"] == "won", df["result"] == "lost"],
        [stake * (odds - 1), -stake], 0.0)
    closing = pd.to_numeric(df["closing_odds"], errors="coerce")
    df["clv"] = odds / closing - 1
    return df


def summary(df: pd.DataFrame) -> dict:
    df = with_profit(df)
    settled = df[df["result"].isin(["won", "lost"])]
    staked = pd.to_numeric(settled["stake"], errors="coerce").sum()
    return {
        "bets": len(df),
        "settled": len(settled),
        "pending": int((df["result"] == "pending").sum()),
        "staked": staked,
        "profit": settled["profit"].sum(),
        "roi": settled["profit"].sum() / staked if staked else float("nan"),
        "hit_rate": (settled["result"] == "won").mean() if len(settled) else float("nan"),
        "avg_clv": df["clv"].mean(),
    }
