# Football Predictor

Betting model for European football: Dixon-Coles team ratings (goals + shots on target + Understat xG), calibration, value detection against bookmaker odds, a Streamlit app, and a SportyBet bet slip.

## Commands (run from this folder)
- Tests: `python -m unittest discover -s tests`
- App: `python -m streamlit run app.py` (then open http://localhost:8501)
- Backtest: `python -m predictor backtest --seasons 2024 2025`
- Refit calibration after model changes: `python -m predictor backtest --seasons 2023 2024 2025 --save-calibration`
- Predict a fixtures file: `python -m predictor predict examples/fixtures_example.csv`
- Predict the next days' fixtures, fetched online: `python -m predictor upcoming --days 3`
- Out-of-sample profit test (calibration fitted on the other seasons): add `--test-seasons 2025 2026` to `backtest`, or on saved results `python -m predictor profit output/backtest.csv --test-seasons 2025`
- One bookmaker vs the market's fair price, no model: `python -m predictor consensus`
- Save SportyBet's and the market's current odds to `data/odds_log/`: `python -m predictor snapshot` (a timer runs it on the VPS)

## Layout
- `predictor/data.py` results/stats/odds (football-data.co.uk), `xg.py` Understat xG, `news.py` injuries (API-Football, FPL)
- `predictor/fixtures.py` upcoming fixtures (football-data.co.uk fixtures.csv + Understat schedule), times converted to local
- `predictor/history.py` form and head-to-head over 10 seasons incl. neighbouring divisions; `picks.py` best picks per match
- `predictor/sportybet.py` SportyBet odds and booking codes (unofficial website API); `review.py` grades a day's picks (ESPN scores)
- `predictor/ratings.py` Dixon-Coles fit, `model.py` league model, `calibration.py`, `markets.py`
- `predictor/value.py` edges/stakes, `safety.py` play-safe filter, `slip.py` bet slips, `tracker.py` bet log
- `predictor/consensus.py` bookmaker-vs-market test and its decision rule (`promising`); `snapshot.py` SportyBet odds log
- `assets/loader.css` is the bouncing-football loading screen: a page-wide `.fp-loader` (markup at the top of app.py) shows while Streamlit's header has its running icon or connection badge (spinners inside a hidden tab are invisible), and every spinner becomes the same card on top with its message. Selectors match Streamlit 1.66's markup; recheck after upgrading Streamlit
- Bet of the day and Check a code are `st.fragment`s: their widgets rerun only that tab
- Understat outages: `xg` remembers a failed download for 30 min and reuses saved player/xG files, so one outage doesn't mean a retry per team
- SportyBet's feed sends at most 10 events per page: `sportybet.events` pages by `PAGE_SIZE = 10`
- SportyBet publishes its own margin-free probability per outcome: `prob:<market>` columns next to `odds:<market>`, `book_probs` on each analysed fixture; `acca.candidates` prefers them
- `sportybet.load_code` reads any booking code (`orders/share/{code}`); `predictor/doctor.py` analyses a code's legs and `improve` rebuilds it for the highest chance at a total odds ("Check a code" tab)
- `data/` is a local cache and the user's bets/settings (git-ignored; never commit it)

## Server (deploy/)
- The VPS runs the app with `PREDICTOR_SHARED=1` behind nginx basic auth; nginx passes the login in `X-Remote-User`.
- `odds-snapshot.timer` runs `predictor snapshot` every 2 hours (07:05–23:05 WAT); the log lives in `data/odds_log/` on the server.
- In shared mode nothing in the page may change shared state: no API keys, cache refreshes, backtests or calibration writes. Per-person data goes under `data/users/<login>/` (`user_dir()` in app.py).

## Rules
- Judge any model change with the walk-forward backtest, never on in-sample fit. A strategy is "promising" only by `consensus.promising` on seasons it wasn't tuned on (>= 150 bets, ROI > 2 standard errors above zero, positive closing-line value).
- Don't loosen the play-safe rules in `safety.py` or the staking caps in `value.py` unless the user asks.
- Never automate placing bets or logging into the bookmaker. Reading SportyBet's public odds and creating booking codes (`predictor/sportybet.py`, the visitor's "Book Bet") is allowed: neither logs in nor stakes anything.
