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
| **Match analysis** | Pick one of the league's upcoming fixtures (or any two teams), the referee and **missing players**. You see expected goals, win/draw/loss, a likely-score grid, form and H2H. Each market shows the model's fair odds, the **Bet at odds** range and the bookmaker average; type SportyBet's odds and value bets appear with a stake, **Log bet** and **Add to slip** |
| **Fixtures** | Loads itself: every match in the chosen competitions for today or the next 2–7 days, fetched online, with probabilities, bookmaker average odds and value bets at those odds. Pick any match for the full breakdown. Uploading your own CSV with SportyBet odds still works underneath |
| **Bet of the day** | An accumulator near your target odds (default 10) from all 16 leagues, built for the highest chance of winning, with one click to a SportyBet booking code. **Mega odds** builds one big ticket (1,000+ odds) from up to two weeks of matches. See [Bet of the day](#bet-of-the-day) |
| **Results** | Pick a day: every finished match with the model's call, the bookmaker favourite, the top pick and the value bets graded against the final score (ESPN), plus how many wins the model expected. Predictions are rebuilt from data before that day, so the model never sees the scores. Same from the command line: `python -m predictor review --date 2026-10-31` |
| **Bet slip** | Your picks, singles vs. accumulator maths and warnings. **Get SportyBet booking code** books the slip on SportyBet and gives you the code; a copy list under SportyBet's market names is the fallback |
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
| Form and head-to-head | Shown for you to read, with date, opponent and score, newest first; **not** used in the probabilities (see below). Head-to-head covers 10 seasons of league meetings including the division above or below, so meetings from before a promotion appear. Cup games aren't in the data |
| Best picks | For each match, the model's most likely outcomes in markets where the backtest showed skill (result, double chance, team to score, total goals), skipping anything above 80% because those pay too little. Each comes with the odds range where it's value; below that range a pick can win often and still lose money. The play-safe rules withhold picks the same way as value bets (`predictor/picks.py`) |

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

**Profit test (run October 2026, with closing odds).** To keep it honest, the calibration was refitted on 2023-24 and 2024-25 only, then the app's exact rules (edge ≥ 5%, probability ≥ 25%, odds ≤ 4.0, edge ≤ 15%) were replayed on 2,158 matches it had never seen (2025-26 and 2026-27 so far), at football-data.co.uk's closing odds (Pinnacle first):

| | Bets | Result |
|---|---|---|
| Value bets, all | 1,160 | **−8.0% ROI** (−92.8 units at level stakes) |
| Home win / away win / draw | 203 / 242 / 114 | −22.7% / −17.8% / −4.6% |
| Over 2.5 / under 2.5 | 387 / 214 | +1.6% / −2.2% |
| Edge 5–10% vs 10–15% | 719 / 441 | −4.7% vs −13.4% |
| Top picks (one per match) | 2,158 | won 74.1%, model expected 75.6% |
| Picks whose closing odds were inside "bet at" | 139 | +10.6% (too few to tell skill from luck) |

Bookmakers' closing odds were also more accurate than the model on match results (log loss 0.973 vs 0.987). What it means: the model's probabilities are honest (picks win about as often as it says), but it does not beat the bookmakers, and betting its "value" signals lost money. Bigger edges lost more, so the gaps between model and market are mostly model error. Until that changes, treat the app as an analysis tool, stake small or not at all, and let the Bet tracker's closing-line value tell you whether you have an edge. Rerun: `python -m predictor backtest --seasons 2024 2025`, then `python -m predictor profit output/backtest.csv --test-seasons 2025`.

At Bet365's pre-match prices (closer to what a soft bookmaker like SportyBet offers when you bet) the same rules lost 7.9% over 1,019 bets, and those bets were on average 5% worse than the fair closing price.

**Decision rule for every test below**, fixed before looking at results: thresholds and calibration are chosen on earlier seasons and judged only on later ones, and a strategy counts as promising only with at least 150 judged bets, ROI above zero by more than 2 standard errors and positive closing-line value.

### Smaller leagues (November 2026)

Smaller leagues get less attention from bookmakers, so they're the obvious place to look for soft prices. The same walk-forward test on 17 of them (the 11 smaller leagues in the app plus League One, League Two, the National League and the three Scottish divisions below the Premiership), calibration fitted on 2023-24 and 2024-25 and judged on 7,428 matches from 2025-26 and 2026-27:

| | Result |
|---|---|
| 1X2 log loss, model vs closing odds | 1.028 vs 1.006: the odds were more accurate **in all 17 leagues** |
| Value bets at closing odds | 3,278 bets, **−8.5%** (± 2.1) |
| Value bets at Bet365 pre-match odds | 3,160 bets, **−6.7%** (± 2.2); 5–8% worse than the fair closing price in every league |
| Leagues passing the decision rule | none |

The bookmakers also protect themselves: the average margin on a 1X2 market is about 4.5–5% in the top 5 leagues but 7–9% in the Greek league, the National League and the lower Scottish divisions. Without xG or team news there, the model knows less than in the big leagues, not more. Rerun: `python -m predictor backtest --leagues E1 N1 P1 B1 T1 SC0 D2 I2 SP2 F2 G1 E2 E3 EC SC1 SC2 SC3 --seasons 2023 2024 2025 2026 --test-seasons 2025 2026`.

### One bookmaker against the market (no model)

Another route needs no model at all: when one bookmaker pays more than the market's fair price (the average odds across bookmakers, margin removed), the bet has an edge if the market is right. `python -m predictor consensus` replays this on 55,357 matches in 22 leagues (2019-20 to 2026-27, odds up to 4.0). Threshold chosen on 2019–2023, judged on 2024 onwards:

| Rule | Judged bets | ROI | Closing-line value | Verdict |
|---|---|---|---|---|
| Bet365 ≥ 2% above the fair price | 29 | +20.9% (± 29.2) | +2.7% | too few bets: Bet365 is rarely out of line |
| Best price anywhere ≥ 6% above the fair price | 106 | +24.6% (± 12.9) | +17.2%, beat the close 91% of the time | close, but not passing |

The second row is the only real signal so far, and it matches published research (Kaunitz et al., 2017): prices far above the market's fair price do tend to win. But the best price across 40+ bookmakers is often a stale quote that no single bookmaker would honour, and bookmakers limit accounts that keep taking such prices. The useful question is whether **SportyBet** is ever that far out of line. That's what the [odds log](#odds-log) is collecting data for.

The fair price uses the power method of removing the margin, which takes more margin off long shots than favourites. Plain normalising made long shots look likelier than they are and invented edges on them; it gives the same verdicts.

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

## Run it on your VPS (you and invited friends)

`deploy/` puts the app on a Linux VPS (Ubuntu or Debian, 2 GB RAM or more) at your own address, behind a login. Only people you add can open it.

On the server the app runs in **shared mode**: no API key field, no Refresh data, no backtest or calibration buttons, so nobody can change the model. Each login gets its own bankroll and bet log (`data/users/<login>/`); the bet slip is per browser session. Times are Nigerian (WAT).

1. **Point a subdomain at the VPS.** In your domain's DNS settings (at your web host, or Contabo's DNS Management), add an **A record**: name `predictor` (or anything), value = your VPS's IP address. Wait until `predictor.yourdomain.com` resolves.
2. **Log in to the VPS** from PowerShell on your PC: `ssh root@YOUR_VPS_IP`
3. **Install** (asks you to choose your own login password; takes 10–15 minutes including the first data download):

   ```bash
   apt-get update && apt-get install -y git
   git clone -b claude/optimistic-hopper-kfj4ww https://github.com/00-REX-00/n8n-business-Workflows.git /tmp/fp
   bash /tmp/fp/football-predictor/deploy/setup.sh predictor.yourdomain.com you@email.com yourname
   ```

4. **Open** `https://predictor.yourdomain.com` and log in.

Add or remove friends (each gets their own login and password; changes apply at once):

```bash
bash /opt/predictor/football-predictor/deploy/friends.sh add tunde
```

```bash
bash /opt/predictor/football-predictor/deploy/friends.sh remove tunde
```

**Updating:** push your changes to the branch on GitHub, then on the VPS run `bash /opt/predictor/football-predictor/deploy/update.sh`.

**Owner-only jobs** run on the server's command line, from `/opt/predictor/football-predictor` as the app user, e.g. a new backtest: `runuser -u predictor -- ../venv/bin/python -m predictor backtest --seasons 2024 2025`. A paid API-Football key goes in the service, never in the page: `systemctl edit football-predictor`, add `[Service]` and `Environment=API_FOOTBALL_KEY=yourkey`, then `systemctl restart football-predictor`.

## Daily use

**In the app:** open **Fixtures**. The next three days' matches load themselves (football-data.co.uk for every league, plus Understat's schedule for the top 5). For each market, **Bet at odds** is the range of odds where a bet is value and passes the play-safe rules: if SportyBet's price falls inside it, it's a candidate. Below it there's no value; above it the edge is over 15% and the model is probably missing news.

**From the command line** (also what an n8n schedule would call):

```bash
python -m predictor upcoming --days 3 --bankroll 50000
```

Value bets there use the bookmaker average odds from football-data.co.uk; SportyBet often pays a little less, so check its price before betting.

**With your own odds file:**

1. **Fill in the fixtures file.** Copy `examples/fixtures_example.csv` (its odds are made up) and fill in the matches and the SportyBet odds you see:

   | Column | Meaning |
   |---|---|
   | `league` | `E0` Premier League, `SP1` La Liga, `I1` Serie A, `D1` Bundesliga, `F1` Ligue 1 (others in `predictor/data.py`) |
   | `date`, `home`, `away` | Team names as SportyBet writes them are usually recognised. Unknown names show the closest matches, and you add them to `predictor/teams.py` |
   | `referee` | Optional. Improves the cards markets |
   | `home_missing`, `away_missing` | Optional. Players who are out, separated by `;` (surnames work: `Haaland; De Bruyne`). Added to the ones team news finds |
   | `news_checked` | Optional. `yes` if you checked team news yourself; otherwise picks need an automatic news source |
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
python -m predictor backtest --leagues N1 P1 E1 --seasons 2023 2024 2025 --test-seasons 2025
```

```bash
python -m predictor consensus
```

```bash
python -m predictor snapshot
```

## Play-safe rules (`predictor/safety.py`)

A value bet only becomes a pick if it passes all three:

1. **No news, no bet.** The app looks up injuries and suspensions for every fixture: Fantasy Premier League for the Premier League (free, no key), and API-Football for other leagues. API-Football's free plan only covers the 2022–2024 seasons, so current team news outside the Premier League needs a paid plan ([dashboard.api-football.com](https://dashboard.api-football.com)). Other free sources tested in October 2026 didn't work: ESPN's feed has no football injuries, Sofascore blocks programs, LaLiga Fantasy's feed was down. Players who are out are applied automatically. If no source answers, the fixture's picks are **withheld**. You can override with "I've checked the team news myself" in Match analysis (`news_checked=yes` column in the fixtures file).
2. **Key player doubtful → no bet.** If a player with ≥10% of their team's attack is doubtful, the model can't know whether they play, so the fixture is skipped.
3. **Edge above 15% → no bet.** Real edges are small; a huge one almost always means the model is missing something (motivation, rotation, late news).

Withheld picks are listed with the reason, so you can see what was skipped.

## Staking rules built in (`predictor/value.py`)

- A bet needs ≥ 5% expected edge, model probability ≥ 25% and odds ≤ 4.0.
- Stake = quarter Kelly, capped at **2% of bankroll per bet**.
- A huge "edge" (say 15%+) on a big match usually means the model is missing news (an injury, a lineup change). Check before betting it.
- **Avoid accumulators.** Each leg carries the bookmaker's margin, so a 5-leg acca multiplies it five times. If you build one anyway, use only legs that each show value (`value.accumulator` computes the true odds).

## Being straight about money

Even very good betting models make a few percent return over hundreds of bets, with losing weeks along the way. That's not "millions over a weekend". Staking big to chase that is the fastest way to lose a bankroll. Use only money you can afford to lose. If the profit test on your machine shows no edge, don't bet with this model yet.

## Bet of the day

Pick the day and how likely each leg must be (default 65%). Every leg must be rated at least that likely by **both** SportyBet's own odds (margin removed) and the model, pass the play-safe rules, and come from a different match. For each ticket the app searches every combination for the one whose total odds land between the target and 35% above it with the **highest chance that every leg wins** (`predictor/acca.py`), shows that chance, and books it on SportyBet with one click. Each ticket gets its own booking code.

- **Best from all leagues** (default 10 odds): the best ticket, plus a 2nd and 3rd best that use different matches.
- **One per league** (default 3 odds, since a league usually has only a few matches a day): the best ticket within each league. Leagues that can't reach the target that day are listed as "no solid bet today". A typical 3-odds league ticket wins about 1 time in 3.5.
- **Mega odds** (switch at the top of the tab): one ticket of hundreds or thousands of odds from up to 14 days of matches, up to 40 legs, plus two alternatives that use different matches. SportyBet lists matches about a week ahead, so in practice that's the window. Same rules per leg and the same search. On 1 November 2026 (195 matches over the next week) it found:

  | Total odds | Legs | Chance it wins | Back per ₦100 on average |
  |---|---|---|---|
  | 1,000 | 21 | 1 in 2,260 | ₦44 |
  | 3,000 | 24 | 1 in 7,800 | ₦38 |
  | 10,000 | 28 | 1 in 31,000 | ₦32 |

  No choice of legs changes the basic maths: even at perfectly fair prices a 3,000-odds ticket wins 1 time in 3,000, and every leg's margin makes it rarer. The builder only finds the least-bad ticket for the odds you ask for. It's a lottery ticket, so stake accordingly.

Three things to know:

- **The chance comes from SportyBet's odds, not the model.** In the backtest the bookmakers' odds predicted results better than the model in every market, and mixing the model in made them worse. The model is a second opinion: it can veto a leg, not add one.
- **Short legs aren't the safe way to big odds.** Each leg carries the bookmaker's margin, so for the same total odds, nine legs at 1.30 win less often than four at 1.78. The search picks whatever combination wins most often.
- **By SportyBet's own prices, every accumulator loses on average.** A typical 10-odds ticket wins about 1 time in 12 and returns about ₦80 per ₦100 staked over time. Treat it as entertainment and keep the stake to 1% of your bankroll or less.

Free team news only covers the Premier League, so by default the ticket can only use Premier League matches. Tick "I've checked the team news" (the same override as in Match analysis) to use the other leagues, after checking the news for the matches marked ✗.

## SportyBet booking codes

**Get SportyBet booking code** in the **Bet slip** tab books your slip on SportyBet and shows the code and a link. It uses the same Book Bet service a visitor uses on sportybet.com (`predictor/sportybet.py`): no login, no stake, no bet placed. You load the code on SportyBet, pick singles or a multiple, set the stake and confirm there. Before booking, each selection is re-checked against SportyBet's current odds and flagged if it has dropped out of its value range.

The app also reads SportyBet's current odds for every fixture it lists (16 leagues), so **Fixtures** values bets and picks at SportyBet's real prices, and **Match analysis** fills "Your odds" with them. Matches SportyBet doesn't list fall back to the bookmaker average.

SportyBet has no public API: this reads the data its own website loads, so it can break whenever SportyBet changes the site, and automated use may be against its terms. If it stops working, the list under SportyBet's market names below the slip still works: add them on sportybet.com/ng and press **Book Bet**. Other Nigerian bookmakers (Bet9ja, BetKing, MSport, 1xBet, Betway) aren't connected.

Accumulators: the slip shows the combined odds, real win chance and edge. Prefer singles. If you do combine, keep to 2–3 legs that each have value, never two picks from the same match, and stake at most 1% of bankroll.

## Odds log

Nobody publishes SportyBet's past prices, so nothing about SportyBet itself can be backtested until we collect them. `python -m predictor snapshot` saves SportyBet's current odds for every listed match in the 16 leagues (all markets the app uses), plus football-data.co.uk's Bet365, average and best odds for the same fixtures, to monthly files in `data/odds_log/` (`sportybet_YYYY-MM.csv`, `footballdata_YYYY-MM.csv`; times in UTC).

On the VPS a timer (`deploy/odds-snapshot.timer`) runs it every 2 hours from 07:05 to 23:05 Nigerian time: about 150 requests a day to SportyBet, and a price within about 2 hours of most kick-offs (`snapshot.closing` takes the last one before kick-off). After 4–6 weeks there's enough to test whether SportyBet's prices are ever far enough from the market's to bet on. Check it on the server with `systemctl list-timers odds-snapshot.timer` and `journalctl -u odds-snapshot`.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Results, shots, corners, cards, referees, odds | football-data.co.uk (fallback: GitHub mirror for top 5, no odds) | Free |
| Upcoming fixtures, referees, bookmaker average odds | football-data.co.uk `fixtures.csv` (next few days, all leagues) + Understat schedule (top 5, whole season) | Free |
| Latest results football-data hasn't added yet | Understat (goals and xG; football-data stays the authority on dates and home/away) | Free |

**Checked:** football-data.co.uk and Understat results were compared match by match for the top 5 leagues, 2016-17 to 2026-27 (about 18,000 matches). Scores agree everywhere except matches awarded by the authorities, where football-data has the official result (Union Berlin v Bochum 2024, Sassuolo v Pescara 2016). Where Understat had home and away swapped (Rennes v PSG, Aug 2026), football-data was right. This season's results refresh automatically every 6 hours.
| Team xG per match | understat.com (fallback: Premier League copy in vaastav/Fantasy-Premier-League, to 2024-25) | Free, top 5 leagues |
| Player xG / xA | understat.com (fallback: vibedatascience/understat_players_aggregated) | Free, top 5 leagues |
| Injuries, suspensions | API-Football `/injuries` (key in the app sidebar or `API_FOOTBALL_KEY`); Fantasy Premier League | Free tier 100 requests/day; paid plans from about $19/month |

All downloads are cached in `data/raw/`.

## Roadmap

1. ~~Profit backtest with odds~~ (done: no edge in the top 5) and ~~smaller leagues~~ (done: no edge in 17 of them). See [What the backtest says](#what-the-backtest-says).
2. After 4–6 weeks of the [odds log](#odds-log): test SportyBet's own prices against the market's fair price, and the model at SportyBet's real prices.
3. Confirmed lineups (released ~1 hour before kickoff) from API-Football, on top of the injury list.
4. n8n workflow in this repo: fetch fixtures → run model → send value picks to Telegram.
