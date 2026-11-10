"""
Robustness checks for the momentum strategy (development data 2016-2021 only).

  1. Parameter grid: momentum lookback 63/126/189/252 for "Momentum only", and
     moving-average length 30/50/100/200 x lookback for "AVERAGE" (the version
     that uses both signals; Momentum only has no moving average).
  2. Finer lookback sweep for Momentum only (42..252 in steps of 21): is 126 a lone spike?
  3. The chosen strategy (Momentum only, 126 days) at 5, 10 and 20 bp costs, year by year.
  4. Results with the COVID crash removed.
  5. Per asset: does the momentum signal help each asset on its own?

Run from the project folder:
    .venv/bin/python research/robustness.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "research"))
from backtest import ASSETS, compute_stats, load_panel, run_backtest  # noqa: E402
from baselines import DEV_END, inverse_vol_daily  # noqa: E402
from signals import COMBINERS, make_signal_strategy, momentum_signal  # noqa: E402

OUT = PROJECT_DIR / "research"
MA_LENGTHS = [30, 50, 100, 200]
LOOKBACKS = [63, 126, 189, 252]
CHOSEN = dict(trend_window=50, mom_window=126)   # chosen BEFORE this grid was run


def stats_of(equity: pd.Series) -> dict:
    daily = equity.pct_change().dropna()
    vol = daily.std()
    return {
        "Return": equity.iloc[-1] / equity.iloc[0] - 1,
        "Sharpe": daily.mean() / vol * np.sqrt(252) if vol > 0 else np.nan,
        "Max DD": (equity / equity.cummax() - 1).min(),
    }


def yearly_table(res) -> pd.DataFrame:
    rows = {}
    for year, eq in res.equity.groupby(res.equity.index.year):
        # include the previous year's last close so each year's return is complete
        prev = res.equity[res.equity.index < eq.index[0]]
        if len(prev):
            eq = pd.concat([prev.iloc[-1:], eq])
        rows[year] = stats_of(eq)
    return pd.DataFrame(rows).T


# ----------------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------------
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ORANGE = ["#fde3d6", "#f8bfa4", "#f39a72", "#eb6834", "#c4501f", "#9a3d15", "#6e2a0c"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e5e4df", "#fcfcfb"


def plot_heatmaps(sharpe: pd.DataFrame, dd: pd.DataFrame, chosen_cell, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    panels = [
        (axes[0], sharpe, LinearSegmentedColormap.from_list("b", BLUE), "Sharpe ratio (darker = better)",
         lambda v: f"{v:.2f}"),
        (axes[1], -dd * 100, LinearSegmentedColormap.from_list("o", ORANGE), "Max drawdown (darker = deeper loss)",
         lambda v: f"−{v:.0f}%"),
    ]
    for ax, data, cmap, title, fmt in panels:
        vals = data.to_numpy(dtype=float)
        im = ax.imshow(vals, cmap=cmap, aspect="auto", vmin=np.nanmin(vals), vmax=np.nanmax(vals))
        lo, hi = np.nanmin(vals), np.nanmax(vals)
        for r in range(vals.shape[0]):
            for c in range(vals.shape[1]):
                frac = (vals[r, c] - lo) / (hi - lo) if hi > lo else 0
                ax.text(c, r, fmt(vals[r, c]), ha="center", va="center", fontsize=11,
                        color="white" if frac > 0.55 else INK)
        r0, c0 = chosen_cell
        ax.add_patch(Rectangle((c0 - 0.5, r0 - 0.5), 1, 1, fill=False, edgecolor=INK, linewidth=2.2))
        ax.axhline(0.5, color=SURFACE, linewidth=6)   # gap between "Momentum only" row and the AVERAGE grid
        ax.set_xticks(range(len(data.columns)), data.columns)
        ax.set_yticks(range(len(data.index)), data.index)
        ax.set_xlabel("Momentum lookback (trading days)", color=INK2)
        ax.set_title(title, loc="left", fontsize=12, color=INK)
        ax.tick_params(colors=INK2, labelsize=10, length=0)
        for s in ax.spines.values():
            s.set_visible(False)
    fig.suptitle("Parameter grid, 2017-10-31 to 2021-12-31 (strict 21-day limit, 5 bp costs). "
                 "Boxed = the version chosen beforehand.", x=0.01, ha="left", fontsize=11, color=INK2)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_sweep(sweep: pd.DataFrame, baseline_sharpe: float, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(sweep.index, sweep["Sharpe"], color="#2a78d6", linewidth=2, marker="o", markersize=7,
            markeredgecolor=SURFACE, markeredgewidth=2, label="Momentum only")
    ax.axhline(baseline_sharpe, color=INK2, linewidth=1.2, linestyle="--")
    ax.annotate(f"Inverse-vol baseline {baseline_sharpe:.2f}", (sweep.index[-1], baseline_sharpe),
                xytext=(0, -14), textcoords="offset points", ha="right", fontsize=9, color=INK2)
    best = sweep["Sharpe"].idxmax()
    ax.annotate(f"{sweep.loc[126, 'Sharpe']:.2f}", (126, sweep.loc[126, "Sharpe"]), xytext=(0, 10),
                textcoords="offset points", ha="center", fontsize=9, color=INK)
    if best != 126:
        ax.annotate(f"{sweep.loc[best, 'Sharpe']:.2f}", (best, sweep.loc[best, "Sharpe"]), xytext=(0, 10),
                    textcoords="offset points", ha="center", fontsize=9, color=INK)
    ax.set_ylim(min(sweep["Sharpe"].min(), baseline_sharpe) - 0.08, sweep["Sharpe"].max() + 0.08)
    ax.set_xticks(sweep.index)
    ax.set_xlabel("Momentum lookback (trading days)", color=INK2)
    ax.set_ylabel("Sharpe ratio", color=INK2)
    ax.set_title("Momentum only: Sharpe vs lookback, 2017-10-31 to 2021-12-31", loc="left", fontsize=12, color=INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK2, labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ----------------------------------------------------------------------------
def main():
    panel = load_panel()
    dev = panel[panel.index <= DEV_END]  # holdout never loaded

    # The 252-day lookback needs 253 closes, so every grid cell starts on the same later day.
    grid_start = str(dev.index[252 + 1].date())
    main_start = str(dev.index[126 + 1].date())  # the chosen 126-day version can start earlier
    print(f"Grid start {grid_start}; chosen-strategy start {main_start}")

    def run(strategy, start=grid_start, cost=0.0005, data=dev):
        return run_backtest(strategy, data, start=start, end=DEV_END, cost_rate=cost)

    base_grid = run(inverse_vol_daily)
    print(f"Inverse-vol baseline over grid period: Sharpe {base_grid.stats['Sharpe ratio']:.2f}, "
          f"Max DD {base_grid.stats['Max drawdown']:.1%}")

    # 1. Grid --------------------------------------------------------------------
    sharpe, dd, ret = {}, {}, {}
    def record(row, col, res):
        sharpe.setdefault(row, {})[col] = res.stats["Sharpe ratio"]
        dd.setdefault(row, {})[col] = res.stats["Max drawdown"]
        ret.setdefault(row, {})[col] = res.stats["Annualized return"]

    for lb in LOOKBACKS:
        record("Momentum only", lb, run(make_signal_strategy(COMBINERS["Momentum only"], mom_window=lb)))
    for ma in MA_LENGTHS:
        for lb in LOOKBACKS:
            record(f"AVERAGE, MA {ma}", lb, run(make_signal_strategy(COMBINERS["AVERAGE"], ma, lb)))
    sharpe, dd, ret = (pd.DataFrame(x).T for x in (sharpe, dd, ret))
    print("\nSharpe\n", sharpe.round(2).to_string())
    print("\nMax drawdown\n", (dd * 100).round(1).to_string())
    print("\nAnnualized return\n", (ret * 100).round(1).to_string())
    plot_heatmaps(sharpe, dd, (0, LOOKBACKS.index(126)), OUT / "robustness_heatmaps.png")

    # 2. Fine sweep ---------------------------------------------------------------
    sweep = {}
    for lb in range(42, 253, 21):
        s = run(make_signal_strategy(COMBINERS["Momentum only"], mom_window=lb)).stats
        sweep[lb] = {"Sharpe": s["Sharpe ratio"], "Max DD": s["Max drawdown"], "Ann. return": s["Annualized return"]}
    sweep = pd.DataFrame(sweep).T
    print("\nFine sweep, Momentum only\n", sweep.round(3).to_string())
    plot_sweep(sweep, base_grid.stats["Sharpe ratio"], OUT / "robustness_sweep.png")

    # 3. Costs and year by year (chosen strategy, its own full period) -------------
    chosen = make_signal_strategy(COMBINERS["Momentum only"], **CHOSEN)
    by_cost = {bp: run(chosen, start=main_start, cost=bp / 10000) for bp in (5, 10, 20)}
    base_main = {bp: run(inverse_vol_daily, start=main_start, cost=bp / 10000) for bp in (5, 10)}
    print("\nCost sensitivity (chosen strategy)")
    for bp, res in by_cost.items():
        s = res.stats
        print(f"  {bp:>2} bp: ann return {s['Annualized return']:.1%}, Sharpe {s['Sharpe ratio']:.2f}, "
              f"Max DD {s['Max drawdown']:.1%}, costs {s['Total costs paid']:.2%}")
    for bp, res in base_main.items():
        s = res.stats
        print(f"  baseline {bp} bp: ann return {s['Annualized return']:.1%}, Sharpe {s['Sharpe ratio']:.2f}, "
              f"Max DD {s['Max drawdown']:.1%}")

    years = pd.concat({
        "Momentum 5bp": yearly_table(by_cost[5]),
        "Momentum 10bp": yearly_table(by_cost[10]),
        "Baseline 5bp": yearly_table(base_main[5]),
    }, axis=1)
    print("\nYear by year\n", years.round(3).to_string())

    # 4. Without the COVID crash ---------------------------------------------------
    def drop_window(res, a="2020-02-01", b="2020-04-30"):
        r = res.equity.pct_change().dropna()
        r = r[(r.index < a) | (r.index > b)]
        return stats_of((1 + r).cumprod())
    print("\nExcluding Feb-Apr 2020")
    print("  Momentum 5bp:", {k: round(v, 3) for k, v in drop_window(by_cost[5]).items()})
    print("  Baseline 5bp:", {k: round(v, 3) for k, v in drop_window(base_main[5]).items()})

    # 5. Per asset: one asset alone, buy-and-hold vs momentum on/off -------------
    def single(asset, use_signal):
        def strat(history):
            if use_signal:
                closes = history.xs("Close", axis=1, level=1)[ASSETS]
                return {asset: float(momentum_signal(closes, 126)[asset])}
            return {asset: 1.0}
        return strat
    per_asset = {}
    for a in ASSETS:
        hold = run(single(a, False), start=main_start).stats
        mom = run(single(a, True), start=main_start).stats
        per_asset[a] = {
            "Hold Sharpe": hold["Sharpe ratio"], "Mom Sharpe": mom["Sharpe ratio"],
            "Hold Max DD": hold["Max drawdown"], "Mom Max DD": mom["Max drawdown"],
            "Hold ann ret": hold["Annualized return"], "Mom ann ret": mom["Annualized return"],
        }
    print("\nPer asset (alone)\n", pd.DataFrame(per_asset).T.round(3).to_string())


if __name__ == "__main__":
    main()
