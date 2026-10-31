"""Time-weighted Dixon-Coles team ratings.

log(home expected) = mu + home_adv + attack[home] + defence[away]
log(away expected) = mu            + attack[away] + defence[home]

`defence` is a weakness: higher means the team concedes more. Recent matches
weigh more (exponential decay `xi` per day). A ridge penalty pulls ratings
towards a prior, so teams with little data (newly promoted sides) start below
average instead of at average. With `dixon_coles=True` the low-score
correction `rho` is fitted too (goals); without it the model is a plain
double-Poisson rating model, which we reuse for corners and cards.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

# Ratings prior for teams not in the league last season (promoted sides).
PROMOTED_ATTACK = -0.20
PROMOTED_DEFENCE = 0.20


@dataclass
class TeamRatings:
    teams: list[str]
    attack: np.ndarray
    defence: np.ndarray
    mu: float
    home_adv: float
    rho: float

    def __post_init__(self):
        self.index = {t: i for i, t in enumerate(self.teams)}

    def has(self, team: str) -> bool:
        return team in self.index

    def expected(self, home: str, away: str) -> tuple[float, float]:
        h, a = self.index[home], self.index[away]
        lam = np.exp(self.mu + self.home_adv + self.attack[h] + self.defence[a])
        mu2 = np.exp(self.mu + self.attack[a] + self.defence[h])
        return float(lam), float(mu2)

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"attack": self.attack, "defence": self.defence,
             "net": self.attack - self.defence},
            index=self.teams,
        ).sort_values("net", ascending=False)


def _priors(train: pd.DataFrame, teams: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Promoted-team prior: teams absent from the previous season."""
    att = np.zeros(len(teams))
    dfn = np.zeros(len(teams))
    latest = train["season"].max()
    prev = train[train["season"] == latest - 1]
    if prev.empty:
        return att, dfn
    prev_teams = set(prev["home"]) | set(prev["away"])
    for i, t in enumerate(teams):
        if t not in prev_teams:
            att[i], dfn[i] = PROMOTED_ATTACK, PROMOTED_DEFENCE
    return att, dfn


def fit(
    train: pd.DataFrame,
    as_of: pd.Timestamp,
    home_col: str = "hg",
    away_col: str = "ag",
    xi: float = 0.0019,
    ridge: float = 4.0,
    dixon_coles: bool = True,
) -> TeamRatings:
    """Fit ratings on matches played before `as_of`."""
    train = train[(train["date"] < as_of)].dropna(subset=[home_col, away_col])
    teams = sorted(set(train["home"]) | set(train["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = train["home"].map(idx).to_numpy()
    ai = train["away"].map(idx).to_numpy()
    x = train[home_col].to_numpy(float)
    y = train[away_col].to_numpy(float)
    age = (as_of - train["date"]).dt.days.to_numpy(float)
    w = np.exp(-xi * age)
    prior_att, prior_def = _priors(train, teams)

    c00 = (x == 0) & (y == 0)
    c01 = (x == 0) & (y == 1)
    c10 = (x == 1) & (y == 0)
    c11 = (x == 1) & (y == 1)
    const = (w * (gammaln(x + 1) + gammaln(y + 1))).sum()

    def unpack(p):
        att = p[:n] - p[:n].mean() + prior_att.mean()
        dfn = p[n:2 * n] - p[n:2 * n].mean() + prior_def.mean()
        return att, dfn, p[2 * n], p[2 * n + 1], (p[2 * n + 2] if dixon_coles else 0.0)

    def objective(p):
        att, dfn, mu, home, rho = unpack(p)
        e1 = mu + home + att[hi] + dfn[ai]
        e2 = mu + att[ai] + dfn[hi]
        lam, lmu = np.exp(e1), np.exp(e2)
        ll = w * (x * e1 - lam + y * e2 - lmu)
        g1 = x - lam
        g2 = y - lmu
        grho = 0.0
        if dixon_coles:
            t = np.ones_like(lam)
            t[c00] = 1 - lam[c00] * lmu[c00] * rho
            t[c01] = 1 + lam[c01] * rho
            t[c10] = 1 + lmu[c10] * rho
            t[c11] = 1 - rho
            t = np.maximum(t, 1e-10)
            ll = ll + w * np.log(t)
            d = -lam[c00] * lmu[c00] * rho / t[c00]
            g1[c00] += d
            g2[c00] += d
            g1[c01] += lam[c01] * rho / t[c01]
            g2[c10] += lmu[c10] * rho / t[c10]
            grho = (w[c00] * -lam[c00] * lmu[c00] / t[c00]).sum() \
                + (w[c01] * lam[c01] / t[c01]).sum() \
                + (w[c10] * lmu[c10] / t[c10]).sum() \
                + (w[c11] * -1 / t[c11]).sum()
        g1 *= w
        g2 *= w
        g_att = np.bincount(hi, g1, n) + np.bincount(ai, g2, n)
        g_def = np.bincount(ai, g1, n) + np.bincount(hi, g2, n)
        # ridge towards the prior
        pen = 0.5 * ridge * (((att - prior_att) ** 2).sum() + ((dfn - prior_def) ** 2).sum())
        g_att -= ridge * (att - prior_att)
        g_def -= ridge * (dfn - prior_def)
        # chain rule through the centring in unpack()
        g_att -= g_att.mean()
        g_def -= g_def.mean()
        grad = [g_att, g_def, [g1.sum() + g2.sum()], [g1.sum()]]
        if dixon_coles:
            grad.append([grho])
        nll = -(ll.sum() - const - pen)
        return nll, -np.concatenate(grad)

    mean_goals = max(np.average((x + y) / 2, weights=w), 0.1)
    p0 = np.concatenate([prior_att, prior_def, [np.log(mean_goals), 0.25]] + ([[0.0]] if dixon_coles else []))
    bounds = [(-3, 3)] * (2 * n) + [(-5, 5), (-1, 1)] + ([(-0.25, 0.25)] if dixon_coles else [])
    res = minimize(objective, p0, jac=True, method="L-BFGS-B", bounds=bounds)
    att, dfn, mu, home, rho = unpack(res.x)
    return TeamRatings(teams, att, dfn, float(mu), float(home), float(rho))


def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = 10) -> np.ndarray:
    """P(home scores i, away scores j) with the Dixon-Coles low-score correction."""
    from scipy.stats import poisson

    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    m[0, 0] *= 1 - lam * mu * rho
    m[0, 1] *= 1 + lam * rho
    m[1, 0] *= 1 + mu * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()
