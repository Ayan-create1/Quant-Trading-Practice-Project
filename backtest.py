"""
Backtester for the trading competition.

HOW A DAY WORKS (day t)
-----------------------
1. Overnight: positions held since yesterday move from Close[t-1] to Open[t].
2. Before the open, the strategy is called with history up to and including
   day t-1 ONLY. It returns target weights for day t, e.g. {"Asset_A": 0.2, "Asset_C": -0.1}.
3. At Open[t] we trade from current positions to the targets and pay
   5 bp (0.05%) on the dollar size of every change.
4. During the day, positions move from Open[t] to Close[t]. Equity is recorded at Close[t].

Weights are fractions of equity (positive = long, negative = short), and the
sum of |weights| must be <= 1 (scaled down if a strategy asks for more).
Positions are held overnight, and by default no position may be held longer
than MAX_HOLD_DAYS trading days (it is force-closed if a strategy tries).

USING IT
--------
    from backtest import run_backtest, load_panel

    def my_strategy(history):            # history = data through day t-1
        return {"Asset_A": 0.5, "Asset_B": 0.5}

    result = run_backtest(my_strategy, load_panel(), start="2016-11-01", end="2021-12-31")
    print_report(result)

Returning None means "keep my current positions, don't trade" (they still
drift with prices, and the holding-period limit still applies).

A strategy may also take a second argument, `portfolio`, a dict with
"weights" (current weights going into today) and "holding_days" (how many
trading days each current position has been held).
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

ASSETS = [f"Asset_{letter}" for letter in "ABCDEF"]
COST_RATE = 0.0005  # 5 basis points per unit of position change
MAX_HOLD_DAYS = 21  # about one month of trading days
TRADING_DAYS_PER_YEAR = 252


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def load_panel() -> pd.DataFrame:
    """All six assets in one table. Columns are (asset, field), e.g.
    panel["Asset_A"]["Close"]. Rows are dates, oldest first."""
    from research.load_data import load_all_assets

    data = load_all_assets()
    return pd.concat({name: data[name] for name in ASSETS}, axis=1)


# ----------------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------------
@dataclass
class BacktestResult:
    equity: pd.Series            # account value at each day's close (starts at 1.0)
    weights: pd.DataFrame        # weights set at each day's open (after the |w| <= 1 cap and hold limit)
    turnover: pd.Series          # sum of |change in weight| traded at each open
    costs: pd.Series             # costs paid each day, as a fraction of equity
    holding_days: pd.DataFrame   # how long each position had been held each day
    forced_closes: int = 0       # positions closed because they hit MAX_HOLD_DAYS
    leverage_scaled_days: int = 0  # days the strategy asked for sum|w| > 1
    stats: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _clean_weights(raw) -> tuple[np.ndarray, bool]:
    """Turn the strategy's dict into an array in ASSETS order and enforce sum|w| <= 1."""
    if not isinstance(raw, dict):
        raise TypeError(f"Strategy must return a dict of weights, got {type(raw).__name__}")
    unknown = set(raw) - set(ASSETS)
    if unknown:
        raise ValueError(f"Unknown assets in weights: {sorted(unknown)}")
    w = np.array([float(raw.get(a, 0.0)) for a in ASSETS])
    if not np.all(np.isfinite(w)):
        raise ValueError(f"Weights must be finite numbers, got {raw}")
    gross = np.abs(w).sum()
    scaled = gross > 1 + 1e-12
    if scaled:
        w = w / gross  # shrink every weight by the same factor
    return w, scaled


def _wants_portfolio(strategy: Callable) -> bool:
    try:
        return len(inspect.signature(strategy).parameters) >= 2
    except (TypeError, ValueError):
        return False


def compute_stats(equity: pd.Series, turnover: pd.Series, costs: pd.Series) -> dict:
    daily = equity.pct_change().dropna()
    n = len(daily)
    years = n / TRADING_DAYS_PER_YEAR
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    vol = daily.std()
    peak = equity.cummax()
    return {
        "Total return": total_return,
        "Annualized return": ((1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0)
        if years > 0 else np.nan,
        "Annualized volatility": vol * np.sqrt(TRADING_DAYS_PER_YEAR),
        "Sharpe ratio": daily.mean() / vol * np.sqrt(TRADING_DAYS_PER_YEAR) if vol > 0 else np.nan,
        "Max drawdown": (equity / peak - 1).min(),
        "Turnover per year": turnover.sum() / years if years > 0 else np.nan,
        "Total costs paid": costs.sum(),
        "Trading days": n,
    }


# ----------------------------------------------------------------------------
# The backtest loop
# ----------------------------------------------------------------------------
def run_backtest(
    strategy: Callable,
    panel: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
    cost_rate: float = COST_RATE,
    max_hold_days: int | None = MAX_HOLD_DAYS,
    liquidate_at_end: bool = True,
) -> BacktestResult:
    """Run `strategy` day by day from `start` to `end` (inclusive).

    The strategy may look at ALL history before each day, including days before
    `start` (that is the past, so it's allowed and useful for warm-up).
    """
    panel = panel.sort_index()
    dates = panel.index
    opens = panel.xs("Open", axis=1, level=1)[ASSETS].to_numpy(dtype=float)
    closes = panel.xs("Close", axis=1, level=1)[ASSETS].to_numpy(dtype=float)

    in_range = np.ones(len(dates), dtype=bool)
    if start is not None:
        in_range &= dates >= pd.Timestamp(start)
    if end is not None:
        in_range &= dates <= pd.Timestamp(end)
    day_idx = np.flatnonzero(in_range)
    day_idx = day_idx[day_idx >= 1]  # day 0 has no history to decide from
    if len(day_idx) == 0:
        raise ValueError("No trading days in the requested range")

    pass_portfolio = _wants_portfolio(strategy)
    n_assets = len(ASSETS)

    # Account state. `pos` = dollar value of each position; equity = cash + sum(pos).
    cash, pos = 1.0, np.zeros(n_assets)
    age = np.zeros(n_assets, dtype=int)  # trading days each current position has been held

    first = day_idx[0]
    rec_dates = [dates[first - 1]]  # starting point: $1 at the close before the first trading day
    rec_equity = [1.0]
    rec_w, rec_turn, rec_cost, rec_age = [], [], [], []
    forced, scaled_days = 0, 0

    for i in day_idx:
        # 1. Overnight move: yesterday's close -> today's open.
        pos = pos * (opens[i] / closes[i - 1])
        equity_open = cash + pos.sum()
        current_w = pos / equity_open if equity_open != 0 else np.zeros(n_assets)

        # 2. Ask the strategy. It sees rows 0..i-1 only (a fresh copy, so it can't
        #    change our data either).
        history = panel.iloc[:i].copy()
        if pass_portfolio:
            portfolio = {
                "weights": dict(zip(ASSETS, current_w)),
                "holding_days": dict(zip(ASSETS, age.tolist())),
            }
            raw = strategy(history, portfolio)
        else:
            raw = strategy(history)
        if raw is None:  # None means "keep what I have": no trade at all
            target, scaled = current_w.copy(), False
        else:
            target, scaled = _clean_weights(raw)
        scaled_days += int(scaled)

        # Holding-period limit: a position that keeps the same direction ages by
        # one day; if it would pass the limit, close it instead.
        same_side = (np.sign(target) == np.sign(current_w)) & (target != 0)
        new_age = np.where(same_side, age + 1, np.where(target != 0, 1, 0))
        if max_hold_days is not None:
            too_old = new_age > max_hold_days
            forced += int(too_old.sum())
            target = np.where(too_old, 0.0, target)
            new_age = np.where(too_old, 0, new_age)
        age = new_age

        # 3. Trade at the open and pay costs on the change only.
        #    Costs come out of equity, so we size the trade so that the weights
        #    AFTER paying costs equal the targets (otherwise a position would look
        #    slightly "off" tomorrow and get re-traded for no reason). Because the
        #    cost is tiny, a few rounds of "guess equity, recompute" converge exactly.
        equity_after = equity_open
        for _ in range(10):
            trade = target * equity_after - pos
            new_equity_after = equity_open - cost_rate * np.abs(trade).sum()
            if abs(new_equity_after - equity_after) < 1e-15:
                break
            equity_after = new_equity_after
        target_pos = target * equity_after
        trade = target_pos - pos
        cost = cost_rate * np.abs(trade).sum()
        cash -= trade.sum() + cost
        pos = target_pos

        # 4. Intraday move: today's open -> today's close.
        pos = pos * (closes[i] / opens[i])
        equity_close = cash + pos.sum()

        rec_dates.append(dates[i])
        rec_equity.append(equity_close)
        rec_w.append(target)
        rec_turn.append(np.abs(trade).sum() / equity_open)
        rec_cost.append(cost / equity_open)
        rec_age.append(age.copy())

    # Close everything at the end so the exit cost is counted.
    if liquidate_at_end:
        exit_cost = cost_rate * np.abs(pos).sum()
        rec_equity[-1] -= exit_cost
        rec_cost[-1] += exit_cost / (rec_equity[-1] + exit_cost)
        rec_turn[-1] += np.abs(pos).sum() / (rec_equity[-1] + exit_cost)

    trade_dates = pd.DatetimeIndex(rec_dates[1:])
    equity = pd.Series(rec_equity, index=pd.DatetimeIndex(rec_dates), name="equity")
    result = BacktestResult(
        equity=equity,
        weights=pd.DataFrame(rec_w, index=trade_dates, columns=ASSETS),
        turnover=pd.Series(rec_turn, index=trade_dates, name="turnover"),
        costs=pd.Series(rec_cost, index=trade_dates, name="costs"),
        holding_days=pd.DataFrame(rec_age, index=trade_dates, columns=ASSETS),
        forced_closes=forced,
        leverage_scaled_days=scaled_days,
    )
    result.stats = compute_stats(result.equity, result.turnover, result.costs)
    return result


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def format_stats(stats: dict) -> dict:
    out = {}
    for k, v in stats.items():
        if k == "Sharpe ratio":
            out[k] = f"{v:.2f}"
        elif k == "Turnover per year":
            out[k] = f"{v:.1f}x"
        elif k == "Trading days":
            out[k] = f"{v:d}"
        elif k == "Total costs paid":
            out[k] = f"{v:.2%}"
        else:
            out[k] = f"{v:.1%}"
    return out


def print_report(result: BacktestResult, name: str = "Strategy") -> None:
    print(f"\n{name}  ({result.equity.index[0].date()} to {result.equity.index[-1].date()})")
    for k, v in format_stats(result.stats).items():
        print(f"  {k:<22} {v}")
    print(f"  {'Forced closes (hold)':<22} {result.forced_closes}")
    print(f"  {'Days |w| scaled to 1':<22} {result.leverage_scaled_days}")


def plot_equity(results: dict[str, BacktestResult], out_path: Path | str, title: str = "Equity curve") -> None:
    """Equity curve (top) and drawdown (bottom) for one or more strategies."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for (name, res), color in zip(results.items(), colors):
        eq = res.equity
        ax1.plot(eq.index, eq.values, color=color, linewidth=1.8, label=name)
        dd = (eq / eq.cummax() - 1) * 100
        ax2.plot(dd.index, dd.values, color=color, linewidth=1.5)
        ax1.annotate(f"{name}  {res.stats['Total return']:+.0%}", (eq.index[-1], eq.iloc[-1]),
                     xytext=(4, 0), textcoords="offset points", fontsize=9, color="#0b0b0b", va="center")
    ax1.set_ylabel("Account value ($1 start)", color="#52514e")
    ax2.set_ylabel("Drawdown (%)", color="#52514e")
    ax1.set_title(title, loc="left", fontsize=13, color="#0b0b0b")
    if len(results) > 1:
        ax1.legend(frameon=False, loc="upper left")
    for ax in (ax1, ax2):
        ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
        ax.tick_params(colors="#52514e", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, facecolor="#fcfcfb", bbox_inches="tight")
    plt.close(fig)
    print(f"Saved chart to {out_path}")


# ----------------------------------------------------------------------------
# Demo: equal weight in all six assets, development period only
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    def equal_weight(history):
        return {a: 1 / len(ASSETS) for a in ASSETS}

    panel = load_panel()
    res = run_backtest(equal_weight, panel, start="2016-10-31", end="2021-12-31")
    print_report(res, "Equal weight (demo)")
    plot_equity({"Equal weight": res}, PROJECT_DIR / "research" / "backtest_demo.png",
                title="Demo backtest: equal weight A-F, 2016-2021")
