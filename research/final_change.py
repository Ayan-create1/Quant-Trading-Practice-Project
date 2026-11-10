"""
Final change: 25% equal weight (always invested) + 75% frozen Multi strategy.

    weight[asset] = 0.25 * (1/6) + 0.75 * multi_weight[asset]

Motivation (stated by the user): slow re-entry seen in the dev period (2019, 2021) and the
scoring weights. NOTE: this change was decided AFTER the holdout was seen, so the 2022-23
rerun below is for reporting only and is NOT an unbiased test.

No other variations are tried.

Run from the project folder:
    .venv/bin/python research/final_change.py
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "research"))
from backtest import ASSETS, format_stats, load_panel, plot_equity, run_backtest  # noqa: E402
from baselines import DEV_END, equal_weight, inverse_vol_daily  # noqa: E402
from final_signal import make_strategy  # noqa: E402
from holdout import period_stats  # noqa: E402
from robustness import yearly_table  # noqa: E402

EW_SHARE = 0.25
MULTI = make_strategy(50, (63, 126, 252))


def blended(history):
    multi = MULTI(history)
    return {a: EW_SHARE / len(ASSETS) + (1 - EW_SHARE) * multi[a] for a in ASSETS}


def table(results):
    rows = {}
    for n, r in results.items():
        row = format_stats(r.stats)
        row.pop("Trading days")
        row["Calmar"] = f"{r.stats['Annualized return'] / -r.stats['Max drawdown']:.2f}"
        row["Avg % invested"] = f"{r.weights.abs().sum(axis=1).mean():.0%}"
        rows[n] = row
    return pd.DataFrame(rows)


def main():
    panel = load_panel()
    dev = panel[panel.index <= DEV_END]
    dev_start = str(dev.index[273 + 1].date())  # same start as final_signal.py

    # Look-ahead check on dev.
    full = run_backtest(blended, dev, start=dev_start, end=DEV_END)
    cut = full.weights.index[len(full.weights) // 2]
    short = run_backtest(blended, dev[dev.index <= cut], start=dev_start, end=str(cut.date()))
    assert (full.weights.loc[short.weights.index] - short.weights).abs().max().max() < 1e-12
    print(f"Look-ahead check passed (cut at {cut.date()}).")

    strategies = {"25% EW + 75% Multi": blended, "Multi (frozen)": MULTI,
                  "Equal weight": equal_weight, "Inv vol (daily)": inverse_vol_daily}

    # 1. Dev period ------------------------------------------------------------------
    dev_res = {n: run_backtest(s, dev, start=dev_start, end=DEV_END) for n, s in strategies.items()}
    print(f"\nDEV {dev_start} to {DEV_END}\n", table(dev_res).to_string())
    s = dev_res["25% EW + 75% Multi"].stats
    print(f"\nExpectation check: Sharpe {s['Sharpe ratio']:.2f} (expected ~1.4), "
          f"Max DD {s['Max drawdown']:.1%} (expected ~-21%)")
    years = pd.concat({n: yearly_table(dev_res[n]) for n in ["25% EW + 75% Multi", "Multi (frozen)", "Equal weight"]},
                      axis=1)
    print("\nDev year by year\n", years.round(3).to_string())
    covid = {n: r.equity.asof(pd.Timestamp("2020-03-23")) / r.equity.asof(pd.Timestamp("2020-02-19")) - 1
             for n, r in dev_res.items()}
    print("\nCOVID crash (Feb 19 - Mar 23 2020)\n", pd.Series(covid).round(3).to_string())

    # 2. Holdout rerun (reporting only, NOT unbiased) ----------------------------------
    end = str(panel.index[-1].date())
    ho = {n: run_backtest(s, panel, start="2022-01-01", end=end) for n, s in strategies.items()}
    print(f"\nHOLDOUT 2022-01-03 to {end} (NOT an unbiased test)\n", table(ho).to_string())
    for label, a, b in [("2022 only", "2022-01-01", "2022-12-31"), ("2023 (to Oct 6)", "2023-01-01", end)]:
        print(f"\n{label}\n", pd.DataFrame({n: period_stats(r, a, b) for n, r in ho.items()}).T.round(3).to_string())

    out = PROJECT_DIR / "research"
    plot_equity(dev_res, out / "final_change_dev.png", title=f"Dev period, {dev_start} to {DEV_END}")
    plot_equity(ho, out / "final_change_holdout.png",
                title=f"2022-01-03 to {end}: reporting only, NOT an unbiased test (change made after seeing it)")


if __name__ == "__main__":
    main()
