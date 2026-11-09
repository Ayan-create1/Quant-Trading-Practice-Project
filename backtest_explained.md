# The Backtester, Explained

Files:
- `backtest.py`: the backtester
- `tests/test_backtest.py`: 17 tests (all passing)
- `research/backtest_demo.png`: example equity curve

Commands:

    .venv/bin/python backtest.py                                # run the demo
    .venv/bin/python -m unittest -v tests/test_backtest.py     # run the tests

---

## 1. What a backtester is

A backtester replays history one day at a time and pretends to trade. Each
day it asks your strategy "what do you want to hold today?", makes the trades,
charges costs, and tracks how much money you'd have. At the end it reports how
well the strategy did.

The hard part is not cheating by accident. In real life you can't know
today's closing price when you trade at today's open. A backtester that lets
that information slip in (called **look-ahead bias**) makes strategies look
far better than they really are.

---

## 2. How one day works (day t)

    Close[t-1] ──overnight──> Open[t] ──trade──> ──during the day──> Close[t]
       │                                                               │
       └─ strategy sees data only up to here                           └─ equity recorded

1. **Overnight:** positions from yesterday move with the price from
   yesterday's close to today's open.
2. **Decide:** the strategy is given every row up to and including day t−1,
   and nothing from day t. It returns target weights, e.g.
   `{"Asset_A": 0.2, "Asset_C": -0.1}`.
3. **Trade at the open:** move from current positions to the targets and pay
   **5 bp (0.05%) of the dollar amount that changes**. Positions that don't
   change pay nothing.
4. **During the day:** positions move from today's open to today's close, and
   the account value is recorded at the close.

---

## 3. Rules the backtester enforces

| Rule | What happens |
|---|---|
| Sum of \|weights\| ≤ 1 | If a strategy asks for more, every weight is shrunk by the same factor. Counted in "Days \|w\| scaled to 1". |
| Hold limit ~21 days | A position held in the same direction for 21 trading days is force-closed on day 22. It can be reopened the next day. Counted in "Forced closes". Can be turned off with `max_hold_days=None`. |
| Only Assets A–F | Any other name (e.g. Asset_G) is an error. |
| No broken numbers | A NaN or infinite weight is an error. |
| Close at the end | Everything is sold at the end, so the exit cost is counted. |

---

## 4. How to write a strategy

    def my_strategy(history):
        # history["Asset_A"]["Close"] = Asset_A's closes up to YESTERDAY
        return {"Asset_A": 0.5, "Asset_B": -0.3}

    from backtest import run_backtest, load_panel, print_report, plot_equity
    result = run_backtest(my_strategy, load_panel(), start="2016-11-01", end="2021-12-31")
    print_report(result, "My strategy")
    plot_equity({"My strategy": result}, "research/my_strategy.png")

- **Return `None`** to mean "keep what I have, don't trade".
- Assets you leave out of the dict get weight 0.
- **Optional second argument `portfolio`:** if your function takes two
  inputs, `my_strategy(history, portfolio)`, it also gets
  `portfolio["weights"]` (current weights) and `portfolio["holding_days"]`
  (how long each position has been held). The final competition function
  needs to track holding time, so this will be useful.
- The strategy may use data before `start`. That is still the past, so it's
  allowed, and it's useful for things like "average of the last 60 days".

---

## 5. What it reports

| Number | Meaning |
|---|---|
| Total return | How much $1 grew (or shrank) over the whole period. |
| Annualized return | Steady yearly growth rate giving the same result. |
| Annualized volatility | How bumpy the account value was, on a yearly scale. |
| Sharpe ratio | Return per unit of bumpiness (risk-free rate = 0). Higher is better. |
| Max drawdown | Worst drop from a high to a later low. |
| Turnover per year | How much was traded, in multiples of the account. 2x = traded twice the account's value in a year. More turnover = more costs. |
| Total costs paid | Sum of all trading costs, as a fraction of equity. |

---

## 6. The tests that prove there's no look-ahead bias

| Test | What it proves |
|---|---|
| **Only sees yesterday** | A "spy" strategy records the newest date it's given each time. For every trading day, it's always exactly the previous trading day, never today. |
| **Changing the future doesn't change the past** (the key test) | Run once on normal data. Then replace every price from day k onward with random junk and run again. Every decision up to day k and every account value up to day k−1 must be exactly the same. If any future data leaked in, they'd differ. Checked at four different k's. |
| **The test catches a cheater** | Proves the key test actually works: a strategy that secretly peeks at today's close fails it. It also earns an absurd Sharpe ratio above 5, which is the warning sign to watch for in real results. |
| **Strategy can't corrupt the data** | A strategy that overwrites the history it's given doesn't change the backtest, because it only gets a copy. |
| **Unsorted data is sorted** | Feeding the data newest-first gives exactly the same result. |

Accounting tests (12 more) check, with hand-calculated answers:
- buying at the open, not the previous close (an overnight jump before you buy doesn't count);
- holding overnight earns the overnight move;
- costs are charged once on entry, never on unchanged positions, and scale with trade size;
- short positions make money when prices fall;
- the \|w\| ≤ 1 cap, the 21-day hold limit, and bad inputs.

---

## 7. A bug the tests caught (and fixed)

The first version had a subtle flaw. After paying the entry cost, the account
was slightly smaller, so a "100%" position was really 100.05% of the account.
The next day the backtester "fixed" that by trading a tiny amount and charging
a cost, even though the strategy hadn't changed anything.

The fix: trades are now sized so the weights *after* costs exactly match what
the strategy asked for. One side effect is visible in the tests: entering a
full position from cash leaves you with `1 / (1 + 0.0005)` ≈ 0.99950 of your
money. That's the same as "minus 5 bp" to 7 decimal places.

---

## 8. Demo result: equal weight in all six assets, 2016–2021

| | With 21-day limit (default) | Without limit |
|---|---|---|
| Total return | 332.1% | 360.5% |
| Sharpe ratio | 1.20 | 1.23 |
| Max drawdown | −42.5% | −46.5% |
| Turnover per year | 26.2x | 3.7x |
| Total costs paid | 6.77% | 0.94% |

This is just a test drive, not the official baseline. The demo returns
the same weights every day, so it trades a little every day to undo price
drift. The proper monthly-rebalanced baseline is the next step.

---

## 9. Decision needed: how does the ~21-day hold limit work?

The table above shows the hold limit matters a lot. Right now, a position held
21 days is fully sold, and if the strategy still wants it, it's bought back
the next day. That round trip happens to every asset about 12 times a year,
which explains the 26x turnover and the extra ~6% in costs.

Possible readings of the competition rule:
1. **Must fully exit** (current setting): sell, sit out at least one day, rebuy.
2. **Must sell and rebuy, but can rebuy the same day.** Same cost, no day out
   of the market.
3. **Rebalancing counts as a new position.** A position you trim or top up
   counts as fresh, so a monthly rebalance satisfies the rule at almost no extra cost.

The competition rules should say which applies. This changes the baseline and
every strategy's costs.
