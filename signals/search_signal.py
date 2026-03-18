"""Search signal: search_ratio >= threshold AND rising."""

import pandas as pd


def compute_search_signal(
    trend_df: pd.DataFrame,
    as_of_date: str,
    lookback_weeks: int = 6,
    recent_weeks: int = 2,
    threshold: float = 1.8,
) -> dict:
    """Compute search signal for a theme as of a given date.

    Args:
        trend_df: Weekly trend DataFrame with 'ratio' column (0-100 scale).
        as_of_date: Only use data up to this date.
        lookback_weeks: Baseline period (prior N weeks).
        recent_weeks: Recent period for comparison.
        threshold: Minimum search_ratio for signal ON.

    Returns:
        {"signal": bool, "ratio": float, "trend": "rising"|"falling"|"none"}
    """
    if trend_df.empty:
        return {"signal": False, "ratio": 0.0, "trend": "none"}

    # Weekly data — ffill to daily for alignment, then slice
    sliced = trend_df.loc[:as_of_date]
    if len(sliced) < lookback_weeks + recent_weeks:
        return {"signal": False, "ratio": 0.0, "trend": "none"}

    recent = sliced["ratio"].iloc[-recent_weeks:]
    baseline = sliced["ratio"].iloc[-(lookback_weeks + recent_weeks):-recent_weeks]

    recent_avg = recent.mean()
    baseline_avg = baseline.mean()

    # Edge case: if baseline avg < 5 (on 0-100 scale), treat as no data
    if baseline_avg < 5:
        return {"signal": False, "ratio": 0.0, "trend": "none"}

    search_ratio = recent_avg / baseline_avg

    # Determine trend direction: compare current ratio to previous week's ratio
    if len(sliced) >= lookback_weeks + recent_weeks + 1:
        prev_recent = sliced["ratio"].iloc[-(recent_weeks + 1):-1]
        prev_baseline = sliced["ratio"].iloc[-(lookback_weeks + recent_weeks + 1):-(recent_weeks + 1)]
        prev_baseline_avg = prev_baseline.mean()
        if prev_baseline_avg >= 5:
            prev_ratio = prev_recent.mean() / prev_baseline_avg
            trend = "rising" if search_ratio > prev_ratio else "falling"
        else:
            trend = "rising"  # can't determine, assume rising
    else:
        trend = "rising"

    signal = search_ratio >= threshold and trend == "rising"

    return {"signal": signal, "ratio": search_ratio, "trend": trend}


def align_weekly_to_daily(trend_df: pd.DataFrame, daily_dates: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill weekly trend data to daily frequency.

    Signal changes at most weekly (from Monday).
    """
    if trend_df.empty:
        return pd.Series(dtype=float)

    # Reindex to daily and ffill
    daily = trend_df["ratio"].reindex(daily_dates).ffill()
    return daily
