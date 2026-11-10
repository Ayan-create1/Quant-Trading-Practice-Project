"""
Three baseline strategies on the development period (2016-2021):

  1. Equal weight      - 1/6 in each asset, reset to 1/6 every day.
  2. Inverse vol       - weight each asset by 1 / (its volatility over the past
                         60 days), reset every day. Calmer assets get more money.
  3. Inverse vol, monthly - same weights as 2, but only set about once a month
                         and left alone (to drift with prices) in between.

Run from the project folder:
    .venv/bin/python research/baselines.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
from backtest import ASSETS, MAX_HOLD_DAYS, format_stats, load_panel, plot_equity, run_backtest  # noqa: E402

VOL_WINDOW = 60      # days of returns used to measure volatility
REBALANCE_DAYS = 21  # "monthly" = about every 21 trading days
DEV_END = "2021-12-31"


# ----------------------------------------------------------------------------
# Weight rules. `history` holds data through yesterday's close only.
# ----------------------------------------------------------------------------
def inverse_vol_weights(history: pd.DataFrame, window: int = VOL_WINDOW) -> dict:
    """Weights proportional to 1 / volatility, adding up to 1.
    Uses the last `window` close-to-close returns, all from before today."""
    closes = history.xs("Close", axis=1, level=1)[ASSETS].iloc[-(window + 1):]
    vol = closes.pct_change().dropna().std()
    inv = 1 / vol
    w = inv / inv.sum()
    return w.to_dict()


def equal_weight(history):
    return {a: 1 / len(ASSETS) for a in ASSETS}


def inverse_vol_daily(history):
    return inverse_vol_weights(history)


def make_inverse_vol_monthly(strict_hold_limit: bool = True):
    """Set inverse-vol weights, then leave them alone for REBALANCE_DAYS days.

    strict_hold_limit=True (matches the backtester's current rule): after 21 days
    held, sell everything, sit out one day, then buy back with fresh weights.
    strict_hold_limit=False: on day 22 just trade straight to the fresh weights.
    """
    def strategy(history, portfolio):
        held = max(portfolio["holding_days"].values())
        is_flat = all(abs(w) < 1e-12 for w in portfolio["weights"].values())
        if is_flat:
            return inverse_vol_weights(history)          # start (or restart) a cycle
        if held >= REBALANCE_DAYS:
            if strict_hold_limit:
                return {}                                # sell everything today
            return inverse_vol_weights(history)          # rebalance in place
        return None                                      # hold, let weights drift
    return strategy


# ----------------------------------------------------------------------------
# Look-ahead check: weights chosen on a day must not change if we delete
# every row from that day onward.
# ----------------------------------------------------------------------------
def check_no_lookahead(panel: pd.DataFrame, start: str) -> None:
    full = run_backtest(inverse_vol_daily, panel, start=start, end=DEV_END)
    cut_date = full.weights.index[len(full.weights) // 2]
    truncated_panel = panel[panel.index <= cut_date]
    short = run_backtest(inverse_vol_daily, truncated_panel, start=start, end=str(cut_date.date()))
    diff = (full.weights.loc[short.weights.index] - short.weights).abs().max().max()
    assert diff < 1e-12, f"Look-ahead detected: weights differ by {diff}"
    print(f"Look-ahead check passed (weights identical with data cut at {cut_date.date()}).")


# ----------------------------------------------------------------------------
def main():
    panel = load_panel()
    dev = panel[panel.index <= DEV_END]  # the holdout period is never even loaded into the backtest

    # Inverse vol needs 60 days of returns (61 closes) before its first decision.
    # Every strategy starts on that same day so the comparison is fair.
    start = str(dev.index[VOL_WINDOW + 1].date())
    print(f"Common start date: {start}  (first day with {VOL_WINDOW} days of history)")

    check_no_lookahead(dev, start)

    strategies = {
        "1. Equal weight (daily)": equal_weight,
        "2. Inverse vol (daily)": inverse_vol_daily,
        "3. Inverse vol (monthly)": None,  # filled per scenario below
    }
    scenarios = {
        f"strict {MAX_HOLD_DAYS}-day limit": dict(max_hold_days=MAX_HOLD_DAYS, strict=True),
        "no hold limit": dict(max_hold_days=None, strict=False),
    }

    tables, all_results = {}, {}
    for scen_name, cfg in scenarios.items():
        strategies["3. Inverse vol (monthly)"] = make_inverse_vol_monthly(cfg["strict"])
        rows, results = {}, {}
        for name, strat in strategies.items():
            res = run_backtest(strat, dev, start=start, end=DEV_END, max_hold_days=cfg["max_hold_days"])
            row = format_stats(res.stats)
            row["Forced closes"] = str(res.forced_closes)
            rows[name] = row
            results[name] = res
        tables[scen_name] = pd.DataFrame(rows)
        all_results[scen_name] = results
        print(f"\n=== {scen_name} ===")
        print(tables[scen_name].to_string())

    # Average weights each strategy held (strict scenario), to see what inverse vol does.
    strict = all_results[f"strict {MAX_HOLD_DAYS}-day limit"]
    invested = strict["2. Inverse vol (daily)"].weights
    invested = invested[invested.abs().sum(axis=1) > 0]
    avg_w = pd.DataFrame({
        "Equal weight": [1 / 6] * 6,
        "Inverse vol (avg)": invested.mean(),
        "Inverse vol (min)": invested.min(),
        "Inverse vol (max)": invested.max(),
    }, index=ASSETS)
    print("\nInverse-vol weights while invested:")
    print(avg_w.round(3).to_string())

    chart = PROJECT_DIR / "research" / "baselines.png"
    plot_equity(strict, chart, title=f"Baselines, {start} to {DEV_END} (strict 21-day hold limit)")

if __name__ == "__main__":
    main()
