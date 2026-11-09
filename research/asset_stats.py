"""
Per-asset statistics for Assets A-F, shown separately for the development
period (2016-2021) and the holdout period (2022-2023).

Run from the project folder:
    .venv/bin/python research/asset_stats.py
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.load_data import PROJECT_DIR, load_all_assets  # noqa: E402

TRADING_DAYS_PER_YEAR = 252  # standard convention for US stock markets
PERIODS = {
    "Development 2016-2021": ("2016-01-01", "2021-12-31"),
    "Holdout 2022-2023": ("2022-01-01", "2023-12-31"),
}


def daily_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Percent change from one day's close to the next. The very first day has no
    previous close, so it has no return and is dropped."""
    return closes.pct_change().dropna()


def growth_curve(returns: pd.Series) -> pd.Series:
    """Value of $1 invested at the start of the period, day by day."""
    return (1 + returns).cumprod()


def drawdown(returns: pd.Series) -> pd.Series:
    """How far below its highest point so far the investment is, each day (0 = at a new high)."""
    wealth = growth_curve(returns)
    running_peak = np.maximum(wealth.cummax(), 1.0)  # the starting $1 counts as a peak
    return wealth / running_peak - 1


def summarize(returns: pd.Series) -> dict:
    n_days = len(returns)
    total_growth = (1 + returns).prod()
    ann_return = total_growth ** (TRADING_DAYS_PER_YEAR / n_days) - 1  # compound annual growth rate
    ann_vol = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)  # risk-free rate = 0
    return {
        "Avg daily return": returns.mean(),
        "Annualized return": ann_return,
        "Annualized volatility": ann_vol,
        "Sharpe ratio": sharpe,
        "Max drawdown": drawdown(returns).min(),
    }


def fmt_table(stats: pd.DataFrame) -> pd.DataFrame:
    out = stats.copy().astype(object)
    for col in stats.columns:
        if col == "Sharpe ratio":
            out[col] = stats[col].map("{:.2f}".format)
        elif col == "Avg daily return":
            out[col] = stats[col].map("{:.3%}".format)
        else:
            out[col] = stats[col].map("{:.1%}".format)
    return out


def plot_drawdowns(returns: pd.DataFrame, out_path: Path) -> None:
    """Drawdown is recomputed from scratch at the start of each period, so the
    lowest point in each section matches the 'Max drawdown' in that period's table."""
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex=True, sharey=True)
    for ax, name in zip(axes.flat, returns.columns):
        for label, (start, end) in PERIODS.items():
            dd = drawdown(returns.loc[start:end, name]) * 100
            ax.fill_between(dd.index, dd, 0, color="#2a78d6", alpha=0.35, linewidth=0)
            ax.plot(dd.index, dd, color="#2a78d6", linewidth=1.2)
            worst_day = dd.idxmin()
            ax.annotate(f"{dd.min():.0f}%", (worst_day, dd.min()), xytext=(4, -2),
                        textcoords="offset points", fontsize=8, color="#0b0b0b", va="top")
        ax.axvspan(pd.Timestamp("2022-01-01"), returns.index.max(), color="#000000", alpha=0.05, linewidth=0)
        ax.axvline(pd.Timestamp("2022-01-01"), color="#52514e", linewidth=0.8, linestyle="--")
        ax.set_title(name, loc="left", fontsize=11, color="#0b0b0b")
        ax.set_ylabel("Drawdown (%)", color="#52514e")
        ax.set_ylim(-100, 5)
        ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
        ax.tick_params(colors="#52514e", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.suptitle("Drawdown from previous peak (resets at 2022; shaded = holdout)", x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, facecolor="#fcfcfb")
    print(f"Saved chart to {out_path}")


if __name__ == "__main__":
    data = load_all_assets()
    closes = pd.DataFrame({name: df["Close"] for name, df in data.items()})
    returns = daily_returns(closes)

    pd.set_option("display.width", 140)
    for label, (start, end) in PERIODS.items():
        r = returns.loc[start:end]
        print(f"\n=== {label}  ({r.index.min().date()} to {r.index.max().date()}, {len(r)} trading days) ===")
        stats = pd.DataFrame({name: summarize(r[name]) for name in r.columns}).T
        print(fmt_table(stats).to_string())

        corr = r.corr()
        print("\nCorrelation of daily returns:")
        print(corr.round(2).to_string())
        off_diag = corr.values[np.triu_indices(len(corr), k=1)]
        print(f"Average correlation between pairs: {off_diag.mean():.2f}")

    print()
    plot_drawdowns(returns, PROJECT_DIR / "research" / "drawdowns.png")
