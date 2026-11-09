# Asset Statistics, Assets A–F

Made by `research/asset_stats.py`. Rerun it with:

    .venv/bin/python research/asset_stats.py

Drawdown chart: `research/drawdowns.png`

---

## 1. What each number means

**Daily return**
How much the closing price changed from one day to the next.
Example: $100 to $101 is +1%. Every other number below is built from these.

**Annualized return**
The steady yearly growth rate that would turn your starting money into your
ending money. It's the "compound" rate, meaning it accounts for gains building
on earlier gains.

**Annualized volatility**
How much the price jumps around. It's the spread of the daily returns,
multiplied by √252 (252 ≈ trading days in a year) to put it on a yearly scale.
Higher = bumpier ride.

**Sharpe ratio**
Average return ÷ volatility, so it measures reward per unit of risk.
About 1 is good; below 0.5 is weak.
(Assumes a risk-free rate of 0, which is common in competitions.)

**Max drawdown**
The worst drop from a previous high to a later low.
−50% means at some point you'd lost half of your best value so far.

**Correlation**
How often two assets move together on the same day. Ranges from −1 to +1;
+1 means they always move together. Low correlation is good, because losses in
one asset can be cushioned by the others.

---

## 2. Results: Development period, 2016–2021

2016-10-31 to 2021-12-31 (1,302 trading days)

| Asset | Avg daily return | Annualized return | Annualized volatility | Sharpe | Max drawdown |
|---|---|---|---|---|---|
| A | 0.159% | 42.6% | 30.1% | 1.33 | −38.7% |
| B | 0.069% | 6.8% | 46.4% | 0.37 | −78.4% |
| C | 0.094% | 20.0% | 32.9% | 0.72 | −43.0% |
| D | 0.322% | 88.5% | 59.6% | 1.36 | −60.6% |
| E | 0.075% | 16.3% | 27.3% | 0.69 | −43.2% |
| F | 0.070% | 11.7% | 36.5% | 0.48 | −69.7% |

Correlation of daily returns:

|   | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| A | 1.00 | 0.39 | 0.60 | 0.41 | 0.48 | 0.31 |
| B | 0.39 | 1.00 | 0.31 | 0.28 | 0.50 | 0.50 |
| C | 0.60 | 0.31 | 1.00 | 0.33 | 0.42 | 0.27 |
| D | 0.41 | 0.28 | 0.33 | 1.00 | 0.29 | 0.26 |
| E | 0.48 | 0.50 | 0.42 | 0.29 | 1.00 | 0.44 |
| F | 0.31 | 0.50 | 0.27 | 0.26 | 0.44 | 1.00 |

Average correlation between pairs: **0.39**

---

## 3. Results: Holdout period, 2022–2023

2022-01-03 to 2023-10-06 (443 trading days)

| Asset | Avg daily return | Annualized return | Annualized volatility | Sharpe | Max drawdown |
|---|---|---|---|---|---|
| A | 0.018% | −0.0% | 30.4% | 0.15 | −31.3% |
| B | 0.015% | −4.0% | 39.6% | 0.10 | −48.7% |
| C | 0.050% | −3.6% | 56.4% | 0.22 | −73.7% |
| D | 0.010% | −15.8% | 62.7% | 0.04 | −73.0% |
| E | −0.034% | −12.3% | 30.4% | −0.28 | −40.2% |
| F | −0.087% | −26.8% | 43.2% | −0.51 | −56.5% |

Correlation of daily returns:

|   | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| A | 1.00 | 0.48 | 0.57 | 0.59 | 0.55 | 0.51 |
| B | 0.48 | 1.00 | 0.35 | 0.37 | 0.47 | 0.55 |
| C | 0.57 | 0.35 | 1.00 | 0.38 | 0.43 | 0.38 |
| D | 0.59 | 0.37 | 0.38 | 1.00 | 0.41 | 0.46 |
| E | 0.55 | 0.47 | 0.43 | 0.41 | 1.00 | 0.49 |
| F | 0.51 | 0.55 | 0.38 | 0.46 | 0.49 | 1.00 |

Average correlation between pairs: **0.47**

---

## 4. What this tells us

1. **Each asset on its own is very risky.**
   Every one of them fell at least 31% at some point, and B fell 78%. Holding B
   alone, you'd have lost more than three-quarters of your peak value. Drawdown
   counts a lot in the scoring, so holding any single asset outright would score
   poorly.

2. **2022–2023 looks very different from 2016–2021.**
   All six assets have a Sharpe below 0.25 in the later period, and four of them
   lost money. The early winners, A and D, aren't guaranteed to keep winning.
   Picking "the best stock from 2016–2021" would probably disappoint.

3. **The assets move together, but not completely.**
   A correlation of 0.4–0.5 means combining them still helps smooth out losses.
   That's why a mix of all six is our baseline. Correlation went up in
   2022–2023, which is common in falling markets: diversification helps less
   exactly when you need it most.

4. **The March 2020 COVID crash shows up in every asset.**
   Any strategy we build needs a plan for a crash like that.

---

## 5. Why can Asset_C have a positive Sharpe but a negative return in 2022–2023?

The Sharpe uses the *simple average* of daily returns. The annualized return
uses *compounding*. When prices swing a lot, compounding works against you:

    Lose 50%, then gain 50%:  $100 → $50 → $75   (down 25%)
    Simple average of −50% and +50% = 0%

C was extremely volatile in this period (56%), so this effect was large.
It's another reason to keep volatility low.

---

## 6. About the drawdown chart (`research/drawdowns.png`)

Each panel shows how far an asset was below its previous high.
The high is reset on 1 January 2022 (dashed line), so the lowest point in each
section matches the max drawdown in that period's table.
The grey shaded area is the holdout period.

---

## 7. A note on the holdout

`CLAUDE.md` says the 2022–2023 holdout should only be used for final checks.
Now that we've seen how badly D and F did in 2022–2023, we should be careful
not to let that shape our choices (for example, quietly leaving those assets
out). From here on, design and tuning use **2016–2021 only**.
