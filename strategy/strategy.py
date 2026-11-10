"""
Final competition strategy: "Multi" trend + momentum, inverse-volatility weighted.

    from strategy.strategy import MultiStrategy
    strat = MultiStrategy()
    weights = strat(history)        # call once per trading day, before the open

`history` = everything known up to YESTERDAY's close (see "INPUT" below).
The result is a dict of target weights for Asset_A ... Asset_G, to trade at TODAY's open.

WHAT IT DOES (identical to research/final_signal.py, frozen)
-----------------------------------------------------------
For each asset A-F, using closing prices only:
    trend     = 1 if latest close > average of the last 50 closes, else 0
    momentum  = average of three 0/1 signals: return over the last 63 / 126 / 252
                trading days is > 0
    strength  = (trend + momentum) / 2                  -> between 0 and 1
    base      = inverse-volatility weights (1 / std of the last 60 daily returns),
                scaled so they add up to 1
    weight    = base x strength        (whatever is left over stays in cash)
Long only. The weights always add up to at most 1 (100% gross). Asset_G is always 0.

INPUT FORMATS ACCEPTED
----------------------
1. A dict {"Asset_A": DataFrame, ...}. Each DataFrame has either a DatetimeIndex or a
   "Date" column, and a close column named "Close" or "Close/Last". Text prices like
   "$28.43" are fine; the "$" and "," get stripped. Other columns (Open, High, Low,
   Volume) are allowed and ignored.
2. One DataFrame with two-level columns (asset, field), e.g. history["Asset_A"]["Close"].
   This is the layout the research backtester uses.
Extra assets (like Asset_G) are ignored. Rows can be in any order; they get sorted by date.

You can pass the FULL history every day, or only the NEW day(s) since the last call.
The strategy keeps its own copy of the recent closes either way. Calling it twice for
the same day returns the same answer without changing any state.

STATE KEPT BETWEEN CALLS
------------------------
- the last ~300 days of closes (enough for the 252-day lookback)
- how many trading days each position has been held (`holding_days`)
- the weights it returned last time
Use ONE MultiStrategy object for the whole competition (or call `reset()` to start over).
The holding-day count assumes your previous target weights were actually traded.

HISTORY NEEDED: 253 TRADING DAYS
--------------------------------
The 252-day momentum lookback needs 253 closes. If the FIRST call gets fewer, the
strategy prepends earlier days from the CSVs bundled in strategy/data/ (only dates
before the first date passed in, after checking the two series line up). See
"SHORT-HISTORY FALLBACK" below. `fallback_status` and `fallback_rows_used` report what it did.
"""

from __future__ import annotations

import functools
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# =============================================================================
# SETTINGS: HOLDING-PERIOD LIMIT  (waiting on the organizer to confirm the rule)
# =============================================================================
#
# HOLD_LIMIT_MODE = "exit_and_wait"
#     After a position has been held MAX_HOLD_DAYS trading days in a row, the strategy
#     returns 0 for that asset for COOLDOWN_DAYS day(s), so it is fully sold at the
#     next open, then allowed back in. This is what every research backtest used
#     (the "strict 21-day limit"), so the research numbers apply to this setting.
#
# HOLD_LIMIT_MODE = "off"
#     Never force an exit. Use this if the organizer says that either:
#       (a) rebalancing a position counts as opening a new one (this strategy trades
#           to fresh weights every day), or
#       (b) you may sell and rebuy at the same open, and their engine handles it.
#     A single target-weight dict can't express "sell and rebuy at the same open",
#     because the net trade is zero. Research results for this setting are the
#     "no hold limit" tables.
#
# MAX_HOLD_DAYS  - trading days a position may be held before it must be closed (~1 month).
# COOLDOWN_DAYS  - days to stay out after a forced exit ("exit_and_wait" only).
#                  1 = sell at one open, buy back at the next if still wanted.
HOLD_LIMIT_MODE = "exit_and_wait"
MAX_HOLD_DAYS = 21
COOLDOWN_DAYS = 1

# =============================================================================
# SETTINGS: SHORT-HISTORY FALLBACK
# =============================================================================
# The strategy needs MIN_HISTORY (253) trading days of closes before it can invest.
# If the FIRST call gets fewer than that, it prepends rows from the CSVs bundled in
# strategy/data/ (Asset_A-F, 2016-10-28 to 2023-10-06), so it can invest from day one.
#   - Only bundled dates EARLIER than the first date passed in are used. Passed-in rows
#     are never replaced, and bundled rows never overlap them.
#   - Safety checks: the bundled prices must line up with the passed-in prices. If the
#     dates overlap, the closes on shared dates must match within FALLBACK_PRICE_TOL.
#     If they don't overlap, the gap must be <= FALLBACK_MAX_GAP_DAYS calendar days and
#     no asset may jump more than FALLBACK_MAX_JUMP across it. If any check fails, the
#     fallback is skipped (with a warning) and the strategy holds cash until it has 253
#     days of real history, rather than trade on a stitched-together series.
FALLBACK_ENABLED = True
FALLBACK_DIR = None             # None = the data/ folder next to this file
FALLBACK_PRICE_TOL = 0.01       # 1%
FALLBACK_MAX_GAP_DAYS = 7
FALLBACK_MAX_JUMP = 0.30        # 30%

# =============================================================================
# STRATEGY PARAMETERS  (frozen; do not tune)
# =============================================================================
ASSETS = [f"Asset_{x}" for x in "ABCDEF"]
OUTPUT_ASSETS = ASSETS + ["Asset_G"]          # Asset_G duplicates Asset_B: always 0
TREND_WINDOW = 50
MOM_LOOKBACKS = (63, 126, 252)
VOL_WINDOW = 60
MIN_HISTORY = max(max(MOM_LOOKBACKS), TREND_WINDOW, VOL_WINDOW) + 1   # 253 closes
BUFFER_ROWS = MIN_HISTORY + 50

_VALID_MODES = ("exit_and_wait", "off")


# -----------------------------------------------------------------------------
# Input handling
# -----------------------------------------------------------------------------
def _to_float(s: pd.Series) -> pd.Series:
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        s = s.astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="raise").astype(float)


def _close_column(df: pd.DataFrame) -> pd.Series:
    for name in ("Close", "Close/Last"):
        if name in df.columns:
            return df[name]
    raise ValueError(f"No 'Close' or 'Close/Last' column; got {list(df.columns)}")


def extract_closes(history) -> pd.DataFrame:
    """Closing prices for Asset_A-F as a float table (rows = dates, oldest first)."""
    if isinstance(history, dict):
        cols = {}
        for a in ASSETS:
            if a not in history:
                raise ValueError(f"history is missing {a}")
            df = history[a]
            if "Date" in df.columns:
                df = df.set_index(pd.to_datetime(df["Date"]))
            cols[a] = _to_float(_close_column(df)).set_axis(pd.to_datetime(df.index))
        closes = pd.DataFrame(cols)
    elif isinstance(history, pd.DataFrame) and isinstance(history.columns, pd.MultiIndex):
        cols = {}
        for a in ASSETS:
            if a not in history.columns.get_level_values(0):
                raise ValueError(f"history is missing {a}")
            cols[a] = _to_float(_close_column(history[a]))
        closes = pd.DataFrame(cols)
        closes.index = pd.to_datetime(closes.index)
    else:
        raise TypeError("history must be a dict of per-asset DataFrames or a DataFrame with (asset, field) columns")
    closes = closes[~closes.index.duplicated(keep="first")].sort_index()
    return closes.dropna(how="any")   # use only days where all six assets have a close


# -----------------------------------------------------------------------------
# Signal (pure function of past closes)
# -----------------------------------------------------------------------------
def target_weights_from_closes(closes: pd.DataFrame) -> pd.Series:
    """Weights before the holding-period limit. `closes` must end at yesterday's close."""
    if len(closes) < MIN_HISTORY:
        return pd.Series(0.0, index=ASSETS)

    last = closes.iloc[-1]
    trend = (last > closes.iloc[-TREND_WINDOW:].mean()).astype(float)
    mom = sum(((last / closes.iloc[-(lb + 1)] - 1) > 0).astype(float) for lb in MOM_LOOKBACKS) / len(MOM_LOOKBACKS)
    strength = (trend + mom) / 2

    vol = closes.iloc[-(VOL_WINDOW + 1):].pct_change().dropna().std()
    inv = 1 / vol
    inv = inv.where(np.isfinite(inv) & (inv > 0), 0.0)   # safety: a flat or broken price series gets 0
    if inv.sum() <= 0:
        return pd.Series(0.0, index=ASSETS)
    base = inv / inv.sum()
    return base * strength


# -----------------------------------------------------------------------------
# The stateful strategy
# -----------------------------------------------------------------------------
class MultiStrategy:
    def __init__(self, hold_limit_mode: str = HOLD_LIMIT_MODE, max_hold_days: int = MAX_HOLD_DAYS,
                 cooldown_days: int = COOLDOWN_DAYS, use_fallback: bool = FALLBACK_ENABLED,
                 fallback_dir=FALLBACK_DIR):
        if hold_limit_mode not in _VALID_MODES:
            raise ValueError(f"hold_limit_mode must be one of {_VALID_MODES}")
        self.hold_limit_mode = hold_limit_mode
        self.max_hold_days = int(max_hold_days)
        self.cooldown_days = int(cooldown_days)
        self.use_fallback = bool(use_fallback)
        self.fallback_dir = Path(fallback_dir) if fallback_dir is not None else Path(__file__).resolve().parent / "data"
        self.reset()

    def reset(self) -> None:
        self._closes = pd.DataFrame(columns=ASSETS, dtype=float)
        self._last_date: pd.Timestamp | None = None
        self._prev = np.zeros(len(ASSETS))
        self._age = np.zeros(len(ASSETS), dtype=int)        # trading days each position has been held
        self._cooldown = np.zeros(len(ASSETS), dtype=int)   # days left to sit out after a forced exit
        self._last_output: dict | None = None
        self.fallback_rows_used = 0          # bundled rows prepended on the first call
        self.fallback_status = "not needed"  # plain-language note on what the fallback did

    def _prepend_bundled(self, new: pd.DataFrame) -> pd.DataFrame:
        """Put bundled closes for dates BEFORE new's first date in front of `new`, if they line up."""
        def skip(reason):
            self.fallback_status = f"skipped: {reason}"
            warnings.warn(f"Short-history fallback skipped ({reason}). Holding cash until "
                          f"{MIN_HISTORY} days of history are available.", stacklevel=3)
            return new
        try:
            bundled = _load_bundled(str(self.fallback_dir))
        except Exception as e:  # missing/corrupt bundled files must never crash the strategy
            return skip(f"could not read bundled data in {self.fallback_dir}: {e}")
        earlier = bundled[bundled.index < new.index[0]]
        if earlier.empty:
            self.fallback_status = "no bundled data earlier than the history passed in"
            return new
        shared = new.index.intersection(bundled.index)
        if len(shared):
            mismatch = float((bundled.loc[shared] / new.loc[shared] - 1).abs().max().max())
            if not mismatch <= FALLBACK_PRICE_TOL:
                return skip(f"bundled closes differ from passed-in closes by up to {mismatch:.1%} on shared dates")
        else:
            gap = (new.index[0] - earlier.index[-1]).days
            if gap > FALLBACK_MAX_GAP_DAYS:
                return skip(f"{gap}-day gap between bundled data (ends {earlier.index[-1].date()}) "
                            f"and history (starts {new.index[0].date()})")
            jump = float((new.iloc[0] / earlier.iloc[-1] - 1).abs().max())
            if not jump <= FALLBACK_MAX_JUMP:
                return skip(f"prices jump {jump:.0%} across the join; probably a different price series")
        self.fallback_rows_used = len(earlier)
        self.fallback_status = (f"prepended {len(earlier)} bundled days "
                                f"({earlier.index[0].date()} to {earlier.index[-1].date()})")
        return pd.concat([earlier, new])

    @property
    def holding_days(self) -> dict:
        return dict(zip(ASSETS, self._age.tolist()))

    def __call__(self, history) -> dict:
        new = extract_closes(history)
        if self._last_date is not None:
            if len(new) and new.index[-1] < self._last_date:
                raise ValueError(f"history ends {new.index[-1].date()}, before the last day already "
                                 f"processed ({self._last_date.date()}); call reset() to start over")
            new = new[new.index > self._last_date]
        if len(new) == 0:
            if self._last_output is None:
                raise ValueError("history contains no usable rows")
            return dict(self._last_output)     # same day again: same answer, no state change

        first_call = self._last_date is None
        if first_call and self.use_fallback and len(new) < MIN_HISTORY:
            new = self._prepend_bundled(new)

        n_new = 1 if first_call else len(new)   # trading days passed since last call
        self._closes = pd.concat([self._closes, new]).iloc[-BUFFER_ROWS:] if len(self._closes) else new.iloc[-BUFFER_ROWS:]
        self._last_date = self._closes.index[-1]

        target = target_weights_from_closes(self._closes).reindex(ASSETS).to_numpy(dtype=float)
        target = self._apply_hold_limit(target, n_new)

        gross = np.abs(target).sum()
        if gross > 1:                          # cannot happen by construction; belt and braces
            target = target / gross
        self._prev = target
        out = {a: float(w) for a, w in zip(ASSETS, target)}
        out["Asset_G"] = 0.0
        self._last_output = out
        return dict(out)

    def _apply_hold_limit(self, target: np.ndarray, n_new: int) -> np.ndarray:
        # Same counting as backtest.py: a position kept on the same side ages; a new one starts at 1.
        same_side = (np.sign(target) == np.sign(self._prev)) & (target != 0)
        age = np.where(same_side, self._age + n_new, np.where(target != 0, 1, 0))
        if self.hold_limit_mode == "exit_and_wait":
            sitting_out = self._cooldown > 0
            too_old = age > self.max_hold_days
            self._cooldown = np.where(sitting_out, self._cooldown - 1, 0)
            self._cooldown = np.where(too_old & ~sitting_out, self.cooldown_days - 1, self._cooldown)
            block = too_old | sitting_out
            target = np.where(block, 0.0, target)
            age = np.where(block, 0, age)
        self._age = age
        return target


# -----------------------------------------------------------------------------
# Convenience: one shared instance + a CSV loader for the raw competition files
# -----------------------------------------------------------------------------
_default = MultiStrategy()


def get_weights(history) -> dict:
    """Function form: uses one shared MultiStrategy that keeps state between calls."""
    return _default(history)


def reset() -> None:
    _default.reset()


def load_csv_folder(folder) -> dict:
    """Read Asset_A.csv ... Asset_F.csv (raw Nasdaq format) into the dict input format."""
    folder = Path(folder)
    return {a: pd.read_csv(folder / f"{a}.csv") for a in ASSETS}


@functools.lru_cache(maxsize=4)
def _load_bundled(folder: str) -> pd.DataFrame:
    return extract_closes(load_csv_folder(folder))


if __name__ == "__main__":
    import sys

    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data"
    data = load_csv_folder(folder)
    strat = MultiStrategy()
    w = strat(data)                     # all history at once; pass only new rows on later days
    print(f"Hold-limit mode: {strat.hold_limit_mode} (max {strat.max_hold_days} days)")
    print(f"Weights for the open after {strat._last_date.date()}:")
    for a, x in w.items():
        print(f"  {a}: {x:.4f}")
    print(f"  gross: {sum(abs(x) for x in w.values()):.4f}  (rest in cash)")
