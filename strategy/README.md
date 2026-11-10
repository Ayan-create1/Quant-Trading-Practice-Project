# Final Strategy: Multi Trend + Momentum

`strategy.py` is the competition deliverable. Before each trading day's open, it
takes the price history up to yesterday's close and returns target weights for
`Asset_A` through `Asset_G`. It is a frozen copy of the research strategy
(`research/final_signal.py`: "Multi", no volatility targeting), and a test proves
it gives exactly the same results.

## What it does

For each asset A–F, using closing prices only:

| Piece | Rule |
|---|---|
| Trend | 1 if the latest close is above the average of the last 50 closes, else 0 |
| Momentum | average of three 0/1 signals: is the return over the last 63, 126 and 252 trading days positive? |
| Strength | (trend + momentum) ÷ 2, between 0 and 1 |
| Base weight | inverse volatility (1 ÷ std of the last 60 daily returns), scaled to add up to 1 |
| **Final weight** | **base weight × strength**; the rest stays in cash |

- Long only, and total weight is never above 1 (100% gross).
- `Asset_G` is always 0 (it duplicates Asset_B).
- It needs **253 trading days** of history. If you give it less, it fills in
  earlier days from its bundled data when it safely can (see
  [History needed](#history-needed-253-trading-days-and-the-fallback)).

Research results (strict 21-day limit, 5 bp costs): 2017-11 to 2021-12 Sharpe 1.37,
max drawdown −12.1%. 2022-01 to 2023-10: −6.2% total return, max drawdown −17.4%.
See `research/final_signal_explained.md` and `research/holdout.md`.

## Dependencies

- Python 3.10 or newer
- `numpy` and `pandas`. Nothing else; it doesn't import any of the research code.

```bash
pip install numpy pandas
```

In this project, everything is already installed in `.venv`.

## How to use it

```python
from strategy.strategy import MultiStrategy

strat = MultiStrategy()                 # create ONCE and reuse it every day
weights = strat(history)                # call once per day, before the open
# {'Asset_A': 0.0646, 'Asset_B': 0.0246, ..., 'Asset_F': 0.0, 'Asset_G': 0.0}
```

Or the plain-function form, which keeps one shared object internally:

```python
from strategy.strategy import get_weights, reset
weights = get_weights(history)
```

Quick demo on the files in `data/`. It prints the weights for the open after the last date:

```bash
.venv/bin/python strategy/strategy.py            # or: python strategy/strategy.py path/to/csv_folder
```

### What `history` can be

1. **A dict of per-asset tables**: `{"Asset_A": df, ..., "Asset_F": df}`. Each table has
   a `Date` column (or a date index) and a close column named `Close` or `Close/Last`.
   Raw Nasdaq text like `$28.43` is fine, and rows can be newest-first.
   `load_csv_folder("data")` builds this dict from the raw CSV files.
2. **One table with two-level columns** `(asset, field)`, e.g. `history["Asset_A"]["Close"]`.
   This is the layout `backtest.py` uses.

Extra assets (such as `Asset_G`) and extra columns (Open, High, Low, Volume) are
ignored. **Only data up to yesterday's close should be passed in.** The strategy
has no way of checking that, so it's the caller's job.

### Feeding it one day at a time

You can pass either the **full history** every day or **only the new day's rows**.
The strategy keeps the last ~300 days of closes itself. Both give identical
results (there's a test for this). Calling it twice for the same day returns the
same weights and doesn't change any state. Passing a history that ends *earlier*
than a day it already processed raises an error. Call `strat.reset()` to start over.

## History needed: 253 trading days, and the fallback

**The strategy needs 253 trading days of closing prices** (about one year),
because its longest signal compares today's price with the price 252 trading
days ago.

If the **first** call gets fewer than 253 days, it automatically fills in
earlier days from the CSVs bundled in `strategy/data/` (Asset_A–F, 2016-10-28 to
2023-10-06, identical copies of the project's `data/` files). That way it can
invest from day one.

**How it works:**
1. It takes the bundled rows whose dates are **strictly earlier than the first
   date you passed in**. Your rows are never replaced or overlapped. If both have
   the same date, your row is used.
2. Before joining the two, it checks that they are the same price series:
   - **If your dates overlap the bundled dates**, the closes on the shared dates
     must match within **1%**.
   - **If they don't overlap**, the gap between the last bundled date and your
     first date must be **7 calendar days or less**, and no asset's price may jump
     more than **30%** across the join.
3. If the checks pass, it puts the bundled rows in front of yours and computes
   signals normally.
4. If a check fails, the bundled folder is missing, or there are no earlier
   bundled dates, it **skips the fallback**, gives a Python warning, and **holds cash**
   until it has 253 days of real history. A stitched-together series with a gap or a
   different price scale would give meaningless signals, so cash is the safer choice.

It only happens on the first call, and only when needed. With 253+ days passed
in, the bundled data is never touched. To see what happened:

```python
strat = MultiStrategy()
strat(history)
strat.fallback_status      # e.g. "prepended 1000 bundled days (2016-10-28 to 2020-10-19)"
strat.fallback_rows_used   # 1000
```

**⚠️ When the fallback can't help:** the bundled data ends **2023-10-06**. If the
competition's data starts much later than that, say 2026, and comes with less
than a year of history, the gap check will fail and the strategy will sit in cash
for up to a year. If that's the situation, ask the organizer to provide at least
253 days of history, or add newer data to `strategy/data/` in the same CSV format.

**Why the bundled files include 2022–23, not just 2016–21:** only dates earlier than
your first date are ever used, so including later data can't leak the future. It
just means the bundled data reaches as close as possible to whatever period the
competition uses, so the gap check is more likely to pass.

Settings, at the top of `strategy.py`:

```python
FALLBACK_ENABLED = True
FALLBACK_DIR = None             # None = strategy/data/
FALLBACK_PRICE_TOL = 0.01       # 1%
FALLBACK_MAX_GAP_DAYS = 7
FALLBACK_MAX_JUMP = 0.30        # 30%
```

or per object: `MultiStrategy(use_fallback=False)`, `MultiStrategy(fallback_dir="path/to/csvs")`.

**Ship the `strategy/data/` folder along with `strategy.py`.** Without it, the
fallback warns and is skipped, but nothing crashes.

### State it keeps

- The recent closes (above).
- `strat.holding_days`: how many trading days each position has been held.
- Its previous weights, used to tell whether a position is continuing or new.

The holding-day count assumes the previous weights were actually traded. If the
organizer's engine ever rejects or changes your orders, call `reset()` and the counts start fresh.

## ⚙️ Setting to check: the 21-day holding limit

At the top of `strategy.py`:

```python
HOLD_LIMIT_MODE = "exit_and_wait"   # or "off"
MAX_HOLD_DAYS = 21
COOLDOWN_DAYS = 1
```

| Organizer's rule turns out to be… | Set |
|---|---|
| A position held 21 days must be fully closed before reopening | `"exit_and_wait"` (default). After 21 days held, it returns 0 for that asset for `COOLDOWN_DAYS` day(s), then may buy back. |
| …and you must stay out longer (e.g. 5 days) | `"exit_and_wait"`, `COOLDOWN_DAYS = 5` |
| Rebalancing to new weights counts as a new position | `"off"` (the strategy trades to fresh weights every day) |
| You may sell and rebuy at the same open, and their engine handles it | `"off"`. A single weight dict can't say "sell and rebuy at the same open", because the net trade is zero. |
| The limit is a different length | change `MAX_HOLD_DAYS` |

You can also set it per object without editing the file:
`MultiStrategy(hold_limit_mode="off")`.

**Which research numbers apply:** `"exit_and_wait"` with 21 days / 1-day cooldown
matches every research backtest (the "strict 21-day limit" tables). `"off"`
matches the "no hold limit" tables. Those show slightly higher returns and much
lower turnover, because there are no forced round trips.

## Tests

```bash
.venv/bin/python -m unittest -v tests/test_strategy.py      # 23 tests, about 25 seconds
```

| Test | What it proves |
|---|---|
| `test_strict_21_day_limit_matches_research_exactly` | Through the research backtester, Nov 2017 – Oct 2023 (1,472 days), every day's weights and the whole equity curve are **identical** to the research version (difference 0.0). The headline numbers (Sharpe 1.37, −12.1% max drawdown, holdout −6.2%) also come out the same. |
| `test_limit_off_matches_research_without_limit` | Same exact match with the limit switched off. |
| `test_one_day_at_a_time_equals_full_history` | Feeding one new row per day gives the same weights and holding counts as feeding everything. |
| `test_raw_csv_format_gives_same_answer` | Raw CSVs (`$` prices, `Close/Last`, newest first) give the same answer as cleaned data. |
| `test_outputs_are_valid_every_day` | All 7 keys present, `Asset_G` = 0, no negatives, total ≤ 1, every day. |
| `test_hold_limit_never_exceeded_and_sits_out`, `test_cooldown_two_days`, `test_off_mode_never_forces_exit` | The holding-limit setting does what it says, in every mode. |
| `test_no_lookahead_future_rows_are_never_seen`, `test_warmup_holds_cash_when_fallback_off`, `test_same_day_twice_does_not_change_state`, `test_going_back_in_time_raises` | Safety behaviour. |
| `test_short_history_invests_and_matches_full_history` | Starting with just 10 days (Oct 2020) plus the fallback gives **exactly** the same weights as having the full history, on day one and for the next 300 days fed one row at a time. |
| `test_only_earlier_dates_are_prepended_never_replaced` | Passed-in rows are kept exactly as given, even when their prices differ slightly from the bundled ones. Prepended rows are all strictly earlier and equal the bundled data. |
| `test_joins_onto_bundled_data_after_it_ends` | History starting right after 2023-10-06 gets the whole bundled file prepended. |
| `test_skipped_if_prices_disagree_on_shared_dates`, `test_skipped_if_gap_too_long`, `test_skipped_if_price_jumps_across_join`, `test_missing_bundled_folder_does_not_crash`, `test_no_earlier_bundled_data_holds_cash` | When the data doesn't line up (or isn't there), the fallback is skipped with a warning and the strategy holds cash. |
| `test_not_used_when_history_is_long_enough`, `test_only_on_first_call` | The fallback never runs when it isn't needed. |
| `test_bundled_data_is_the_project_data` | `strategy/data/` files are byte-for-byte copies of `data/`. |
