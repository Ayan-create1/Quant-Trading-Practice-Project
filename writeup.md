# Strategy Write-up: Multi Trend + Momentum

**Author:** Ayan Agarwal
**Deliverable:** `strategy/` folder (code, README, bundled data)

## Summary

A long-only, risk-controlled strategy for Assets A–F. Each asset is held only
while its price trend is positive. The size of each holding depends on how calm
the asset has been, and money that isn't invested stays in cash. The goal is a steady
Sharpe ratio and small drawdowns rather than maximum return.

| | Max drawdown | Sharpe | Return |
|---|---|---|---|
| Development, 2017-11 to 2021-12 | **−12.1%** (baseline −36.5%) | **1.37** (baseline 1.17) | 19.6% a year (baseline 31.9%) |
| Holdout, 2022-01 to 2023-10 | **−17.4%** (baselines about −30.5%) | −0.23 (baselines −0.02 to 0.09) | −6.2% total (baselines −3.3% to −7.9%) |

The baseline is an inverse-volatility portfolio of all six assets. The
drawdown protection held up out of sample. Return and Sharpe did not (see
[Results](#results)).

---

## The strategy

Every morning, for each asset A–F, using closing prices up to the previous day only:

| Step | Rule |
|---|---|
| Trend signal | 1 if the latest close is above its 50-day average, else 0 |
| Momentum signal | the average of three 0/1 signals: is the return over the past 63, 126 and 252 trading days positive? |
| Signal strength | (trend + momentum) ÷ 2, a number between 0 and 1 |
| Base weight | inverse volatility: 1 ÷ standard deviation of the last 60 daily returns, scaled so the six add up to 1 |
| **Target weight** | **base weight × signal strength**. The remainder is held in cash. |

- Long only. Total weight is never above 100%. Asset_G is always 0, because it duplicates Asset_B.
- Trades happen at the next day's open. Costs are 5 bp per unit traded, charged only on the change in each position.
- Holding-period limit: by default, a position held 21 trading days is closed for
  one day, then may be reopened. This is configurable (see [Holding-rule setting](#holding-rule-setting)).

**Why it should work:** assets that have been rising over several months tend to
keep doing so for a while. More importantly, a sustained fall turns the signals
off, and the strategy moves to cash before most of the damage is done.
Blending one trend signal with momentum over three different lookbacks means no
single, possibly lucky, setting drives the result. Inverse-volatility sizing
stops the jumpiest assets from dominating risk.

---

## Research process

- **Development data:** 2016-10-28 to 2021-12-31, used for all design decisions.
- **Holdout:** 2022-01-03 to 2023-10-06. Run **once**, after the strategy was frozen.
- **Look-ahead checks:** every strategy was re-run with later data deleted and with
  future prices deliberately altered. Earlier decisions never changed.
- **Steps:**
  1. Baselines: equal weight and inverse volatility, daily and monthly.
  2. A trend filter and a momentum signal, plus their combinations (AND, OR, AVERAGE).
  3. A robustness grid: moving average 30–200 days × momentum 63–252 days.
     Single-lookback momentum turned out to depend heavily on the 126-day setting
     (Sharpe 1.60 at 126 days, but 1.07–1.26 at the neighbouring settings).
  4. A final choice between "Single" (126-day momentum) and "Multi" (63/126/252),
     using a decision rule written down *before* running. The rule compared the two
     at 9 nearby settings. Multi won: its Sharpe stayed between 1.22 and 1.49
     across all 9 settings, against 1.15–1.66 for Single.
  5. Volatility targeting at 10%, 15% and 20%: tested and **rejected**. Every
     version lowered the Sharpe. The signals already move money to cash in
     sell-offs, and vol targeting then kept exposure low during rebounds.
  6. Holdout: run once, and nothing was changed afterwards. A 25% equal-weight /
     75% Multi blend was looked at later, as a reporting check only (it is no
     longer an unbiased test). It was **not adopted**, because it traded lower
     Sharpe and deeper drawdowns for more return.

---

## Results

All results use the strict 21-day holding limit and 5 bp costs.

### Development period (2017-11-30 to 2021-12-31)

| | **Multi** | Inverse vol | Equal weight |
|---|---|---|---|
| Annualized return | 19.6% | 31.9% | 33.6% |
| Annualized volatility | **13.8%** | 26.7% | 28.8% |
| Sharpe ratio | **1.37** | 1.17 | 1.15 |
| Max drawdown | **−12.1%** | −36.5% | −38.6% |
| Average % invested | 63% | 96% | 96% |

### Holdout (2022-01-03 to 2023-10-06)

| | **Multi** | Inverse vol | Equal weight |
|---|---|---|---|
| Total return | −6.2% | −7.9% | **−3.3%** |
| Sharpe ratio | −0.23 | −0.02 | **0.09** |
| Max drawdown | **−17.4%** | −30.4% | −30.7% |
| 2022 return | **−15.7%** | −23.9% | −25.3% |
| 2023 return (to Oct 6) | +11.3% | +21.1% | **+29.5%** |

**Honest reading:** the strategy did what it is designed to do in the 2022 bear
market. It lost about a third less than the baselines, and its worst drawdown was
roughly half theirs. But it re-entered too slowly in the sharp 2023 rebound,
because the 252-day momentum stayed negative for months. Over the full holdout
it finished behind equal weight.

The development-period Sharpe was also helped a lot by one fast crash (COVID,
March 2020), which is the easiest case for this kind of strategy. On new data, a
realistic expectation is a Sharpe of about 1.0–1.4 and a max drawdown of −12% to −20%,
with the strategy trailing buy-and-hold during strong rallies.

**Risks:**
- Choppy markets with repeated false rallies, where signals switch on just before another drop.
- Sharp V-shaped rebounds, which it is slow to rejoin.
- Overnight gaps, because signals react only to the previous close.

---

## How to run

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

### Verification

A test suite in my project repository (`tests/test_strategy.py`, 23 tests; not part of this submission, available on request) confirms that the packaged strategy
reproduces the research backtest **exactly**: identical weights on every one of
1,472 trading days. It also tests the one-day-at-a-time feeding, the fallback,
the holding limit, and that total weight never exceeds 100%.

Separately, a script written only from the README was run in a fresh folder
containing just `strategy/`. It fed the strategy one day at a time, using its own
simple accounting, and reproduced the numbers above. That included the holdout
run where it was given just one day of history and the fallback filled in the rest.
