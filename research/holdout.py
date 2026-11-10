"""
ONE-TIME holdout test, 2022-01-03 to 2023-10-06. Nothing is tuned here.

Frozen strategy (imported unchanged from final_signal.py):
  Multi signal = (trend 50 + mean of momentum 63/126/252) / 2, per asset
  weight = inverse-vol (60-day) weight x signal, rest in cash, no vol targeting
  strict 21-day hold limit, 5 bp costs per side, trades at next day's open

Every strategy starts flat and makes its first trade at the open of 2022-01-03,
using data through 2021-12-31 only (earlier data is the past, so it's allowed for warm-up).

Run from the project folder:
    .venv/bin/python research/holdout.py
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "research"))
from backtest import ASSETS, MAX_HOLD_DAYS, format_stats, load_panel, plot_equity, run_backtest  # noqa: E402
from baselines import equal_weight, inverse_vol_daily, make_inverse_vol_monthly  # noqa: E402
from final_signal import make_strategy  # noqa: E402
from robustness import stats_of  # noqa: E402

HOLDOUT_START = "2022-01-01"
FINAL = make_strategy(50, (63, 126, 252))  # frozen: no vol target


def period_stats(res, a, b):
    eq = res.equity
    before = eq[eq.index < pd.Timestamp(a)]
    e = eq[(eq.index >= pd.Timestamp(a)) & (eq.index <= pd.Timestamp(b))]
    if len(before):
        e = pd.concat([before.iloc[-1:], e])
    return stats_of(e)


def main():
    panel = load_panel()
    end = str(panel.index[-1].date())
    print(f"Holdout: {HOLDOUT_START} to {end}")

    strategies = {
        "Final (Multi)": FINAL,
        "Equal weight": equal_weight,
        "Inv vol (daily)": inverse_vol_daily,
        "Inv vol (monthly)": make_inverse_vol_monthly(strict_hold_limit=True),
    }
    results = {n: run_backtest(s, panel, start=HOLDOUT_START, end=end, max_hold_days=MAX_HOLD_DAYS)
               for n, s in strategies.items()}

    # Look-ahead check on the holdout too: cutting the data mid-way must not change earlier weights.
    cut = results["Final (Multi)"].weights.index[len(results["Final (Multi)"].weights) // 2]
    short = run_backtest(FINAL, panel[panel.index <= cut], start=HOLDOUT_START, end=str(cut.date()))
    diff = (results["Final (Multi)"].weights.loc[short.weights.index] - short.weights).abs().max().max()
    assert diff < 1e-12, f"look-ahead: {diff}"
    print(f"Look-ahead check passed (cut at {cut.date()}).")

    rows = {}
    for n, r in results.items():
        row = format_stats(r.stats)
        row["Calmar"] = f"{r.stats['Annualized return'] / -r.stats['Max drawdown']:.2f}"
        row["Avg % invested"] = f"{r.weights.abs().sum(axis=1).mean():.0%}"
        rows[n] = row
    print("\nFull holdout\n", pd.DataFrame(rows).to_string())

    for label, a, b in [("2022 only", "2022-01-01", "2022-12-31"), ("2023 (to Oct 6)", "2023-01-01", end)]:
        t = pd.DataFrame({n: period_stats(r, a, b) for n, r in results.items()}).T
        print(f"\n{label}\n", t.round(3).to_string())

    # Context only (no decisions made from this): quarters, exposure, and each asset's own 2022-23 path.
    q = pd.DataFrame({n: r.equity.resample("QE").last().pct_change() for n, r in results.items()})
    first_q = {n: r.equity.resample("QE").last().iloc[0] / r.equity.iloc[0] - 1 for n, r in results.items()}
    q.iloc[0] = pd.Series(first_q)
    print("\nQuarterly returns\n", q.round(3).to_string())
    w = results["Final (Multi)"].weights
    print("\nFinal strategy: avg % invested per quarter\n",
          w.abs().sum(axis=1).resample("QE").mean().round(2).to_string())
    print("\nFinal strategy: avg weight per asset (2022, 2023)\n",
          w.groupby(w.index.year).mean().round(3).to_string())
    closes = panel.xs("Close", axis=1, level=1)[ASSETS]
    asset_rows = {}
    for a in ASSETS:
        c = closes[a]
        c22 = c[(c.index >= "2021-12-31") & (c.index <= "2022-12-31")]
        c23 = c[c.index >= "2022-12-30"]
        cfull = c[c.index >= "2021-12-31"]
        asset_rows[a] = {"2022": c22.iloc[-1] / c22.iloc[0] - 1, "2023 YTD": c23.iloc[-1] / c23.iloc[0] - 1,
                         "Max DD": (cfull / cfull.cummax() - 1).min()}
    print("\nEach asset's own price change\n", pd.DataFrame(asset_rows).T.round(3).to_string())

    plot_equity(results, PROJECT_DIR / "research" / "holdout.png",
                title=f"Holdout (never used for tuning): {HOLDOUT_START} to {end}, strict 21-day limit, 5 bp")


if __name__ == "__main__":
    main()
