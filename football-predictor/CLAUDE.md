# Football Predictor

Betting model for European football: Dixon-Coles team ratings (goals + shots on target + Understat xG), calibration, value detection against bookmaker odds, a Streamlit app, and a SportyBet bet slip.

## Commands (run from this folder)
- Tests: `python -m unittest discover -s tests`
- App: `python -m streamlit run app.py` (then open http://localhost:8501)
- Backtest: `python -m predictor backtest --seasons 2024 2025`
- Refit calibration after model changes: `python -m predictor backtest --seasons 2023 2024 2025 --save-calibration`
- Predict a fixtures file: `python -m predictor predict examples/fixtures_example.csv`

## Layout
- `predictor/data.py` results/stats/odds (football-data.co.uk), `xg.py` Understat xG, `news.py` injuries (API-Football, FPL)
- `predictor/ratings.py` Dixon-Coles fit, `model.py` league model, `calibration.py`, `markets.py`
- `predictor/value.py` edges/stakes, `safety.py` play-safe filter, `slip.py` bet slips, `tracker.py` bet log
- `data/` is a local cache and the user's bets/settings (git-ignored; never commit it)

## Rules
- Judge any model change with the walk-forward backtest, never on in-sample fit.
- Don't loosen the play-safe rules in `safety.py` or the staking caps in `value.py` unless the user asks.
- Never automate placing bets or logging into the bookmaker.
