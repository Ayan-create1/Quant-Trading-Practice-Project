# Strategy Write-up: Multi Trend + Momentum

**Author:** Ayan Agarwal
**Deliverable:** `strategy/` folder (code, README, bundled data)

## Summary

A long-only, risk-controlled strategy for Assets A–F. It holds each asset only
while that asset's price trend is positive, sizes holdings so calmer assets get
more money, and keeps everything else in cash. The aim is a steady Sharpe ratio
and small drawdowns rather than maximum return.

| | Max drawdown | Sharpe | Return |
|---|---|---|---|
| Development, 2017-11 to 2021-12 | **−12.1%** (inverse-vol baseline −36.5%) | **1.37** (baseline 1.17) | 19.6% a year (baseline 31.9%) |
| Holdout, 2022-01 to 2023-10 | **−17.4%** (baselines −30.4% to −30.8%) | −0.23 (baselines −0.02 to 0.09) | −6.2% total (baselines −3.3% to −8.2%) |

The drawdown protection held up out of sample. Return and Sharpe did not.

---

## 1. Trading hypothesis

**Hypothesis:** an asset whose price has been rising over the past few months
tends to keep rising for a while, and one that has been falling tends to keep
falling. Holding assets only while they trend up, and stepping into cash while
they trend down, should avoid much of the damage in sustained sell-offs while
keeping most of the gains in up-trends.

**Why it might work:** trends persist because investors react to news gradually
and because selling tends to feed on itself during declines. The main benefit we
expected, and found, is **loss avoidance**: the strategy's value comes from
being in cash during long falls, not from picking winners.

## 2. Assets and behaviours targeted

- **Assets:** all six, A–F, traded independently. Asset_G is excluded (always
  weight 0) because it duplicates Asset_B.
- **Behaviour targeted:** sustained multi-month trends, and especially sustained
  declines. For example, in 2022 Assets C and D each fell about 65%, and the strategy
  held only 1% and 4% of them on average.
- **Not targeted:** short-term moves. The signals are deliberately slow, so the
  strategy doesn't react to day-to-day noise.

## 3. How signals are generated

Every morning, for each asset, using closing prices **up to the previous day only**:

| Signal | Rule |
|---|---|
| Trend | 1 if the latest close is above its 50-day average, else 0 |
| Momentum | the average of three 0/1 signals: is the return over the past 63, 126 and 252 trading days positive? |
| **Signal strength** | **(trend + momentum) ÷ 2**, from 0 (fully out) to 1 (fully in), in steps of ⅙ |

Combining four signals means the strategy steps in and out of an asset gradually
rather than all at once. Using three momentum lookbacks means no single, possibly
lucky, setting drives the result.

## 4. Allocation sizing and risk management

- **Base weight:** inverse volatility, meaning 1 ÷ the standard deviation of the
  last 60 daily returns, scaled so the six weights add up to 1. A jumpier asset
  gets less money, so each asset contributes more evenly to risk.
- **Target weight = base weight × signal strength.** The unused part of the account is held in cash.
- **Limits:** long only. Total weight is never above 100% (checked in code and in tests).
- **Execution and costs:** trades happen at the next day's open. Costs are 5 bp per
  unit traded, charged only on the change in each position.
- **Holding period:** by default, a position held 21 trading days is closed for one
  day, then may be reopened. This is configurable (see [Holding-rule setting](#holding-rule-setting)).
- **The main risk control is the signal itself:** in falling markets the strategy
  moves to cash. On average it was 63% invested in the development period and 46% in the holdout.

---

## 5. How it was backtested and validated

- **Data split:** development data from 2016-10-28 to 2021-12-31 was used for every
  design decision. The 2022-01-03 to 2023-10-06 holdout was run **once**, after the
  strategy was frozen. Nothing was changed because of the holdout result.
- **Backtester:** trades at the next day's open, 5 bp costs on turnover, positions
  carried overnight, strict 21-day holding limit, total weight capped at 100%.
  All strategies in a comparison start on the same day.
- **Look-ahead tests:** these were run for every strategy.
  - Truncation: re-running with all data after a cut-off date deleted left every earlier day's weights unchanged.
  - Tamper: tripling all prices from the decision day onward didn't change that day's weights.
  - By hand: signals were checked against hand calculations.
- **Robustness grids (development data only):**
  - Moving average 30/50/100/200 days × momentum lookback 63/126/252 days, plus a finer lookback sweep from 42 to 252 days in steps of 21.
  - This showed that single-lookback momentum depended heavily on the 126-day setting: Sharpe 1.60 at 126 days, but only 1.07–1.26 at 63, 189 and 252 days.
  - All 20 grid cells cut drawdown sharply (−10% to −22% vs −48% for the baseline over that period).
- **Decision rule fixed in advance:** before running the final comparison between
  "Single" (126-day momentum) and "Multi" (63/126/252), I wrote down how the winner would be chosen.
  - Compare both at 9 nearby settings, and prefer the one that is better on median Sharpe *and* on worst drawdown.
  - If those two disagree, the one whose Sharpe varies less wins.
  - Multi won on that tie-break. Its Sharpe stayed between 1.22 and 1.49 across the 9 settings, against 1.15–1.66 for Single.
- **Other checks:**
  - Year-by-year results.
  - Results with the COVID crash removed.
  - Each asset traded on its own.
  - Costs doubled to 10 bp: for the earlier 126-day momentum version, Sharpe went from 1.63 to 1.55.
- **Packaging check:** the delivered code reproduces the research backtest
  **exactly**, with identical weights on all 1,472 trading days (23 automated tests).
  A script written only from the README also reproduced the results in a clean
  folder containing just `strategy/`.

---

## 6. Results vs baselines

All results use the strict 21-day holding limit and 5 bp costs.

### Development period (2017-11-30 to 2021-12-31)

| | **Multi** | Inverse vol | Equal weight |
|---|---|---|---|
| Annualized return | 19.6% | 31.9% | 33.6% |
| Sharpe ratio | **1.37** | 1.17 | 1.15 |
| Max drawdown | **−12.1%** | −36.5% | −38.6% |

### Holdout (2022-01-03 to 2023-10-06)

| | **Multi** | Inverse vol (daily) | Inverse vol (monthly) | Equal weight |
|---|---|---|---|---|
| Total return | −6.2% | −7.9% | −8.2% | **−3.3%** |
| Annualized return | −3.6% | −4.6% | −4.7% | **−1.9%** |
| Sharpe ratio | −0.23 | −0.02 | −0.02 | **0.09** |
| Max drawdown | **−17.4%** | −30.4% | −30.8% | −30.7% |
| 2022 return | **−15.7%** | −23.9% | −23.5% | −25.3% |
| 2023 return (to Oct 6) | +11.3% | +21.1% | +20.0% | **+29.5%** |

**Honest reading:**
- In the 2022 bear market, the strategy did what it is designed to do. It lost
  about a third less than the baselines, and its worst drawdown was roughly half theirs.
- It then re-entered too slowly in the sharp 2023 rebound, and over the full
  holdout it finished behind equal weight.
- Before the holdout, the expectation was a Sharpe of about 1.2–1.4 and a max
  drawdown of about −12% to −18%. The drawdown landed inside that range; the Sharpe came in well below it.

---

## 7. Ideas tested and rejected

| Idea | Result | Why rejected |
|---|---|---|
| **Single-lookback signals** (trend only, momentum only, AND, OR, Single AVERAGE) | Momentum only looked best at 126 days (Sharpe 1.63), but fell to about baseline level at nearby settings | Too dependent on one possibly lucky setting; Multi was more stable |
| **Volatility targeting** (10%, 15%, 20%; "cut only" and "up & down") | Every version lowered the Sharpe, from 1.37 to between 1.18 and 1.32. The best drawdown, −10.7% (cut only, 10%), cost 7% a year in return (19.6% to 12.5%) | The signals already de-risk in sell-offs. Vol targeting then kept exposure low during rebounds, and the "up & down" version concentrated risk |
| **25% equal weight + 75% Multi** | Development: Sharpe 1.32, max drawdown −17.8%, 23.4% a year. 2022–23: −7.0%, max drawdown −21.4% | Traded lower Sharpe and deeper drawdowns for more return. **Note: this was tested *after* seeing the holdout, so its 2022–23 numbers are not an unbiased test** |
| **Short-term reversal** | **Not tested** in this project | — |

---

## 8. Limitations and failure conditions

- **Slow re-entry after crashes.** After a deep fall, the 252-day momentum can stay
  negative for months even while prices recover. This happened in 2019 and 2021 in
  the development period, and badly in 2023.
- **Lags strong rebounds.** It trails buy-and-hold in strong rallies. In 2023 it made
  +11.3% against equal weight's +29.5%.
- **Its value depends on sell-offs happening.** If Feb–Apr 2020 (COVID) is removed
  from the development period, the final Multi strategy's Sharpe falls *below* the
  baseline's: 1.46 vs 1.58. Its drawdown is still much smaller (−12.1% vs −20.2%).
  The earlier 126-day momentum version showed the same pattern (1.74 vs 1.66; −10.3% vs −20.0%).
  In a calm, steadily rising market it will likely underperform.
- **Choppy markets and false rallies.** Signals can switch back on just before
  another drop, as in mid to late 2022. They also react only to the previous close,
  so fast single-day drops get through.
- **The 21-day rule interpretation matters.** All results assume a full exit after
  21 days with one day out. A different reading changes turnover and costs (see the setting below).
- **Short history.** Development results cover about four years and contain one fast
  crash, so the estimates are noisy.

---

## 9. How to run

**Requirements:** Python 3.10+, `numpy`, `pandas`. Nothing else.

```bash
pip install numpy pandas
```

```python
from strategy.strategy import MultiStrategy

strat = MultiStrategy()          # create once, reuse every day
weights = strat(history)         # call before each open, with data up to yesterday's close
# -> {'Asset_A': ..., 'Asset_B': ..., ..., 'Asset_F': ..., 'Asset_G': 0.0}
```

- **What `history` can be:** a dict `{"Asset_A": DataFrame, ...}` in the raw Nasdaq
  CSV format (`Date`, `Close/Last` with `$` prices are fine), or one DataFrame with
  `(asset, field)` columns. You can pass the full history every day, or only the
  newest day's row. The strategy keeps the state it needs, including the holding
  days per asset.
- **Quick demo:** `python strategy/strategy.py` prints the weights for the next open.
- **Full details:** `strategy/README.md`.

### History requirement: 253 trading days, and the fallback

The strategy needs **253 trading days of closing prices** (about one year),
because its longest signal compares today's price with the price 252 trading days earlier.

If the first call provides less than that, the strategy **automatically fills in
earlier days** from the CSVs bundled in `strategy/data/` (Assets A–F, 2016-10-28 to
2023-10-06):

- Only dates **strictly earlier** than the first date provided are added. The provided data is never replaced.
- Before joining, it checks that the two series line up:
  - If the dates overlap, the closes on shared dates must match within 1%.
  - If they don't overlap, the gap must be 7 days or less and no price may jump more than 30% across it.
- If a check fails, it warns and holds cash until 253 days of real history exist.
- **Please ship `strategy/data/` together with `strategy.py`.**

If the competition data starts long after October 2023 and comes with less than
a year of history, the fallback cannot bridge the gap. In that case, please
provide at least 253 days of history.

### Holding-rule setting

At the top of `strategy/strategy.py`:

```python
HOLD_LIMIT_MODE = "exit_and_wait"   # or "off"
MAX_HOLD_DAYS = 21
COOLDOWN_DAYS = 1
```

| Rule | Setting |
|---|---|
| A position held 21 days must be closed before reopening | `"exit_and_wait"` (default; all results above use this) |
| …and must stay closed longer | `"exit_and_wait"` with a larger `COOLDOWN_DAYS` |
| Rebalancing counts as a new position, or sell-and-rebuy at the same open is allowed | `"off"` |
