"""
Final signal choice + volatility targeting (development data 2016-2021 only).

VERSIONS (fixed in advance, no tweaking afterwards)
  Single : AVERAGE of trend(50) and momentum(126).                      -> 0, 0.5, 1
  Multi  : AVERAGE of trend(50) and mean(momentum 63, 126, 252).        -> 0, 1/6, ..., 1
  Each asset's weight = inverse-vol weight x signal strength; the rest is cash.

DECISION RULE (written before running)
  Neighbourhood = MA in {30, 50, 100} x momentum lookback(s) shifted by -21 / 0 / +21 days
  (9 settings per version). The version with the better MEDIAN Sharpe AND the better WORST
  max drawdown across its neighbourhood wins. If those disagree, the smaller Sharpe range
  (max - min) wins.

VOLATILITY TARGETING (design fixed in advance)
  Predicted portfolio vol = sqrt(w' * Cov * w) * sqrt(252), Cov from the last 20 daily
  close-to-close returns (all before today). Scale every weight by T / predicted vol.
  Two variants:  "cut only" (scale capped at 1: only ever reduces exposure)
                 "up & down" (scale capped so total |weights| <= 1)
  Targets T = 10%, 15%, 20%.

All runs start on the same day: the first with 274 closes, enough for the longest
lookback in any neighbourhood (252 + 21 = 273 days).

Run from the project folder:
    .venv/bin/python research/final_signal.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "research"))
from backtest import ASSETS, format_stats, load_panel, plot_equity, run_backtest  # noqa: E402
from baselines import DEV_END, inverse_vol_daily, inverse_vol_weights  # noqa: E402
from robustness import stats_of, yearly_table  # noqa: E402
from signals import COMBINERS, make_signal_strategy, momentum_signal, trend_signal  # noqa: E402

OUT = PROJECT_DIR / "research"
VERSIONS = {"Single (MA 50 / 126)": (50, (126,)), "Multi (MA 50 / 63+126+252)": (50, (63, 126, 252))}
VT_WINDOW = 20
TARGETS = [0.10, 0.15, 0.20]


# ----------------------------------------------------------------------------
# Signal and strategy. `history` ends at yesterday's close.
# ----------------------------------------------------------------------------
def signal_strength(closes: pd.DataFrame, ma: int, lookbacks) -> pd.Series:
    """(trend + average of the momentum signals) / 2, per asset, between 0 and 1."""
    mom = sum(momentum_signal(closes, lb) for lb in lookbacks) / len(lookbacks)
    return (trend_signal(closes, ma) + mom) / 2


def vol_scale(w: pd.Series, closes: pd.DataFrame, target: float, allow_up: bool) -> pd.Series:
    gross = w.abs().sum()
    if gross < 1e-12:
        return w
    rets = closes.iloc[-(VT_WINDOW + 1):].pct_change().dropna()
    cov = rets.cov().to_numpy() * 252
    vol = float(np.sqrt(w.to_numpy() @ cov @ w.to_numpy()))
    if vol < 1e-12:
        return w
    cap = 1 / gross if allow_up else 1.0
    return w * min(target / vol, cap)


def make_strategy(ma: int, lookbacks, target: float | None = None, allow_up: bool = False):
    def strategy(history):
        closes = history.xs("Close", axis=1, level=1)[ASSETS]
        w = pd.Series(inverse_vol_weights(history)) * signal_strength(closes, ma, lookbacks)
        if target is not None:
            w = vol_scale(w, closes, target, allow_up)
        return w.to_dict()
    return strategy


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------
def run_checks(dev: pd.DataFrame, start: str) -> None:
    # 1. The new code reproduces the earlier AVERAGE strategy exactly.
    old = run_backtest(make_signal_strategy(COMBINERS["AVERAGE"], 50, 126), dev, start=start, end=DEV_END)
    new = run_backtest(make_strategy(50, (126,)), dev, start=start, end=DEV_END)
    assert (old.weights - new.weights).abs().max().max() < 1e-12, "Single version != earlier AVERAGE"

    # 2. Look-ahead: delete the second half of the data; earlier weights must not change.
    cut = dev.index[(dev.index.get_loc(pd.Timestamp(start)) + len(dev)) // 2]
    for strat in [make_strategy(50, (63, 126, 252)), make_strategy(50, (63, 126, 252), 0.10, True)]:
        full = run_backtest(strat, dev, start=start, end=DEV_END)
        short = run_backtest(strat, dev[dev.index <= cut], start=start, end=str(cut.date()))
        assert (full.weights.loc[short.weights.index] - short.weights).abs().max().max() < 1e-12

    # 3. Tamper: wreck all prices from the decision day on; that day's weights must not change.
    i = 700
    t = dev.copy()
    t.iloc[i:] *= 3
    strat = make_strategy(50, (63, 126, 252), 0.15, True)
    assert strat(dev.iloc[:i]) == strat(t.iloc[:i])
    print(f"Checks passed: Single == earlier AVERAGE; no look-ahead (cut at {cut.date()}); tamper test OK.")


# ----------------------------------------------------------------------------
def plot_scatter(points: pd.DataFrame, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e5e4df", "#fcfcfb"
    styles = {"No vol target": ("#52514e", "s"), "Cut only": ("#2a78d6", "o"), "Up & down": ("#eb6834", "D")}
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for group, (color, marker) in styles.items():
        sub = points[points["Group"] == group]
        ax.plot(-sub["Max DD"] * 100, sub["Ann. return"] * 100, linestyle="-" if len(sub) > 1 else "none",
                color=color, linewidth=1.5, marker=marker, markersize=9, markeredgecolor=SURFACE,
                markeredgewidth=2, label=group)
        for _, r in sub.iterrows():
            ax.annotate(f"{r['Label']}  (Sharpe {r['Sharpe']:.2f})", (-r["Max DD"] * 100, r["Ann. return"] * 100),
                        xytext=(8, -3), textcoords="offset points", fontsize=9, color=INK)
    ax.set_xlabel("Max drawdown (%, further right = worse)", color=INK2)
    ax.set_ylabel("Annualized return (%)", color=INK2)
    ax.set_title("Multi signal with volatility targeting: return vs max drawdown", loc="left", fontsize=12, color=INK)
    ax.legend(frameon=False, loc="lower right")
    ax.grid(color=GRID, linewidth=0.8)
    ax.margins(x=0.25, y=0.12)
    ax.tick_params(colors=INK2, labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    panel = load_panel()
    dev = panel[panel.index <= DEV_END]  # holdout never loaded
    start = str(dev.index[273 + 1].date())
    print(f"Common start date: {start}")
    run_checks(dev, start)

    def run(strat):
        return run_backtest(strat, dev, start=start, end=DEV_END)

    base = run(inverse_vol_daily)

    # 1. Head to head --------------------------------------------------------------
    results = {name: run(make_strategy(ma, lbs)) for name, (ma, lbs) in VERSIONS.items()}
    table = {"Inv vol baseline": format_stats(base.stats)}
    for name, res in results.items():
        table[name] = format_stats(res.stats)
        table[name]["Avg % invested"] = f"{res.weights.abs().sum(axis=1).mean():.0%}"
    print("\nHead to head\n", pd.DataFrame(table).to_string())

    years = pd.concat({n: yearly_table(r) for n, r in results.items()} | {"Baseline": yearly_table(base)}, axis=1)
    print("\nYear by year\n", years.round(3).to_string())

    def ex_covid(res):
        r = res.equity.pct_change().dropna()
        r = r[(r.index < "2020-02-01") | (r.index > "2020-04-30")]
        return stats_of((1 + r).cumprod())
    print("\nExcluding Feb-Apr 2020")
    for n, r in results.items():
        print(f"  {n}: {ex_covid(r)}")
    print(f"  Baseline: {ex_covid(base)}")

    # 2. Neighbourhood test (the decision rule) -------------------------------------
    neigh = {}
    for name, (_, lbs) in VERSIONS.items():
        rows = []
        for ma in (30, 50, 100):
            for shift in (-21, 0, 21):
                s = run(make_strategy(ma, tuple(lb + shift for lb in lbs))).stats
                rows.append({"MA": ma, "Shift": shift, "Sharpe": s["Sharpe ratio"], "Max DD": s["Max drawdown"],
                             "Ann. return": s["Annualized return"]})
        neigh[name] = pd.DataFrame(rows)
        print(f"\nNeighbourhood: {name}")
        print(neigh[name].pivot(index="MA", columns="Shift", values="Sharpe").round(2).to_string())
        print(neigh[name].pivot(index="MA", columns="Shift", values="Max DD").round(3).to_string())

    summary = pd.DataFrame({n: {"Median Sharpe": d["Sharpe"].median(), "Min Sharpe": d["Sharpe"].min(),
                                "Max Sharpe": d["Sharpe"].max(), "Sharpe range": d["Sharpe"].max() - d["Sharpe"].min(),
                                "Worst max DD": d["Max DD"].min(), "Median max DD": d["Max DD"].median()}
                            for n, d in neigh.items()}).T
    print("\nNeighbourhood summary\n", summary.round(3).to_string())

    s_name, m_name = list(VERSIONS)
    better_sharpe = m_name if summary.loc[m_name, "Median Sharpe"] > summary.loc[s_name, "Median Sharpe"] else s_name
    better_dd = m_name if summary.loc[m_name, "Worst max DD"] > summary.loc[s_name, "Worst max DD"] else s_name
    if better_sharpe == better_dd:
        winner, reason = better_sharpe, "better on both median Sharpe and worst drawdown"
    else:
        winner = min(VERSIONS, key=lambda n: summary.loc[n, "Sharpe range"])
        reason = "split decision; smaller Sharpe range wins"
    print(f"\nWINNER: {winner}  ({reason})")

    # 3. Volatility targeting on the winner -----------------------------------------
    ma, lbs = VERSIONS[winner]
    vt_res = {"No vol target": results[winner]}
    points = [{"Group": "No vol target", "Label": "none", "T": np.nan}]
    for allow_up, group in [(False, "Cut only"), (True, "Up & down")]:
        for T in TARGETS:
            key = f"{group}, T={T:.0%}"
            vt_res[key] = run(make_strategy(ma, lbs, T, allow_up))
            points.append({"Group": group, "Label": f"T={T:.0%}", "T": T})
    rows = {}
    for (key, res), p in zip(vt_res.items(), points):
        s = res.stats
        p.update({"Ann. return": s["Annualized return"], "Max DD": s["Max drawdown"], "Sharpe": s["Sharpe ratio"]})
        row = format_stats(s)
        row.pop("Trading days")
        row["Calmar"] = f"{s['Annualized return'] / -s['Max drawdown']:.2f}"
        row["Avg % invested"] = f"{res.weights.abs().sum(axis=1).mean():.0%}"
        row["COVID crash (Feb 19-Mar 23 2020)"] = (
            f"{res.equity.asof(pd.Timestamp('2020-03-23')) / res.equity.asof(pd.Timestamp('2020-02-19')) - 1:+.1%}")
        rows[key] = row
    print("\nVolatility targeting\n", pd.DataFrame(rows).to_string())

    vt_years = pd.concat({k: yearly_table(vt_res[k])[["Return", "Max DD"]] for k in
                          ["No vol target", "Cut only, T=10%", "Up & down, T=15%"]}, axis=1)
    print("\nVol-target year by year\n", vt_years.round(3).to_string())

    plot_scatter(pd.DataFrame(points), OUT / "final_vol_target.png")
    plot_equity({k: vt_res[k] for k in ["No vol target", "Cut only, T=10%", "Up & down, T=10%", "Up & down, T=15%",
                                        "Up & down, T=20%"]},
                OUT / "final_vol_target_equity.png", title=f"{winner} with vol targeting, {start} to {DEV_END}")


if __name__ == "__main__":
    main()
