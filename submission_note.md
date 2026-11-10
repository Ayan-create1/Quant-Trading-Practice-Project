# Submission note

Hi, here's my submission: the `strategy/` folder (including `strategy/data/`) and `writeup.md`.

**1. History requirement: 253 trading days.** The strategy needs about one
year of daily closes before it can invest. If you give it less, it automatically fills
in earlier days from the bundled CSVs in `strategy/data/` (2016-10-28 to
2023-10-06), but only if they join up with your data: overlapping prices must match
within 1%, or the gap must be 7 days or less. Otherwise it holds cash until it has
253 days. **Please keep `strategy/data/` next to `strategy.py`.** If the competition
data starts well after October 2023, please provide at least 253 days of history.

**2. Holding-period rule: please confirm which applies.** The setting is at the
top of `strategy/strategy.py`:
- `HOLD_LIMIT_MODE = "exit_and_wait"` (current default): a position held 21
  trading days is fully closed for 1 day, then may be reopened.
- `HOLD_LIMIT_MODE = "off"`: no forced exits. This is the right choice if
  rebalancing counts as a new position, or if selling and rebuying at the same
  open is allowed.

If the rule is "close and stay out for N days", set `COOLDOWN_DAYS = N`. If you let
me know the exact rule, I'll set it, or you can change that one line.

**How to call it:** `strat = MultiStrategy()` once, then `strat(history)` before
each open, with data up to the previous close. It returns weights for Asset_A–G
(Asset_G is always 0). Details are in `strategy/README.md`.

Thanks!
Ayan
