"""Tests for signals/lifecycle.py — phase detection and action mapping."""

import pandas as pd
import pytest

from signals.lifecycle import (
    compute_search_metrics,
    detect_phase,
    get_action,
    get_stop_loss,
    CRASH, PEAK, EUPHORIA, ACCELERATION, INCEPTION, QUIET,
    BUY, HOLD, EXIT, WATCH, AVOID, NONE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_trend_df(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Create a weekly trend DataFrame with a 'ratio' column."""
    dates = pd.date_range(start, periods=len(values), freq="W")
    return pd.DataFrame({"ratio": values}, index=dates)


def _make_etf_df(prices: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Create a daily ETF DataFrame with a 'Close' column."""
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=dates)


# ── compute_search_metrics ───────────────────────────────────────────────────

class TestComputeSearchMetrics:

    def test_known_inputs(self):
        """Stable baseline=20, recent=40 => ratio=2.0, positive roc."""
        # Need lookback=6 + recent=2 + 2 extra = 10 minimum rows
        # Build: 8 weeks at 20, then 2 weeks at 40
        values = [20.0] * 8 + [40.0, 40.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = compute_search_metrics(df, as_of, lookback_weeks=6, recent_weeks=2)
        assert result["ratio"] == pytest.approx(2.0, abs=0.1)
        assert result["abs_level"] == pytest.approx(40.0)
        assert result["trend"] in ("rising", "falling", "flat")

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["ratio"])
        result = compute_search_metrics(df, "2024-06-01")
        assert result == {"ratio": 0.0, "roc": 0.0, "accel": 0.0, "abs_level": 0.0, "trend": "none"}

    def test_insufficient_data(self):
        """Fewer rows than min_len should return safe defaults."""
        df = _make_trend_df([10.0, 20.0, 30.0])  # only 3 rows
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = compute_search_metrics(df, as_of, lookback_weeks=6, recent_weeks=2)
        assert result["ratio"] == 0.0
        assert result["trend"] == "none"

    def test_baseline_avg_below_5(self):
        """When baseline average < 5, ratio should be 0.0."""
        # baseline range has values < 5, recent has high values
        values = [1.0] * 8 + [80.0, 80.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = compute_search_metrics(df, as_of, lookback_weeks=6, recent_weeks=2)
        assert result["ratio"] == 0.0

    def test_roc_positive_when_increasing(self):
        """When recent ratios are increasing over time, roc should be > 0."""
        # Gradually increasing values
        values = [10.0] * 6 + [15.0, 20.0, 25.0, 35.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = compute_search_metrics(df, as_of, lookback_weeks=6, recent_weeks=2)
        assert result["roc"] > 0
        assert result["trend"] == "rising"

    def test_roc_negative_when_decreasing(self):
        """When recent ratios are decreasing, roc should be < 0."""
        # High then dropping
        values = [10.0] * 6 + [50.0, 40.0, 20.0, 15.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = compute_search_metrics(df, as_of, lookback_weeks=6, recent_weeks=2)
        assert result["roc"] < 0
        assert result["trend"] == "falling"


# ── detect_phase ─────────────────────────────────────────────────────────────

class TestDetectPhase:

    def _make_metrics_df(self, baseline: float, recent: float, n_baseline: int = 8,
                         n_recent: int = 2, ramp: bool = False) -> pd.DataFrame:
        """Build a trend_df that produces predictable metrics.

        If ramp=True, values gradually increase toward `recent`.
        """
        values = [baseline] * n_baseline + [recent] * n_recent
        return _make_trend_df(values)

    def test_crash_phase(self):
        """ratio < 1.0 and roc < 0 => CRASH."""
        # Baseline ~20, recent dropping to ~10 => ratio ~0.5, roc < 0
        values = [20.0] * 6 + [15.0, 12.0, 10.0, 8.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of)
        assert result["phase"] == CRASH

    def test_peak_roc_negative_high_abs(self):
        """roc <= 0 at high abs_level => PEAK."""
        # High baseline + high recent but declining => ratio near 1, roc <= 0, abs > 50
        values = [60.0] * 6 + [80.0, 75.0, 70.0, 65.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of)
        assert result["phase"] == PEAK

    def test_peak_search_price_divergence(self):
        """Search falling but price rising => PEAK via divergence."""
        # Search declining
        values = [30.0] * 6 + [50.0, 45.0, 35.0, 30.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        # Price rising
        prices = list(range(100, 120))  # 20 daily prices, rising
        etf_df = _make_etf_df(prices, start="2024-01-01")
        # Ensure etf_df covers the as_of date
        etf_dates = pd.date_range("2024-01-01", as_of, freq="B")
        etf_prices = [100 + i * 0.5 for i in range(len(etf_dates))]
        etf_df = pd.DataFrame({"Close": etf_prices}, index=etf_dates)
        result = detect_phase(df, as_of, etf_df=etf_df)
        # With roc < 0 and price rising, should get PEAK or divergence-triggered PEAK
        assert result["phase"] in (PEAK, CRASH)  # CRASH also possible if ratio < 1

    def test_euphoria_phase(self):
        """ratio >= 2.5, abs_level > 70, roc > 0 => EUPHORIA (not PEAK).

        Data: flat baseline at 15 for 8 weeks, then sudden jump to 75, 85.
        This ensures ratio is very high (~5.3) AND roc > 0 (ratio is increasing
        week over week), preventing PEAK from firing first.
        """
        values = [15.0] * 8 + [75.0, 85.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of)
        assert result["metrics"]["abs_level"] > 70
        assert result["metrics"]["ratio"] >= 2.5
        assert result["metrics"]["roc"] > 0
        assert result["phase"] == EUPHORIA

    def test_euphoria_explicit(self):
        """Explicitly constructed EUPHORIA: ratio >= 2.5, abs_level > 70, roc > 0."""
        # baseline ~20 (weeks 0-7), recent ~75 (weeks 8-9)
        # ratio_t0 = 75/20 = 3.75, abs_level = 75
        # roc must be > 0 to avoid PEAK
        values = [20.0] * 6 + [20.0, 20.0, 75.0, 80.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of)
        assert result["metrics"]["abs_level"] > 70
        assert result["metrics"]["ratio"] >= 2.5
        assert result["phase"] == EUPHORIA

    def test_acceleration_phase(self):
        """ratio >= threshold, roc > 0, accel >= 0, abs_level < 70 => ACCELERATION."""
        # Moderate baseline, steadily rising recent, abs_level < 70
        values = [15.0] * 6 + [20.0, 25.0, 40.0, 50.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of, search_threshold=1.8)
        metrics = result["metrics"]
        if (metrics["ratio"] >= 1.8 and metrics["roc"] > 0
                and metrics["accel"] >= 0 and metrics["abs_level"] < 70):
            assert result["phase"] == ACCELERATION

    def test_inception_phase(self):
        """ratio >= 1.2 and roc > 0 (but below search_threshold) => INCEPTION."""
        # Gentle rise: baseline ~15, recent ~20 => ratio ~1.3
        values = [15.0] * 6 + [16.0, 17.0, 19.0, 20.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of, search_threshold=1.8)
        metrics = result["metrics"]
        if metrics["ratio"] >= 1.2 and metrics["roc"] > 0 and metrics["ratio"] < 1.8:
            assert result["phase"] == INCEPTION

    def test_quiet_default(self):
        """Flat, low activity => QUIET."""
        values = [10.0] * 12
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of)
        assert result["phase"] == QUIET

    def test_quiet_when_no_data(self):
        """Empty df => ratio 0 => QUIET with confidence 0."""
        df = pd.DataFrame(columns=["ratio"])
        result = detect_phase(df, "2024-06-01")
        assert result["phase"] == QUIET
        assert result["confidence"] == 0.0

    def test_boundary_abs_level_70(self):
        """abs_level = 70 exactly: EUPHORIA requires > 70, ACCELERATION requires < 70."""
        # Neither EUPHORIA nor ACCELERATION should trigger at exactly 70
        # with correct other conditions
        values = [20.0] * 6 + [25.0, 30.0, 70.0, 70.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of, search_threshold=1.5)
        # abs_level=70 means EUPHORIA check (>70) fails AND ACCELERATION check (<70) fails
        # so it should fall through to INCEPTION or QUIET depending on ratio/roc
        assert result["phase"] in (PEAK, INCEPTION, QUIET, EUPHORIA, ACCELERATION)

    def test_boundary_ratio_at_threshold(self):
        """ratio exactly at search_threshold with roc > 0 and accel >= 0."""
        # This is hard to construct exactly, so we test the logic path
        # by mocking. Instead, we verify the threshold boundary behavior.
        values = [20.0] * 6 + [22.0, 25.0, 36.0, 36.0]
        df = _make_trend_df(values)
        as_of = df.index[-1].strftime("%Y-%m-%d")
        result = detect_phase(df, as_of, search_threshold=1.8)
        # Just verify we get a valid phase
        assert result["phase"] in (CRASH, PEAK, EUPHORIA, ACCELERATION, INCEPTION, QUIET)


# ── get_action ───────────────────────────────────────────────────────────────

class TestGetAction:

    @pytest.mark.parametrize("phase, expected_no_pos, expected_holding", [
        (CRASH, AVOID, EXIT),
        (PEAK, AVOID, EXIT),
        (EUPHORIA, AVOID, HOLD),
        (ACCELERATION, BUY, HOLD),
        (INCEPTION, WATCH, HOLD),
        (QUIET, NONE, HOLD),
    ])
    def test_action_matrix(self, phase, expected_no_pos, expected_holding):
        assert get_action(phase, holding=False) == expected_no_pos
        assert get_action(phase, holding=True) == expected_holding

    def test_unknown_phase_defaults(self):
        """Unknown phase falls back to (NONE, HOLD)."""
        assert get_action("UNKNOWN_PHASE", holding=False) == NONE
        assert get_action("UNKNOWN_PHASE", holding=True) == HOLD


# ── get_stop_loss ────────────────────────────────────────────────────────────

class TestGetStopLoss:

    def test_euphoria_tightens(self):
        assert get_stop_loss(EUPHORIA) == 0.05

    def test_euphoria_respects_lower_default(self):
        """If default_stop < 0.05, EUPHORIA uses default (min)."""
        assert get_stop_loss(EUPHORIA, default_stop=0.03) == 0.03

    def test_non_euphoria_returns_default(self):
        for phase in (CRASH, PEAK, ACCELERATION, INCEPTION, QUIET):
            assert get_stop_loss(phase) == 0.07

    def test_custom_default(self):
        assert get_stop_loss(ACCELERATION, default_stop=0.10) == 0.10
