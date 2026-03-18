"""Performance metrics for backtesting."""

import numpy as np
import pandas as pd


def compute_metrics(
    portfolio_values: pd.Series,
    trades: list[dict],
    risk_free_rate: float = 0.035,
    benchmark_values: pd.Series | None = None,
) -> dict:
    """Compute backtest performance metrics.

    Args:
        portfolio_values: Daily portfolio value series (DatetimeIndex).
        trades: List of trade dicts with keys: entry_date, exit_date, entry_price,
                exit_price, return_pct, etf_code, theme.
        risk_free_rate: Annual risk-free rate for Sharpe calculation.
        benchmark_values: Optional benchmark daily values for comparison.

    Returns:
        Dict of metrics.
    """
    if portfolio_values.empty or len(portfolio_values) < 2:
        return {}

    # Total return
    total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1

    # CAGR
    days = (portfolio_values.index[-1] - portfolio_values.index[0]).days
    years = days / 365.25
    cagr = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) ** (1 / years) - 1 if years > 0 else 0

    # MDD
    cummax = portfolio_values.cummax()
    drawdown = (portfolio_values - cummax) / cummax
    mdd = drawdown.min()

    # Daily returns for Sharpe
    daily_returns = portfolio_values.pct_change().dropna()
    if len(daily_returns) > 1:
        excess_return = daily_returns.mean() - risk_free_rate / 252
        sharpe = (excess_return / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0
    else:
        sharpe = 0

    # Trade stats
    completed_trades = [t for t in trades if t.get("exit_date") is not None]
    num_trades = len(completed_trades)
    if num_trades > 0:
        wins = sum(1 for t in completed_trades if t["return_pct"] > 0)
        win_rate = wins / num_trades
        avg_return = np.mean([t["return_pct"] for t in completed_trades])
        holding_days = [
            (pd.Timestamp(t["exit_date"]) - pd.Timestamp(t["entry_date"])).days
            for t in completed_trades
        ]
        avg_hold_days = np.mean(holding_days)
    else:
        win_rate = 0
        avg_return = 0
        avg_hold_days = 0

    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "mdd": mdd,
        "sharpe": sharpe,
        "num_trades": num_trades,
        "win_rate": win_rate,
        "avg_return_per_trade": avg_return,
        "avg_hold_days": avg_hold_days,
    }

    # Benchmark comparison
    if benchmark_values is not None and not benchmark_values.empty:
        bm_return = (benchmark_values.iloc[-1] / benchmark_values.iloc[0]) - 1
        metrics["benchmark_return"] = bm_return
        metrics["excess_return"] = total_return - bm_return

    return metrics


def format_metrics(metrics: dict) -> str:
    """Pretty-print metrics for terminal output."""
    if not metrics:
        return "No metrics to display."

    lines = [
        "═" * 50,
        "  Backtest Results",
        "═" * 50,
        f"  Total Return:       {metrics['total_return']:>8.1%}",
        f"  CAGR:               {metrics['cagr']:>8.1%}",
        f"  MDD:                {metrics['mdd']:>8.1%}",
        f"  Sharpe Ratio:       {metrics['sharpe']:>8.2f}",
        "─" * 50,
        f"  Trades:             {metrics['num_trades']:>8d}",
        f"  Win Rate:           {metrics['win_rate']:>8.1%}",
        f"  Avg Return/Trade:   {metrics['avg_return_per_trade']:>8.1%}",
        f"  Avg Hold Days:      {metrics['avg_hold_days']:>8.1f}",
    ]

    if "benchmark_return" in metrics:
        lines += [
            "─" * 50,
            f"  Benchmark Return:   {metrics['benchmark_return']:>8.1%}",
            f"  Excess Return:      {metrics['excess_return']:>8.1%}",
        ]

    lines.append("═" * 50)
    return "\n".join(lines)
