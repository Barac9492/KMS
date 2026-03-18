"""Mania lifecycle phase detection.

Phases (evaluated danger-first):
    CRASH → PEAK → EUPHORIA → ACCELERATION → INCEPTION → QUIET

Each phase maps to a trading action depending on whether we hold a position.
"""

import pandas as pd
from signals.search_signal import compute_search_signal


# Phase constants
CRASH = "CRASH"
PEAK = "PEAK"
EUPHORIA = "EUPHORIA"
ACCELERATION = "ACCELERATION"
INCEPTION = "INCEPTION"
QUIET = "QUIET"

# Actions
BUY = "BUY"
HOLD = "HOLD"
EXIT = "EXIT"
WATCH = "WATCH"
AVOID = "AVOID"
NONE = "NONE"

# Action matrix: phase → (action_no_position, action_holding)
PHASE_ACTIONS = {
    CRASH:        (AVOID, EXIT),
    PEAK:         (AVOID, EXIT),
    EUPHORIA:     (AVOID, HOLD),   # too late to enter, but let winners run
    ACCELERATION: (BUY,   HOLD),
    INCEPTION:    (WATCH, HOLD),
    QUIET:        (NONE,  HOLD),
}


def compute_search_metrics(
    trend_df: pd.DataFrame,
    as_of_date: str,
    lookback_weeks: int = 6,
    recent_weeks: int = 2,
) -> dict:
    """Compute search ratio, rate of change, and acceleration for a theme.

    Returns dict with keys:
        ratio, roc, accel, abs_level, trend
    """
    if trend_df.empty:
        return {"ratio": 0.0, "roc": 0.0, "accel": 0.0, "abs_level": 0.0, "trend": "none"}

    sliced = trend_df.loc[:as_of_date]
    min_len = lookback_weeks + recent_weeks + 2  # need 2 extra for roc/accel
    if len(sliced) < min_len:
        return {"ratio": 0.0, "roc": 0.0, "accel": 0.0, "abs_level": 0.0, "trend": "none"}

    def _ratio_at(data: pd.DataFrame, offset: int = 0) -> float:
        """Compute search_ratio at a given offset (0=current, 1=one week ago)."""
        end_idx = len(data) - offset
        if end_idx < lookback_weeks + recent_weeks:
            return 0.0
        recent = data["ratio"].iloc[end_idx - recent_weeks:end_idx]
        baseline = data["ratio"].iloc[end_idx - lookback_weeks - recent_weeks:end_idx - recent_weeks]
        baseline_avg = baseline.mean()
        if baseline_avg < 5:
            return 0.0
        return recent.mean() / baseline_avg

    ratio_t0 = _ratio_at(sliced, 0)
    ratio_t1 = _ratio_at(sliced, 1)
    ratio_t2 = _ratio_at(sliced, 2)

    roc = ratio_t0 - ratio_t1       # 1st derivative
    accel = roc - (ratio_t1 - ratio_t2)  # 2nd derivative

    # Absolute level: recent average on 0-100 scale
    abs_level = sliced["ratio"].iloc[-recent_weeks:].mean()

    trend = "rising" if roc > 0 else ("falling" if roc < 0 else "flat")

    return {
        "ratio": ratio_t0,
        "roc": roc,
        "accel": accel,
        "abs_level": abs_level,
        "trend": trend,
    }


def detect_phase(
    trend_df: pd.DataFrame,
    as_of_date: str,
    etf_df: pd.DataFrame | None = None,
    lookback_weeks: int = 6,
    recent_weeks: int = 2,
    search_threshold: float = 1.8,
) -> dict:
    """Detect mania lifecycle phase for a theme.

    Args:
        trend_df: Weekly trend DataFrame with 'ratio' column.
        as_of_date: Date to evaluate at.
        etf_df: Optional ETF price DataFrame for search-price divergence.
        lookback_weeks: Baseline period.
        recent_weeks: Recent period.
        search_threshold: Minimum ratio for ACCELERATION.

    Returns:
        {"phase": str, "metrics": dict, "confidence": float}
    """
    metrics = compute_search_metrics(
        trend_df, as_of_date, lookback_weeks, recent_weeks
    )

    ratio = metrics["ratio"]
    roc = metrics["roc"]
    accel = metrics["accel"]
    abs_level = metrics["abs_level"]

    # No data → QUIET
    if ratio == 0.0:
        return {"phase": QUIET, "metrics": metrics, "confidence": 0.0}

    # Check search-price divergence (search declining but price rising)
    divergence = False
    if etf_df is not None and not etf_df.empty and roc < 0:
        price_sliced = etf_df.loc[:as_of_date]
        if len(price_sliced) >= 10:
            price_recent = price_sliced["Close"].iloc[-5:].mean()
            price_prior = price_sliced["Close"].iloc[-10:-5].mean()
            if price_prior > 0 and price_recent > price_prior:
                divergence = True

    # Phase classification (evaluated top-down, danger-first)

    # CRASH: ratio below baseline and declining
    if ratio < 1.0 and roc < 0:
        confidence = min(1.0, abs(roc) * 5)
        return {"phase": CRASH, "metrics": metrics, "confidence": confidence}

    # PEAK: roc turning negative at high levels, or search-price divergence
    if divergence:
        return {"phase": PEAK, "metrics": metrics, "confidence": 0.8}
    if (roc <= 0 or accel < -0.1) and abs_level > 50:
        confidence = min(1.0, abs_level / 100 + abs(roc) * 3)
        return {"phase": PEAK, "metrics": metrics, "confidence": confidence}

    # EUPHORIA: very high ratio + volume confirmed + high absolute
    if ratio >= 2.5 and abs_level > 70:
        confidence = min(1.0, ratio / 3.0)
        return {"phase": EUPHORIA, "metrics": metrics, "confidence": confidence}

    # ACCELERATION: ratio above threshold, rising, not decelerating
    if ratio >= search_threshold and roc > 0 and accel >= 0 and abs_level < 70:
        confidence = min(1.0, (ratio - search_threshold) / search_threshold + roc * 5)
        return {"phase": ACCELERATION, "metrics": metrics, "confidence": confidence}

    # INCEPTION: slightly elevated ratio, rising
    if ratio >= 1.2 and roc > 0:
        confidence = min(1.0, (ratio - 1.0) * 2)
        return {"phase": INCEPTION, "metrics": metrics, "confidence": confidence}

    # QUIET: default
    return {"phase": QUIET, "metrics": metrics, "confidence": 0.0}


def get_action(phase: str, holding: bool) -> str:
    """Map phase to trading action based on whether we hold a position."""
    no_pos_action, hold_action = PHASE_ACTIONS.get(phase, (NONE, HOLD))
    return hold_action if holding else no_pos_action


def get_stop_loss(phase: str, default_stop: float = 0.07) -> float:
    """Return stop-loss for current phase. Tightened during EUPHORIA."""
    if phase == EUPHORIA:
        return min(default_stop, 0.05)
    return default_stop
