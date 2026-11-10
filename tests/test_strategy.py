"""
Tests for the final deliverable, strategy/strategy.py.

Run from the project folder (takes about a minute):
    .venv/bin/python -m unittest -v tests/test_strategy.py

The key test: run the packaged strategy through the research backtester and check
that every day's weights and the equity curve match the frozen research version
(research/final_signal.py, Multi, no vol target). The match is checked both with
the strict 21-day limit and with the limit off.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from backtest import ASSETS, load_panel, run_backtest  # noqa: E402
from final_signal import make_strategy  # noqa: E402
from strategy.strategy import BUFFER_ROWS, MIN_HISTORY, OUTPUT_ASSETS, MultiStrategy, load_csv_folder  # noqa: E402

RESEARCH_MULTI = make_strategy(50, (63, 126, 252))   # the frozen research version
START = "2017-11-30"                                 # same start as final_signal.py
TOL = 1e-12


def packaged(**kwargs):
    """Wrap a fresh MultiStrategy for the backtester (which only accepts Asset_A-F keys)."""
    strat = MultiStrategy(**kwargs)

    def fn(history):
        w = strat(history)
        assert w.pop("Asset_G") == 0.0
        return w
    fn.strat = strat
    return fn


class TestMatchesResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()
        cls.end = str(cls.panel.index[-1].date())

    def _compare(self, max_hold_days, mode):
        ours_fn = packaged(hold_limit_mode=mode)
        research = run_backtest(RESEARCH_MULTI, self.panel, start=START, end=self.end, max_hold_days=max_hold_days)
        ours = run_backtest(ours_fn, self.panel, start=START, end=self.end, max_hold_days=max_hold_days)
        self.assertLess((research.weights - ours.weights).abs().max().max(), TOL)
        self.assertLess((research.equity - ours.equity).abs().max(), TOL)
        # Our strategy enforces the limit itself, so the backtester never has to.
        self.assertEqual(ours.forced_closes, 0)
        return research, ours

    def test_strict_21_day_limit_matches_research_exactly(self):
        research, ours = self._compare(max_hold_days=21, mode="exit_and_wait")
        self.assertGreater(research.forced_closes, 0)   # the research run did rely on the backtester's limit
        # Headline numbers from the research write-ups:
        dev = run_backtest(packaged(), self.panel[self.panel.index <= "2021-12-31"], start=START, end="2021-12-31")
        self.assertAlmostEqual(dev.stats["Sharpe ratio"], 1.37, delta=0.005)        # final_signal_explained.md
        self.assertAlmostEqual(dev.stats["Max drawdown"], -0.121, delta=0.0005)
        hold = run_backtest(packaged(), self.panel, start="2022-01-01", end=self.end)
        self.assertAlmostEqual(hold.stats["Total return"], -0.062, delta=0.0005)    # holdout.md
        self.assertAlmostEqual(hold.stats["Max drawdown"], -0.174, delta=0.0005)

    def test_limit_off_matches_research_without_limit(self):
        self._compare(max_hold_days=None, mode="off")


class TestDeliverableBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()
        cls.dates = cls.panel.index

    def test_one_day_at_a_time_equals_full_history(self):
        """Feeding only the newest row each day gives the same weights as feeding everything."""
        full, inc = MultiStrategy(), MultiStrategy()
        first = MIN_HISTORY + 5
        for i in range(first, first + 400):
            w_full = full(self.panel.iloc[:i])
            w_inc = inc(self.panel.iloc[:i] if i == first else self.panel.iloc[i - 1:i])
            for a in OUTPUT_ASSETS:
                self.assertAlmostEqual(w_full[a], w_inc[a], delta=TOL)
        self.assertEqual(full.holding_days, inc.holding_days)

    def test_raw_csv_format_gives_same_answer(self):
        """Raw files ('$' prices, 'Close/Last', newest-first rows) work and match the cleaned panel."""
        raw = load_csv_folder(ROOT / "data")
        a, b = MultiStrategy(), MultiStrategy()
        wa = a(raw)
        wb = b(self.panel)
        for k in OUTPUT_ASSETS:
            self.assertAlmostEqual(wa[k], wb[k], delta=TOL)

    def test_outputs_are_valid_every_day(self):
        strat = MultiStrategy()
        for i in range(MIN_HISTORY + 1, len(self.panel), 3):
            w = strat(self.panel.iloc[:i])
            self.assertEqual(list(w), OUTPUT_ASSETS)
            self.assertEqual(w["Asset_G"], 0.0)
            vals = np.array(list(w.values()))
            self.assertTrue(np.all(np.isfinite(vals)))
            self.assertTrue(np.all(vals >= 0))                      # long only
            self.assertLessEqual(np.abs(vals).sum(), 1 + 1e-12)     # never above 100% gross

    def test_same_day_twice_does_not_change_state(self):
        strat = MultiStrategy()
        h = self.panel.iloc[:MIN_HISTORY + 30]
        w1 = strat(h)
        ages = strat.holding_days
        w2 = strat(h)
        self.assertEqual(w1, w2)
        self.assertEqual(ages, strat.holding_days)

    def test_going_back_in_time_raises(self):
        strat = MultiStrategy()
        strat(self.panel.iloc[:MIN_HISTORY + 30])
        with self.assertRaises(ValueError):
            strat(self.panel.iloc[:MIN_HISTORY + 10])

    def test_warmup_holds_cash_when_fallback_off(self):
        w = MultiStrategy(use_fallback=False)(self.panel.iloc[600:600 + MIN_HISTORY - 1])
        self.assertTrue(all(v == 0.0 for v in w.values()))

    def test_no_lookahead_future_rows_are_never_seen(self):
        """Changing prices from day i onward can't change the weights chosen for day i."""
        i = 900
        tampered = self.panel.copy()
        tampered.iloc[i:] *= 3
        self.assertEqual(MultiStrategy()(self.panel.iloc[:i]), MultiStrategy()(tampered.iloc[:i]))

    def test_hold_limit_never_exceeded_and_sits_out(self):
        for cooldown in (1, 2):
            strat = MultiStrategy(hold_limit_mode="exit_and_wait", max_hold_days=21, cooldown_days=cooldown)
            held = np.zeros(6, dtype=int)
            saw_exit = False
            for i in range(MIN_HISTORY + 1, MIN_HISTORY + 600):
                w = np.array([strat(self.panel.iloc[:i])[a] for a in ASSETS])
                was_held_21 = held == 21
                held = np.where(w > 0, held + 1, 0)
                self.assertTrue(np.all(held <= 21))
                # After 21 days held, the asset must be flat for `cooldown` days.
                if was_held_21.any():
                    saw_exit = True
                    self.assertTrue(np.all(w[was_held_21] == 0))
                self.assertEqual(strat.holding_days, dict(zip(ASSETS, held.tolist())))
            self.assertTrue(saw_exit)

    def test_cooldown_two_days(self):
        strat = MultiStrategy(cooldown_days=2)
        ws = [np.array([strat(self.panel.iloc[:i])[a] for a in ASSETS]) for i in range(MIN_HISTORY + 1, MIN_HISTORY + 400)]
        ws = np.array(ws)
        for j in range(6):
            col = ws[:, j] > 0
            run = 0
            for t in range(len(col)):
                if col[t]:
                    run += 1
                else:
                    if run == 21:       # forced exit: the next day must also be flat
                        self.assertFalse(col[t + 1] if t + 1 < len(col) else False)
                    run = 0

    def test_off_mode_never_forces_exit(self):
        strat = MultiStrategy(hold_limit_mode="off")
        for i in range(MIN_HISTORY + 1, MIN_HISTORY + 300):
            strat(self.panel.iloc[:i])
        self.assertGreater(max(strat.holding_days.values()), 21)


class TestShortHistoryFallback(unittest.TestCase):
    """If the first call has < 253 days, earlier days come from the bundled CSVs in strategy/data/."""

    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()
        cls.S = 1000   # pretend the competition's history starts on this row (2020-10-20)

    def _cash(self, w):
        return all(v == 0.0 for v in w.values())

    def test_bundled_data_is_the_project_data(self):
        for a in ASSETS:
            self.assertEqual((ROOT / "strategy" / "data" / f"{a}.csv").read_bytes(),
                             (ROOT / "data" / f"{a}.csv").read_bytes())

    def test_short_history_invests_and_matches_full_history(self):
        """10 days of history + fallback gives exactly the weights you'd get from the full history,
        on the first day and on every following day fed one row at a time."""
        S = self.S
        short, full = MultiStrategy(), MultiStrategy(use_fallback=False)
        for i in range(S + 10, S + 310):
            w_short = short(self.panel.iloc[S:i] if i == S + 10 else self.panel.iloc[i - 1:i])
            w_full = full(self.panel.iloc[:i])
            for a in OUTPUT_ASSETS:
                self.assertAlmostEqual(w_short[a], w_full[a], delta=TOL)
            if i == S + 10:
                self.assertGreater(sum(w_short.values()), 0)     # invested from day one
        self.assertEqual(short.fallback_rows_used, S)            # every bundled day before the first passed date
        self.assertEqual(short.holding_days, full.holding_days)

    def test_only_earlier_dates_are_prepended_never_replaced(self):
        S = self.S
        passed = self.panel.iloc[S:S + 10].copy()
        passed.loc[:, (slice(None), "Close")] *= 1.005          # slightly different prices (within the 1% check)
        strat = MultiStrategy()
        strat(passed)
        buf = strat._closes
        first = passed.index[0]
        self.assertFalse(buf.index.duplicated().any())
        self.assertEqual(strat.fallback_rows_used, S)
        self.assertEqual(len(buf), min(S + 10, BUFFER_ROWS))     # the strategy keeps only its last ~300 days
        # The passed-in rows are kept exactly as given...
        passed_close = pd.DataFrame({a: passed[a]["Close"] for a in ASSETS})
        pd.testing.assert_frame_equal(buf.loc[buf.index >= first], passed_close, check_freq=False, check_names=False)
        # ...and every prepended row is strictly earlier and equals the bundled data.
        prepended = buf.loc[buf.index < first]
        self.assertEqual(len(prepended), len(buf) - 10)
        orig = pd.DataFrame({a: self.panel[a]["Close"] for a in ASSETS}).loc[prepended.index]
        pd.testing.assert_frame_equal(prepended, orig, check_freq=False, check_names=False)

    def test_not_used_when_history_is_long_enough(self):
        strat = MultiStrategy()
        strat(self.panel.iloc[100:100 + MIN_HISTORY])
        self.assertEqual(strat.fallback_rows_used, 0)
        self.assertEqual(strat.fallback_status, "not needed")

    def test_only_on_first_call(self):
        """Later short updates (one row per day) never trigger another prepend."""
        strat = MultiStrategy()
        strat(self.panel.iloc[:MIN_HISTORY + 5])
        strat(self.panel.iloc[MIN_HISTORY + 5:MIN_HISTORY + 6])
        self.assertEqual(strat.fallback_rows_used, 0)

    def test_no_earlier_bundled_data_holds_cash(self):
        strat = MultiStrategy()
        self.assertTrue(self._cash(strat(self.panel.iloc[:100])))   # starts on the first bundled date
        self.assertIn("no bundled data earlier", strat.fallback_status)

    def test_skipped_if_prices_disagree_on_shared_dates(self):
        passed = self.panel.iloc[self.S:self.S + 10] * 1.5            # same dates, different price scale
        strat = MultiStrategy()
        with self.assertWarns(UserWarning):
            w = strat(passed)
        self.assertTrue(self._cash(w))
        self.assertEqual(strat.fallback_rows_used, 0)
        self.assertTrue(strat.fallback_status.startswith("skipped"))

    def _after_bundled_end(self, scale, start="2023-10-09"):
        """10 days starting after the bundled data ends, prices = last bundled close x scale."""
        last = pd.DataFrame({a: self.panel[a]["Close"] for a in ASSETS}).iloc[-1]
        dates = pd.bdate_range(start, periods=10)
        return {a: pd.DataFrame({"Date": dates, "Close/Last": [f"${last[a] * scale:.4f}"] * 10}) for a in ASSETS}

    def test_joins_onto_bundled_data_after_it_ends(self):
        strat = MultiStrategy()
        strat(self._after_bundled_end(1.01))
        self.assertEqual(strat.fallback_rows_used, len(self.panel))  # all bundled rows, all earlier
        self.assertTrue(strat.fallback_status.startswith("prepended"))

    def test_skipped_if_gap_too_long(self):
        strat = MultiStrategy()
        with self.assertWarns(UserWarning):
            w = strat(self._after_bundled_end(1.0, start="2026-01-05"))
        self.assertTrue(self._cash(w))
        self.assertIn("gap", strat.fallback_status)

    def test_skipped_if_price_jumps_across_join(self):
        strat = MultiStrategy()
        with self.assertWarns(UserWarning):
            w = strat(self._after_bundled_end(2.0))
        self.assertTrue(self._cash(w))
        self.assertIn("jump", strat.fallback_status)

    def test_missing_bundled_folder_does_not_crash(self):
        strat = MultiStrategy(fallback_dir=ROOT / "no_such_folder")
        with self.assertWarns(UserWarning):
            w = strat(self.panel.iloc[self.S:self.S + 10])
        self.assertTrue(self._cash(w))


if __name__ == "__main__":
    unittest.main()
