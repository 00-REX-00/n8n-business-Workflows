# Football Predictor

A betting model for the top 5 European leagues (more leagues ready to switch on). It gives a probability for each market, compares it with your bookmaker's odds (e.g. SportyBet), and only flags a bet when the odds pay more than the model thinks the bet is worth. Stake sizes are capped.

**Read "What the backtest says" before you stake money.**

## How it's built (and why)

```
 football-data.co.uk ──► predictor/ (Python model) ──► app.py (web app you use)
                                     │                 └─ command line (python -m predictor)
                                     └──► later: n8n workflow for schedules + Telegram alerts
```

- **The model is plain Python code**, not an n8n workflow. Statistical fitting, backtests and tests need real code: workflows can't be tested or tuned properly.
- **The web app (`app.py`, Streamlit)** is how you use it day to day: pick a match, type the SportyBet odds, see value bets, log them, track profit. It runs on your computer in the browser and needs no web development.
- **n8n comes later** for automation only: fetch fixtures every morning, run the model, send value picks to Telegram. It calls this code; it doesn't replace it.

## Web app

The app runs **on your own computer**: start it there, then open http://localhost:8501 in your browser (see [Setup](#setup)). On Windows, double-click `run_app.bat`; on Mac/Linux run `./run_app.sh`.

| Tab | What you do there |
|---|---|
| **Match analysis** | Choose teams, referee and **missing players**. You see expected goals, win/draw/loss, a likely-score grid, form and H2H. Type the bookmaker's odds next to the model's fair odds, and value bets appear with a stake, **Log bet** and **Add to slip** |
| **Fixture list** | Upload a CSV of the weekend's matches with odds to analyse them all at once, then add every value bet to the slip |
| **Bet slip** | Your picks under SportyBet's market names, singles vs. accumulator maths, warnings, and a copy list for booking on SportyBet |
| **Bet tracker** | Every logged bet: set won/lost, add closing odds, see profit, ROI, hit rate, closing-line value and a profit chart |
| **Team ratings** | Attack vs. defence chart and table for the league |
| **Model report** | Run the backtest from the browser: scorecard, calibration chart, "safe pick" table and, with odds data, the profit test |

## What it models

| Area | How |
|---|---|
| Team strength | Dixon-Coles ratings (attack and defence per team, home advantage), refitted on every prediction date. Recent games count more: a match a year ago weighs about a third as much as last week's |
| Chance quality | Ratings learn from a blend: 50% Understat expected goals (xG), 25% shots on target, 25% goals. xG measures chance quality, so it shows true strength faster than goals. Where xG is missing, goals and shots on target share the weight |
| Promoted teams | Start below league average instead of at average |
| Goal markets | A full scoreline probability table gives 1X2, double chance, draw no bet, over/under 0.5 to 4.5, team goals, both teams to score (BTTS) and clean sheets |
| Cards | Team card ratings × referee strictness (shrunk until the referee has enough games); spread modelled with a negative binomial |
| Corners | Team corner ratings (experimental, see below) |
| Calibration | A final correction learned from the backtest: the raw model was slightly timid on match results (favourites won more than it said) and overconfident on cards and corners. `models/calibration.json` fixes both |
| Missing players | Pick who's out; each player's share of the team's attack (their xG + xA per 90, Understat) lowers the team's expected goals, half-covered by the replacement. Haaland out ≈ Man City ×0.90. Extra manual multiplier for rotation etc. |
| Form and head-to-head | Printed for you to read; **not** used in the probabilities (see below) |

### Why head-to-head and "form" are shown but not used

Five past meetings are five noisy games, often with different players and managers. Recent form is already inside the ratings, which weight recent games more and use every opponent rather than just one. Adding H2H on top double-counts noise. That's why the report prints them but the numbers ignore them. Lineups do matter a lot, which is what the `*_adj` columns are for.

## What the backtest says

Walk-forward test of 3,492 matches (2024-25 and 2025-26 seasons, top 5 leagues). The model was refitted every week using only matches played before that week, so it never saw a result before predicting it.

| Market | Accuracy | Skill vs. always guessing the league average |
|---|---|---|
| 1X2 (backing the favourite) | 52.4% | good (on par with published models) |
| Double chance 1X / X2 | 70% / 66% | **+10%**: the model's strongest area |
| Home team over 0.5 / away team over 0.5 | 77% / 72% | +6% / +3% |
| Over 1.5 / 2.5 / 3.5 | 77% / 57% / 69% | +1% (small) |
| Cards over 3.5 / 4.5 | 60% / 61% | +1.9% (after tuning) |
| BTTS | 55% | ~0, no skill |
| Corners over 9.5 | 56% | ~0, no skill |

Calibration then improved every market when tested on a season it hadn't seen (fitted on 2023-24 and 2024-25, tested on 2025-26). Refit it after any model change with `python -m predictor backtest --seasons 2023 2024 2025 --save-calibration`.

The model never calls BTTS or corners a value bet (`NO_SKILL_PREFIXES` in `predictor/value.py`) until they're improved.

**"Safe" picks:** when the model rated something ≥ 85% likely:

| Pick | Picks | Actually won | Lowest odds that would have made a profit |
|---|---|---|---|
| Over 1.5 / under 1.5 | 393 | 85.5% | 1.17 |
| Home team to score | 641 | 92.5% | 1.08 |
| 1X double chance | 348 | 91.4% | 1.09 |

The model is reliable here: when it says 90%, it wins about 90% of the time. But bookmakers price these near 1.05–1.15, so the odds usually leave no profit. **High hit rate is not the same as profit.** That's why the tool compares with real odds instead of picking "sure" games.

**No profit test yet.** The data reachable in the build environment has no odds. On your machine, the data downloads straight from football-data.co.uk, which includes closing odds. Run the backtest there and it adds a "value bets at historical closing odds" table: the profit test that matters. Don't stake real money before you've seen that table.

## Setup

The app runs on your computer, not in the cloud. "localhost refused to connect" means it isn't running on your machine yet.

**Windows, first time:**

1. Install [Python 3.12](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"** in the installer.
2. Install [Git](https://git-scm.com/download/win).
3. Open **Command Prompt** and download the code (this branch):

   ```bash
   git clone -b claude/optimistic-hopper-kfj4ww https://github.com/00-REX-00/n8n-business-Workflows.git
   ```

4. Open the `n8n-business-Workflows\football-predictor` folder and double-click **`run_app.bat`**. The first start installs everything (a few minutes), then your browser opens http://localhost:8501. Keep the black window open while you use the app.
5. In the app, press **Refresh data** to load the current season.

**Getting updates later:** in Command Prompt, inside `n8n-business-Workflows`:

```bash
git pull
```

**Manual start (any system):**

```bash
cd football-predictor
```

```bash
pip install -r requirements.txt
```

```bash
python -m unittest discover -s tests
```

## Daily use

1. **Fill in the fixtures file.** Copy `examples/fixtures_example.csv` (its odds are made up) and fill in the matches and the SportyBet odds you see:

   | Column | Meaning |
   |---|---|
   | `league` | `E0` Premier League, `SP1` La Liga, `I1` Serie A, `D1` Bundesliga, `F1` Ligue 1 (others in `predictor/data.py`) |
   | `date`, `home`, `away` | Team names as SportyBet writes them are usually recognised. Unknown names show the closest matches, and you add them to `predictor/teams.py` |
   | `referee` | Optional. Improves the cards markets |
   | `home_missing`, `away_missing` | Optional. Players who are out, separated by `;` (surnames work: `Haaland; De Bruyne`) |
   | `home_adj`, `away_adj` | Optional, default 1.0. Extra multiplier on top: ~0.90 for heavy rotation, ~1.05 when the opponent's key defenders are out |
   | `odds:<market>` | Any of: `1 X 2 1X X2 12 dnb_1 dnb_2 over_1.5 under_1.5 over_2.5 under_2.5 over_3.5 under_3.5 home_over_0.5 away_over_0.5 home_over_1.5 away_over_1.5 btts_yes btts_no cards_over_3.5 cards_under_3.5 corners_over_9.5 …` |

2. **Run the prediction** once lineups are out (about 1 hour before kickoff):

   ```bash
   python -m predictor predict my_fixtures.csv --bankroll 50000
   ```

   For each match you get expected goals, likely scores, form, H2H, the model's probability and fair odds for each market, and any **VALUE** bets with a stake. "No value at these odds: no bet" is the most common output, and the right one.

3. **Log every bet** you place (date, market, odds, stake, result) and the odds at kickoff. After 200+ bets you'll know whether you have an edge. If your odds keep beating the kickoff odds, that's the best sign.

Other commands:

```bash
python -m predictor ratings E0
```

```bash
python -m predictor backtest --seasons 2024 2025
```

```bash
python -m predictor backtest --leagues N1 P1 E1 --seasons 2024 2025
```

## Staking rules built in (`predictor/value.py`)

- A bet needs ≥ 5% expected edge, model probability ≥ 25% and odds ≤ 4.0.
- Stake = quarter Kelly, capped at **2% of bankroll per bet**.
- A huge "edge" (say 15%+) on a big match usually means the model is missing news (an injury, a lineup change). Check before betting it.
- **Avoid accumulators.** Each leg carries the bookmaker's margin, so a 5-leg acca multiplies it five times. If you build one anyway, use only legs that each show value (`value.accumulator` computes the true odds).

## Being straight about money

Even very good betting models make a few percent return over hundreds of bets, with losing weeks along the way. That's not "millions over a weekend". Staking big to chase that is the fastest way to lose a bankroll. Use only money you can afford to lose. If the profit test on your machine shows no edge, don't bet with this model yet.

## SportyBet booking codes

SportyBet has no public API, so the app can't create booking codes itself. The **Bet slip** tab lists your picks under SportyBet's market names (1X2, Double Chance, Over/Under, GG/NG, Home Over/Under, …). Add them on sportybet.com/ng, open the betslip and press **Book Bet**; SportyBet gives you the code to save or share. Odds on SportyBet may differ from the ones you typed: if a price has dropped below the model's fair odds, remove that pick.

Accumulators: the slip shows the combined odds, real win chance and edge. Prefer singles. If you do combine, keep to 2–3 legs that each have value, never two picks from the same match, and stake at most 1% of bankroll.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Results, shots, corners, cards, referees, odds | football-data.co.uk (fallback: GitHub mirror for top 5, no odds) | Free |
| Team xG per match | understat.com (fallback: Premier League copy in vaastav/Fantasy-Premier-League, to 2024-25) | Free, top 5 leagues |
| Player xG / xA | understat.com (fallback: vibedatascience/understat_players_aggregated) | Free, top 5 leagues |

All downloads are cached in `data/raw/`.

## Roadmap

1. Run the backtest with odds on your machine (football-data.co.uk) to test whether it profits, then refit the calibration with xG for all 5 leagues: `python -m predictor backtest --seasons 2023 2024 2025 --save-calibration`.
2. Automatic lineups and injuries from API-Football (paid) instead of picking missing players by hand.
3. Test the second-wave leagues (Championship, Eredivisie, Portugal, Belgium, Scotland, Turkey, Greece). Bookmaker prices in smaller leagues are often less sharp.
4. n8n workflow in this repo: fetch fixtures → run model → send value picks to Telegram.
