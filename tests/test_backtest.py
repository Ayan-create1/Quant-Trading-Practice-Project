"""
Tests for backtest.py.

Run from the project folder:
    .venv/bin/python -m unittest -v tests/test_backtest.py

Part 1 proves there is no look-ahead bias.
Part 2 checks the accounting (trading at the open, costs, shorts, limits).
All tests use made-up price data so the answers are known exactly.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backtest import ASSETS, COST_RATE, run_backtest  # noqa: E402

C = COST_RATE

# Entering a position of size |w| starting from cash costs C * |w| of the trade.
# Costs come out of equity, and the backtester sizes trades so that AFTER costs
# the weight is exactly w. So going from all-cash to weight 1 leaves equity
# E = 1 - C * E, i.e. E = 1 / (1 + C) (about 0.99950, the same as 1 - C to 7 decimals).
ENTRY_FACTOR = 1 / (1 + C)


# ----------------------------------------------------------------------------
# Fake data
# ----------------------------------------------------------------------------
def random_panel(n_days=300, seed=0) -> pd.DataFrame:
    """Random-walk prices for all six assets, in the same layout as the real data."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = {}
    for a in ASSETS:
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n_days)))
        open_ = close * np.exp(rng.normal(0, 0.01, n_days))
        high = np.maximum(open_, close) * 1.01
        low = np.minimum(open_, close) * 0.99
        vol = rng.integers(1_000, 10_000, n_days).astype(float)
        frames[a] = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=dates)
    return pd.concat(frames, axis=1)


def simple_panel(opens: dict, closes: dict, n: int | None = None) -> pd.DataFrame:
    """Hand-written prices. Assets not given stay flat at 100."""
    if n is None:
        n = len(next(iter(opens.values())))
    dates = pd.bdate_range("2020-01-01", periods=n)
    frames = {}
    for a in ASSETS:
        o = np.array(opens.get(a, [100.0] * n), dtype=float)
        c = np.array(closes.get(a, [100.0] * n), dtype=float)
        frames[a] = pd.DataFrame({"Open": o, "High": np.maximum(o, c), "Low": np.minimum(o, c),
                                  "Close": c, "Volume": 1000.0}, index=dates)
    return pd.concat(frames, axis=1)


def scramble_from(panel: pd.DataFrame, k: int, seed=99) -> pd.DataFrame:
    """Copy of `panel` where every value on day k and later is replaced by random junk."""
    out = panel.copy()
    rng = np.random.default_rng(seed)
    out.iloc[k:] = rng.uniform(1, 1000, size=out.iloc[k:].shape)
    return out


def momentum_strategy(history: pd.DataFrame) -> dict:
    """A strategy that really depends on the data: it reads every column of the
    latest rows, so any leak of future data would change its answers."""
    if len(history) < 6:
        return {}
    w = {}
    for a in ASSETS:
        h = history[a]
        signal = h["Close"].iloc[-1] / h["Close"].iloc[-6] - 1
        signal += 0.001 * (h["High"].iloc[-1] - h["Low"].iloc[-1]) / h["Open"].iloc[-1]
        signal += 1e-9 * h["Volume"].iloc[-1]
        w[a] = np.tanh(10 * signal) / len(ASSETS)
    return w


# ----------------------------------------------------------------------------
# Part 1: no look-ahead bias
# ----------------------------------------------------------------------------
class TestNoLookAhead(unittest.TestCase):

    def test_strategy_only_sees_data_up_to_yesterday(self):
        """Each time the strategy is called for day t, the newest row it gets is day t-1."""
        panel = random_panel()
        last_seen = []

        def spy(history):
            last_seen.append(history.index[-1])
            return {"Asset_A": 0.5}

        res = run_backtest(spy, panel, max_hold_days=None)
        trade_days = res.weights.index
        self.assertEqual(len(last_seen), len(trade_days))
        for seen, trade_day in zip(last_seen, trade_days):
            yesterday = panel.index[panel.index.get_loc(trade_day) - 1]
            self.assertEqual(seen, yesterday)
            self.assertLess(seen, trade_day)

    def test_changing_the_future_does_not_change_the_past(self):
        """The key test. Replace everything from day k onward with junk. Decisions
        for every day up to and including k (which only use data through k-1) and
        equity up to day k-1's close must be exactly identical."""
        panel = random_panel()
        for k in [10, 57, 150, 299]:
            with self.subTest(k=k):
                clean = run_backtest(momentum_strategy, panel, liquidate_at_end=False)
                junk = run_backtest(momentum_strategy, scramble_from(panel, k), liquidate_at_end=False)
                day_k = panel.index[k]
                day_before = panel.index[k - 1]
                pd.testing.assert_frame_equal(clean.weights.loc[:day_k], junk.weights.loc[:day_k])
                pd.testing.assert_series_equal(clean.equity.loc[:day_before], junk.equity.loc[:day_before])
                # Sanity: the junk really did change something from day k on.
                self.assertNotAlmostEqual(clean.equity.loc[day_k], junk.equity.loc[day_k])

    def test_the_future_test_catches_a_cheater(self):
        """Proves the test above has teeth: a strategy that secretly peeks at
        today's close gives different decisions when the future is scrambled."""
        panel = random_panel()
        k = 150

        def make_cheater(full_data):
            def cheater(history):
                today = full_data.index[len(history)]  # the day being traded
                w = {}
                for a in ASSETS:
                    went_up = full_data[a]["Close"].loc[today] > full_data[a]["Open"].loc[today]
                    w[a] = (1 if went_up else -1) / len(ASSETS)
                return w
            return cheater

        scrambled = scramble_from(panel, k)
        clean = run_backtest(make_cheater(panel), panel, max_hold_days=None)
        junk = run_backtest(make_cheater(scrambled), scrambled, max_hold_days=None)
        day_k = panel.index[k]
        self.assertFalse(clean.weights.loc[:day_k].equals(junk.weights.loc[:day_k]),
                         "A cheating strategy should be caught by the scramble test")
        # And cheating makes absurd profits, which is the warning sign in real life.
        self.assertGreater(clean.stats["Sharpe ratio"], 5)

    def test_strategy_cannot_corrupt_the_data(self):
        """If a strategy scribbles on the history it was given, the backtest must not care."""
        panel = random_panel()
        normal = run_backtest(momentum_strategy, panel)

        def vandal(history):
            w = momentum_strategy(history)
            history.iloc[:, :] = 0.0  # try to wreck the data
            return w

        vandalized = run_backtest(vandal, panel)
        pd.testing.assert_series_equal(normal.equity, vandalized.equity)

    def test_unsorted_input_is_sorted_first(self):
        """If the data arrives newest-first, the backtester sorts it before anything else."""
        panel = random_panel()
        a = run_backtest(momentum_strategy, panel)
        b = run_backtest(momentum_strategy, panel.iloc[::-1])
        pd.testing.assert_series_equal(a.equity, b.equity)


# ----------------------------------------------------------------------------
# Part 2: accounting
# ----------------------------------------------------------------------------
class TestAccounting(unittest.TestCase):

    def test_buy_and_hold_math_is_exact(self):
        """100% in Asset_A from day 1: pay 5bp to enter, ride the price, pay 5bp to exit."""
        opens = {"Asset_A": [100, 110, 120, 90, 100]}
        closes = {"Asset_A": [105, 115, 100, 95, 130]}
        res = run_backtest(lambda h: {"Asset_A": 1.0}, simple_panel(opens, closes), max_hold_days=None)
        # Enter at day 1's open (110), finish at day 4's close (130), then pay exit cost.
        expected = ENTRY_FACTOR * (130 / 110) * (1 - C)
        self.assertAlmostEqual(res.equity.iloc[-1], expected, places=12)

    def test_trades_happen_at_the_open(self):
        """Price gaps up overnight before we can buy: we must NOT get that gain."""
        opens = {"Asset_A": [100, 150, 150]}   # jumps from 100 to 150 overnight
        closes = {"Asset_A": [100, 150, 150]}
        res = run_backtest(lambda h: {"Asset_A": 1.0}, simple_panel(opens, closes),
                           max_hold_days=None, liquidate_at_end=False)
        self.assertAlmostEqual(res.equity.iloc[-1], ENTRY_FACTOR, places=12)  # only the entry cost

    def test_positions_held_overnight_earn_the_gap(self):
        """Once we own it, the overnight move from close to next open counts."""
        opens = {"Asset_A": [100, 100, 120]}
        closes = {"Asset_A": [100, 100, 120]}
        res = run_backtest(lambda h: {"Asset_A": 1.0}, simple_panel(opens, closes),
                           max_hold_days=None, liquidate_at_end=False)
        self.assertAlmostEqual(res.equity.iloc[-1], ENTRY_FACTOR * 1.2, places=12)

    def test_costs_only_on_changes(self):
        """Holding the same single position costs nothing after the entry day."""
        n = 30
        prices = list(np.linspace(100, 130, n))
        res = run_backtest(lambda h: {"Asset_A": 1.0}, simple_panel({"Asset_A": prices}, {"Asset_A": prices}),
                           max_hold_days=None, liquidate_at_end=False)
        self.assertAlmostEqual(res.costs.iloc[0], C * ENTRY_FACTOR, places=12)
        self.assertTrue(np.allclose(res.costs.iloc[1:], 0.0, atol=1e-15))
        self.assertAlmostEqual(res.turnover.sum(), 1.0, places=3)

    def test_cost_scales_with_size_of_change(self):
        """Going from 0 to 0.3 and then to -0.2 trades 0.3 and then 0.5 of equity."""
        schedule = iter([0.3, -0.2])
        panel = simple_panel({}, {}, n=3)  # all prices flat at 100
        res = run_backtest(lambda h: {"Asset_A": next(schedule)}, panel,
                           max_hold_days=None, liquidate_at_end=False)
        self.assertAlmostEqual(res.turnover.iloc[0], 0.3, places=3)
        self.assertAlmostEqual(res.turnover.iloc[1], 0.5, places=3)
        # Day 1: E1 = 1 - C*0.3*E1.   Day 2: E2 = E1 - C*(0.3*E1 + 0.2*E2).
        e1 = 1 / (1 + 0.3 * C)
        e2 = e1 * (1 - 0.3 * C) / (1 + 0.2 * C)
        self.assertAlmostEqual(res.equity.iloc[-1], e2, places=12)

    def test_short_profits_when_price_falls(self):
        opens = {"Asset_A": [100, 100]}
        closes = {"Asset_A": [100, 90]}
        res = run_backtest(lambda h: {"Asset_A": -1.0}, simple_panel(opens, closes),
                           max_hold_days=None, liquidate_at_end=False)
        # Short at 100, price falls 10% by the close: we gain 10% of the position.
        self.assertAlmostEqual(res.equity.iloc[-1], ENTRY_FACTOR * 1.1, places=12)

    def test_returning_none_means_hold(self):
        """None = keep positions, no trade. With two assets that move differently,
        re-sending the same targets would cost money (weights drift); None should not."""
        rng_prices = random_panel(40)
        calls = iter(range(1000))

        def enter_then_hold(history):
            return {"Asset_A": 0.5, "Asset_B": 0.5} if next(calls) == 0 else None

        res = run_backtest(enter_then_hold, rng_prices, max_hold_days=None, liquidate_at_end=False)
        self.assertTrue(np.allclose(res.costs.iloc[1:], 0.0, atol=1e-15))

    def test_gross_exposure_is_capped_at_one(self):
        res = run_backtest(lambda h: {"Asset_A": 1.0, "Asset_B": -1.0}, random_panel(50))
        self.assertTrue(np.all(res.weights.abs().sum(axis=1) <= 1 + 1e-12))
        self.assertAlmostEqual(res.weights["Asset_A"].iloc[0], 0.5)
        self.assertAlmostEqual(res.weights["Asset_B"].iloc[0], -0.5)
        self.assertGreater(res.leverage_scaled_days, 0)

    def test_holding_limit_forces_a_close(self):
        res = run_backtest(lambda h: {"Asset_A": 0.5}, random_panel(60), max_hold_days=21)
        self.assertLessEqual(res.holding_days["Asset_A"].max(), 21)
        # Held days 1-21, forced flat on day 22, re-entered on day 23.
        self.assertEqual(res.weights["Asset_A"].iloc[21], 0.0)
        self.assertEqual(res.weights["Asset_A"].iloc[22], 0.5)
        self.assertGreater(res.forced_closes, 0)

    def test_flipping_direction_resets_the_holding_clock(self):
        flip = iter([0.5 if (i // 15) % 2 == 0 else -0.5 for i in range(100)])
        res = run_backtest(lambda h: {"Asset_A": next(flip)}, random_panel(60), max_hold_days=21)
        self.assertEqual(res.forced_closes, 0)

    def test_bad_weights_are_rejected(self):
        panel = random_panel(20)
        with self.assertRaises(ValueError):
            run_backtest(lambda h: {"Asset_G": 0.5}, panel)  # Asset_G is not allowed
        with self.assertRaises(ValueError):
            run_backtest(lambda h: {"Asset_A": float("nan")}, panel)
        with self.assertRaises(TypeError):
            run_backtest(lambda h: [0.5, 0.5], panel)

    def test_strategy_can_receive_portfolio_info(self):
        seen = []

        def strat(history, portfolio):
            seen.append(portfolio["holding_days"]["Asset_A"])
            return {"Asset_A": 0.5}

        run_backtest(strat, random_panel(10), max_hold_days=None)
        self.assertEqual(seen[:4], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
