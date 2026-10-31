# Football Predictor

Betting model for European football: Dixon-Coles team ratings (goals + shots on target + Understat xG), calibration, value detection against bookmaker odds, a Streamlit app, and a SportyBet bet slip.

## Commands (run from this folder)
- Tests: `python -m unittest discover -s tests`
- App: `python -m streamlit run app.py` (then open http://localhost:8501)
- Backtest: `python -m predictor backtest --seasons 2024 2025`
- Refit calibration after model changes: `python -m predictor backtest --seasons 2023 2024 2025 --save-calibration`
- Predict a fixtures file: `python -m predictor predict examples/fixtures_example.csv`
- Predict the next days' fixtures, fetched online: `python -m predictor upcoming --days 3`

## Layout
- `predictor/data.py` results/stats/odds (football-data.co.uk), `xg.py` Understat xG, `news.py` injuries (API-Football, FPL)
- `predictor/fixtures.py` upcoming fixtures (football-data.co.uk fixtures.csv + Understat schedule), times converted to local
- `predictor/history.py` form and head-to-head over 10 seasons incl. neighbouring divisions; `picks.py` best picks per match
- `predictor/sportybet.py` SportyBet odds and booking codes (unofficial website API); `review.py` grades a day's picks (ESPN scores)
- `predictor/ratings.py` Dixon-Coles fit, `model.py` league model, `calibration.py`, `markets.py`
- `predictor/value.py` edges/stakes, `safety.py` play-safe filter, `slip.py` bet slips, `tracker.py` bet log
- `data/` is a local cache and the user's bets/settings (git-ignored; never commit it)

## Server (deploy/)
- The VPS runs the app with `PREDICTOR_SHARED=1` behind nginx basic auth; nginx passes the login in `X-Remote-User`.
- In shared mode nothing in the page may change shared state: no API keys, cache refreshes, backtests or calibration writes. Per-person data goes under `data/users/<login>/` (`user_dir()` in app.py).

## Rules
- Judge any model change with the walk-forward backtest, never on in-sample fit.
- Don't loosen the play-safe rules in `safety.py` or the staking caps in `value.py` unless the user asks.
- Never automate placing bets or logging into the bookmaker. Reading SportyBet's public odds and creating booking codes (`predictor/sportybet.py`, the visitor's "Book Bet") is allowed: neither logs in nor stakes anything.
