"""
Trend and momentum signals on top of inverse-volatility weights (2016-2021 only).

Two on/off signals, computed per asset from closes up to YESTERDAY only:
  trend    = 1 if yesterday's close > average of the last 50 closes, else 0
  momentum = 1 if the return over the last 126 trading days > 0, else 0

Each strategy holds (inverse-vol weight) x (signal) in each asset. Whatever is
not invested sits in cash (earns 0%). Five ways to use the signals:
  Trend only, Momentum only, AND (both 1), OR (either 1), AVERAGE (0 / 0.5 / 1).

Run from the project folder:
    .venv/bin/python research/signals.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "research"))
from backtest import ASSETS, MAX_HOLD_DAYS, format_stats, load_panel, plot_equity, run_backtest  # noqa: E402
from baselines import (  # noqa: E402
    DEV_END, VOL_WINDOW, equal_weight, inverse_vol_daily, inverse_vol_weights, make_inverse_vol_monthly,
)

TREND_WINDOW = 50   # days in the moving average
MOM_WINDOW = 126    # about 6 months of trading days


# ----------------------------------------------------------------------------
# Signals. `history` ends at yesterday's close, so the last row is day t-1.
# ----------------------------------------------------------------------------
def trend_signal(closes: pd.DataFrame, window: int = TREND_WINDOW) -> pd.Series:
    """1 where the latest close is above its `window`-day average (that average includes the latest close)."""
    last = closes.iloc[-1]
    ma = closes.iloc[-window:].mean()
    return (last > ma).astype(float)


def momentum_signal(closes: pd.DataFrame, window: int = MOM_WINDOW) -> pd.Series:
    """1 where the return from `window` days ago to the latest close is positive."""
    past_return = closes.iloc[-1] / closes.iloc[-(window + 1)] - 1
    return (past_return > 0).astype(float)


COMBINERS = {
    "Trend only":    lambda t, m: t,
    "Momentum only": lambda t, m: m,
    "AND":           lambda t, m: t * m,              # both must be 1
    "OR":            lambda t, m: np.maximum(t, m),   # either is 1
    "AVERAGE":       lambda t, m: (t + m) / 2,        # 0, 0.5 or 1
}


def make_signal_strategy(combine, trend_window=TREND_WINDOW, mom_window=MOM_WINDOW):
    """Inverse-vol weight x combined signal, recomputed every day. Unused weight = cash."""
    def strategy(history):
        closes = history.xs("Close", axis=1, level=1)[ASSETS]
        signal = combine(trend_signal(closes, trend_window), momentum_signal(closes, mom_window))
        base = pd.Series(inverse_vol_weights(history))
        return (base * signal).to_dict()
    return strategy


# ----------------------------------------------------------------------------
# Look-ahead checks
# ----------------------------------------------------------------------------
def check_signal_timing(panel: pd.DataFrame) -> None:
    """The weights chosen for day t must equal what we'd compute by hand from closes through day t-1,
    and must NOT change if we secretly alter day t's prices."""
    closes = panel.xs("Close", axis=1, level=1)[ASSETS]
    i = 600  # an arbitrary day in the middle
    by_hand_trend = (closes.iloc[i - 1] > closes.iloc[i - TREND_WINDOW:i].mean()).astype(float)
    by_hand_mom = (closes.iloc[i - 1] / closes.iloc[i - 1 - MOM_WINDOW] > 1).astype(float)
    hist = panel.iloc[:i]
    assert (trend_signal(hist.xs("Close", axis=1, level=1)[ASSETS]) == by_hand_trend).all()
    assert (momentum_signal(hist.xs("Close", axis=1, level=1)[ASSETS]) == by_hand_mom).all()

    strat = make_signal_strategy(COMBINERS["AVERAGE"])
    tampered = panel.copy()
    tampered.iloc[i:] *= 3  # wreck today's and all future prices
    assert strat(panel.iloc[:i]) == strat(tampered.iloc[:i])


def check_no_lookahead(panel: pd.DataFrame, start: str) -> None:
    """Rerun every signal strategy with the second half of the data deleted; early weights must not change."""
    cut_date = panel.index[(panel.index.get_loc(pd.Timestamp(start)) + len(panel)) // 2]
    for name, combine in COMBINERS.items():
        strat = make_signal_strategy(combine)
        full = run_backtest(strat, panel, start=start, end=DEV_END)
        short = run_backtest(strat, panel[panel.index <= cut_date], start=start, end=str(cut_date.date()))
        diff = (full.weights.loc[short.weights.index] - short.weights).abs().max().max()
        assert diff < 1e-12, f"{name}: look-ahead detected, weights differ by {diff}"
    print(f"Look-ahead checks passed (hand-computed signals match; weights identical with data cut at {cut_date.date()}).")


# ----------------------------------------------------------------------------
def extra_stats(res, closes: pd.DataFrame) -> dict:
    """How much of the account was invested, and how each strategy did in specific bad periods."""
    gross = res.weights.abs().sum(axis=1)
    eq = res.equity

    def period_return(a, b):
        e = eq[(eq.index >= a) & (eq.index <= b)]
        return e.iloc[-1] / e.iloc[0] - 1

    return {
        "Avg % invested": f"{gross.mean():.0%}",
        "Days fully in cash": f"{(gross < 1e-9).mean():.0%}",
        "Q4 2018 (Oct-Dec)": f"{period_return('2018-09-28', '2018-12-31'):+.1%}",
        "COVID crash (Feb 19-Mar 23 2020)": f"{period_return('2020-02-19', '2020-03-23'):+.1%}",
        "2020 full-year": f"{period_return('2019-12-31', '2020-12-31'):+.1%}",
    }


def main():
    panel = load_panel()
    dev = panel[panel.index <= DEV_END]  # holdout (2022-23) is never loaded

    # Momentum needs 126 returns (127 closes) before its first decision. Everyone,
    # baselines included, starts that same day so the comparison is fair.
    warmup = max(MOM_WINDOW, TREND_WINDOW, VOL_WINDOW) + 1
    start = str(dev.index[warmup].date())
    print(f"Common start date: {start}")

    check_signal_timing(dev)
    check_no_lookahead(dev, start)

    closes = dev.xs("Close", axis=1, level=1)[ASSETS]
    scenarios = {
        f"strict {MAX_HOLD_DAYS}-day limit": dict(max_hold_days=MAX_HOLD_DAYS, strict=True),
        "no hold limit": dict(max_hold_days=None, strict=False),
    }
    all_results = {}
    for scen_name, cfg in scenarios.items():
        strategies = {
            "Equal weight": equal_weight,
            "Inv vol (daily)": inverse_vol_daily,
            "Inv vol (monthly)": make_inverse_vol_monthly(cfg["strict"]),
        }
        strategies.update({name: make_signal_strategy(c) for name, c in COMBINERS.items()})

        rows, results = {}, {}
        for name, strat in strategies.items():
            res = run_backtest(strat, dev, start=start, end=DEV_END, max_hold_days=cfg["max_hold_days"])
            row = format_stats(res.stats)
            row.pop("Trading days")
            row["Calmar (ann. return / |max DD|)"] = f"{res.stats['Annualized return'] / -res.stats['Max drawdown']:.2f}"
            row.update(extra_stats(res, closes))
            row["Forced closes"] = str(res.forced_closes)
            rows[name], results[name] = row, res
        all_results[scen_name] = results
        print(f"\n=== {scen_name} ===")
        print(pd.DataFrame(rows).to_string())

    # How often does each signal say "on"? (fraction of days, per asset, strict scenario)
    strict = all_results[f"strict {MAX_HOLD_DAYS}-day limit"]
    sig_rows = {}
    for name in ["Trend only", "Momentum only", "AND", "OR"]:
        w = strict[name].weights
        sig_rows[name] = {a: f"{(w[a] > 0).mean():.0%}" for a in ASSETS}
    print("\nShare of days each asset is held (strict; includes forced days out):")
    print(pd.DataFrame(sig_rows).T.to_string())

    # Signal switches per year: how "jumpy" each raw signal is.
    flips = {}
    idx = dev.index[(dev.index >= start)]
    t_series = pd.DataFrame({d: trend_signal(closes.loc[:d].iloc[:-1]) for d in idx}).T
    m_series = pd.DataFrame({d: momentum_signal(closes.loc[:d].iloc[:-1]) for d in idx}).T
    years = len(idx) / 252
    flips["Trend"] = (t_series.diff().abs().sum() / years).round(1)
    flips["Momentum"] = (m_series.diff().abs().sum() / years).round(1)
    print("\nSignal switches per year, per asset (on->off or off->on):")
    print(pd.DataFrame(flips).T.to_string())

    # Sensitivity: are the chosen windows special, or do nearby windows work too? (dev data only)
    # Starts later (needs 253 closes for the 252-day window), so numbers differ slightly from the main table.
    grid_start = str(dev.index[252 + 1].date())
    print(f"\nSensitivity of AVERAGE combo (strict limit, from {grid_start}): Sharpe / Max DD")
    grid = {}
    for tw in [20, 50, 100, 200]:
        for mw in [63, 126, 252]:
            res = run_backtest(make_signal_strategy(COMBINERS["AVERAGE"], tw, mw), dev, start=grid_start, end=DEV_END)
            grid.setdefault(f"MA {tw}", {})[f"Mom {mw}"] = (
                f"{res.stats['Sharpe ratio']:.2f} / {res.stats['Max drawdown']:.0%}"
            )
    print(pd.DataFrame(grid).T.to_string())

    out = PROJECT_DIR / "research"
    plot_equity({k: strict[k] for k in ["Inv vol (daily)", "Trend only", "Momentum only", "AND", "OR", "AVERAGE"]},
                out / "signals.png", title=f"Signals vs inverse-vol baseline, {start} to {DEV_END} (strict 21-day limit)")


if __name__ == "__main__":
    main()
