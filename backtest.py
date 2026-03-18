"""Backtest entry point — run volume-only or combined backtest."""

import sys
import pandas as pd

from config import (
    ETF_UNIVERSE, INITIAL_CAPITAL, BACKTEST_START, BACKTEST_END,
    RISK_FREE_RATE, BENCHMARK_CODE, DEFAULT_PARAMS,
)
from data.fetch_etf import fetch_all_etfs, fetch_etf_data, add_indicators
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics, format_metrics
from kms_logger import logger


def run_single_backtest(params: dict | None = None, verbose: bool = True):
    """Run a single backtest with given parameters."""
    params = {**DEFAULT_PARAMS, **(params or {})}
    ma_period = params.get("ma_period", 20)

    if verbose:
        logger.info("Fetching ETF data...")
    etf_data = fetch_all_etfs(ETF_UNIVERSE, BACKTEST_START, BACKTEST_END, ma_period)

    if not etf_data:
        logger.error("No ETF data fetched. Check your internet connection.")
        sys.exit(1)

    if verbose:
        logger.info("  Loaded %d ETFs", len(etf_data))

    # Fetch benchmark
    bm_df = fetch_etf_data(BENCHMARK_CODE, BACKTEST_START, BACKTEST_END)
    benchmark_values = None
    if not bm_df.empty:
        benchmark_values = bm_df["Close"]

    # Try to load search signal if trend data available
    search_signal_func = None
    trend_data = {}
    try:
        from signals.search_signal import compute_search_signal
        from data.fetch_trend import load_all_trend_cache
        trend_data = load_all_trend_cache()
        if trend_data:
            search_signal_func = compute_search_signal
            if verbose:
                logger.info("  Loaded trend data for %d themes", len(trend_data))
    except (ImportError, Exception) as e:
        if verbose:
            logger.info("  No trend data available — running volume-only backtest (%s)", e)

    engine = BacktestEngine(
        etf_data=etf_data,
        params=params,
        initial_capital=INITIAL_CAPITAL,
        search_signal_func=search_signal_func,
        trend_data=trend_data,
    )

    if verbose:
        logger.info("Running backtest %s → %s...", BACKTEST_START, BACKTEST_END)
    pv, trades = engine.run(BACKTEST_START, BACKTEST_END)

    metrics = compute_metrics(pv, trades, RISK_FREE_RATE, benchmark_values)

    if verbose:
        logger.info(format_metrics(metrics))
        logger.info("  Total trades: %d", len(trades))
        if trades:
            logger.info("  Last 10 trades:")
            for t in trades[-10:]:
                logger.info("    %s → %s  %s  %+.1f%%  (%s)",
                            t["entry_date"], t["exit_date"],
                            t["etf_name"], t["return_pct"] * 100, t["exit_reason"])

    return pv, trades, metrics


def grid_search(verbose: bool = True):
    """Run parameter grid search with train/test split."""
    from itertools import product

    PARAM_GRID = {
        "search_threshold": [1.5, 1.8, 2.0, 2.5],
        "vol_threshold": [1.3, 1.5, 2.0],
        "stop_loss": [0.05, 0.07, 0.10],
        "max_hold_weeks": [2, 4, 6],
        "search_lookback_weeks": [4, 6, 8],
    }

    # Preload ETF data once
    ma_period = DEFAULT_PARAMS["ma_period"]
    logger.info("Fetching ETF data for grid search...")
    etf_data = fetch_all_etfs(ETF_UNIVERSE, BACKTEST_START, BACKTEST_END, ma_period)
    bm_df = fetch_etf_data(BENCHMARK_CODE, BACKTEST_START, BACKTEST_END)
    benchmark_values = bm_df["Close"] if not bm_df.empty else None

    # Try to load trend data
    search_signal_func = None
    trend_data = {}
    try:
        from signals.search_signal import compute_search_signal
        from data.fetch_trend import load_all_trend_cache
        trend_data = load_all_trend_cache()
        if trend_data:
            search_signal_func = compute_search_signal
    except (ImportError, Exception):
        pass

    keys = list(PARAM_GRID.keys())
    combos = list(product(*PARAM_GRID.values()))
    total = len(combos)
    logger.info("Running %d parameter combinations...", total)

    train_end = "2022-12-31"
    test_start = "2023-01-01"
    results = []

    for i, vals in enumerate(combos):
        params = {**DEFAULT_PARAMS, **dict(zip(keys, vals))}

        # Train period
        engine_train = BacktestEngine(
            etf_data=etf_data, params=params, initial_capital=INITIAL_CAPITAL,
            search_signal_func=search_signal_func, trend_data=trend_data,
        )
        pv_train, trades_train = engine_train.run(BACKTEST_START, train_end)
        metrics_train = compute_metrics(pv_train, trades_train, RISK_FREE_RATE, benchmark_values)

        # Test period
        engine_test = BacktestEngine(
            etf_data=etf_data, params=params, initial_capital=INITIAL_CAPITAL,
            search_signal_func=search_signal_func, trend_data=trend_data,
        )
        pv_test, trades_test = engine_test.run(test_start, BACKTEST_END)
        metrics_test = compute_metrics(pv_test, trades_test, RISK_FREE_RATE, benchmark_values)

        results.append({
            "params": params,
            "train_metrics": metrics_train,
            "test_metrics": metrics_test,
        })

        if verbose and (i + 1) % 50 == 0:
            logger.info("  %d/%d done...", i + 1, total)

    # Sort by train Sharpe, show top 10 with test comparison
    results.sort(key=lambda r: r["train_metrics"].get("sharpe", 0), reverse=True)

    logger.info("\n" + "═" * 80)
    logger.info("  Top 10 Parameter Combinations (by Train Sharpe)")
    logger.info("═" * 80)
    logger.info("  %-5s %10s %12s %10s %11s %8s",
                "Rank", "Train CAGR", "Train Sharpe", "Test CAGR", "Test Sharpe", "Overfit?")
    logger.info("─" * 80)

    for i, r in enumerate(results[:10]):
        tm, ttm = r["train_metrics"], r["test_metrics"]
        train_sharpe = tm.get("sharpe", 0)
        test_sharpe = ttm.get("sharpe", 0)
        overfit = "YES" if train_sharpe > 0 and test_sharpe < train_sharpe * 0.5 else "no"
        logger.info("  %-5d %10.1f%% %12.2f %10.1f%% %11.2f %8s",
                     i + 1, tm.get("cagr", 0) * 100, train_sharpe,
                     ttm.get("cagr", 0) * 100, test_sharpe, overfit)

        if verbose and i == 0:
            p = r["params"]
            logger.info("        Params: vol=%s search=%s sl=%s hold=%sw lookback=%sw",
                         p["vol_threshold"], p["search_threshold"],
                         p["stop_loss"], p["max_hold_weeks"], p["search_lookback_weeks"])

    logger.info("═" * 80)

    # Generate HTML report for best params
    try:
        from report.reporter import generate_html_report
        best_params = results[0]["params"]

        # Re-run full period with best params for report
        engine_full = BacktestEngine(
            etf_data=etf_data, params=best_params, initial_capital=INITIAL_CAPITAL,
            search_signal_func=search_signal_func, trend_data=trend_data,
        )
        pv_full, trades_full = engine_full.run(BACKTEST_START, BACKTEST_END)
        metrics_full = compute_metrics(pv_full, trades_full, RISK_FREE_RATE, benchmark_values)

        generate_html_report(pv_full, trades_full, metrics_full, best_params,
                             benchmark_values, results[:10])
    except Exception as e:
        logger.warning("Could not generate HTML report: %s", e)

    return results


if __name__ == "__main__":
    if "--grid" in sys.argv:
        grid_search()
    else:
        run_single_backtest()
