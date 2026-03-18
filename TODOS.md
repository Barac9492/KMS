# KMS — TODOS

## P2: Strategy Auto-Tuning
**What:** After accumulating 50+ trades in the signal accuracy log, automatically re-run grid search with live data to find optimal parameters. Compare live-optimal vs backtest-optimal params to detect overfitting.
**Why:** The 52% win rate from backtesting might be improvable with real-world signal data. Also validates whether backtest parameters generalize.
**Effort:** M (human: ~1 week / CC: ~20 min)
**Priority:** P3
**Depends on:** signal_accuracy.csv having 50+ trades (est. ~3-6 months of live running with cron enabled)
**Blocked by:** Signal accuracy logger must be live and accumulating data first.
**How to start:** Add a `--retune` flag to backtest.py that reads from signal_accuracy.csv instead of (or in addition to) historical backtest data.

~~## P1: Deprecated Pandas API Fix~~ — **RESOLVED** (bundled into eng review implementation plan, 2026-03-18)
