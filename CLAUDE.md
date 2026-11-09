# CLAUDE.md

Project rules for this trading-competition practice project. Follow these in every session.

## Data
- Files: `data/Asset_A.csv` through `data/Asset_F.csv` — daily Nasdaq data, 2016-10-28 to 2023-10-06.
- Columns: `Date, Close/Last, Volume, Open, High, Low`. Price columns contain `$` signs — strip them and convert to float. The close column is `Close/Last`.
- Always sort by date ascending after loading.
- **Ignore Asset_G entirely** (it duplicates Asset_B). Use only the 6 assets A–F.
- Do not try to identify the real stocks, and do not use any outside price data.

## Trading rules
- Trades execute at the **next day's Open**.
- Positions may be held overnight for up to about one month (~21 trading days). Every position must be closed by then.
- Weights are signed fractions of equity (positive = long, negative = short). The sum of absolute weights must be ≤ 1.
- Costs: 5 basis points on entry + 5 bps on exit, scaled by position size. Charge costs only on the part of a position that actually changes (the turnover), not on positions that are simply held.

## No look-ahead bias
- Decisions for day t may only use data through day t−1's close. Never use day t's data.
- Always check for look-ahead bias (e.g. off-by-one shifts, using the same day's Open/Close in the signal, fitting on future data).

## Scoring
- Weighted points for percent return, max percent drawdown, and Sharpe ratio, scored relative to other competitors.
- **Sharpe and drawdown matter a lot** — prefer steady, risk-controlled strategies over high-return/high-risk ones.

## Final deliverable
- A function that takes the data available so far and returns a dict of target weights for `Asset_A`–`Asset_F`, while keeping track of how long each position has been held (to enforce the ~21-trading-day limit).

## Research process
- Development period: 2016–2021. Holdout: 2022–2023 — touch only for final checks, never for tuning.
- First baseline to beat: hold all 6 assets (equal weight or inverse-volatility weight), rebalanced monthly.

## Environment
- Use the Python virtual environment in `.venv` (pandas, numpy, matplotlib, jupyter installed), e.g. `.venv/bin/python`.

## Communication
- The user is a beginner: explain what you're doing and why in plain language.
- Long terminal output is hard for the user to scroll through. For any analysis or explanation longer than a few lines, write it to a Markdown file next to the script that produced it (e.g. `research/asset_stats_explained.md`), including results tables, plain-language explanations, and chart paths. Keep the terminal reply short: what was done, the key takeaway, and the file path. Remind the user they can preview it in VS Code with Cmd+Shift+V.
