"""Tests for backtest/engine.py — BacktestEngine."""

import pandas as pd
import pytest
from unittest.mock import patch

from backtest.engine import BacktestEngine, Position


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_etf_df(prices: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Create a daily ETF DataFrame with 'Close' and 'Volume' columns."""
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({
        "Close": prices,
        "Volume": [1_000_000] * len(prices),
    }, index=dates)


def _make_trend_df(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Create a weekly trend DataFrame with 'ratio' column."""
    dates = pd.date_range(start, periods=len(values), freq="W")
    return pd.DataFrame({"ratio": values}, index=dates)


# Minimal ETF_UNIVERSE for tests (patched into config)
_TEST_ETF_UNIVERSE = {
    "테스트": [
        {"code": "TEST01", "name": "Test ETF 1", "type": "etf"},
    ],
    "테스트2": [
        {"code": "TEST02", "name": "Test ETF 2", "type": "stock"},
    ],
}

_TEST_PARAMS = {
    "search_threshold": 1.8,
    "vol_threshold": 1.5,
    "stop_loss": 0.07,
    "max_hold_weeks": 4,
    "search_lookback_weeks": 6,
    "search_recent_weeks": 2,
    "ma_period": 20,
    "position_size": 0.20,
    "max_positions": 5,
}


@pytest.fixture
def simple_etf_data():
    """ETF data with 60 business days of stable prices."""
    prices = [10000.0 + i * 10 for i in range(60)]
    return {"TEST01": _make_etf_df(prices)}


@pytest.fixture
def engine(simple_etf_data):
    """Basic engine with one ETF, patched ETF_UNIVERSE."""
    with patch("backtest.engine.ETF_UNIVERSE", _TEST_ETF_UNIVERSE):
        eng = BacktestEngine(
            etf_data=simple_etf_data,
            params=_TEST_PARAMS,
            initial_capital=10_000_000,
        )
    return eng


# ── _should_exit ─────────────────────────────────────────────────────────────

class TestShouldExit:

    def test_time_exit(self, engine, simple_etf_data):
        """Position held >= max_hold_weeks * 7 days triggers time exit."""
        pos = Position(
            theme="테스트", etf_code="TEST01", etf_name="Test ETF 1",
            entry_date="2024-01-01", entry_price=10000.0, shares=100, cost=1_000_000,
        )
        # 4 weeks * 7 = 28 days later
        exit_date = "2024-02-05"  # 35 days later
        should, reason = engine._should_exit(pos, exit_date)
        assert should is True
        assert reason == "time_exit"

    def test_stop_loss_exit(self, engine):
        """Price drop > stop_loss triggers stop loss exit."""
        # Entry at 10000, price drops to 9200 => -8% > 7% stop loss
        prices = [10000.0] * 5 + [9200.0] * 5
        engine.etf_data["TEST01"] = _make_etf_df(prices)
        pos = Position(
            theme="테스트", etf_code="TEST01", etf_name="Test ETF 1",
            entry_date="2024-01-01", entry_price=10000.0, shares=100, cost=1_000_000,
        )
        exit_date = "2024-01-12"  # within max_hold but after price drop
        should, reason = engine._should_exit(pos, exit_date)
        assert should is True
        assert reason == "stop_loss"

    def test_no_exit_conditions(self, engine, simple_etf_data):
        """No exit when price is fine and within hold period."""
        pos = Position(
            theme="테스트", etf_code="TEST01", etf_name="Test ETF 1",
            entry_date="2024-01-15", entry_price=10000.0, shares=100, cost=1_000_000,
        )
        # Only 5 days later, price stable
        exit_date = "2024-01-22"
        should, reason = engine._should_exit(pos, exit_date)
        assert should is False
        assert reason == ""


# ── _enter_position ──────────────────────────────────────────────────────────

class TestEnterPosition:

    def test_creates_position(self, engine, simple_etf_data):
        """Entering a position creates a Position with correct fields."""
        initial_cash = engine.cash
        engine._enter_position("테스트", "TEST01", "2024-01-15")
        assert len(engine.positions) == 1
        pos = engine.positions[0]
        assert pos.theme == "테스트"
        assert pos.etf_code == "TEST01"
        assert pos.shares > 0
        assert engine.cash < initial_cash

    def test_skips_missing_etf(self, engine):
        """No position created when ETF code not in data."""
        engine._enter_position("테스트", "MISSING", "2024-01-15")
        assert len(engine.positions) == 0

    def test_entry_phase_recorded(self, engine, simple_etf_data):
        """Phase is stored on the position."""
        engine._enter_position("테스트", "TEST01", "2024-01-15", phase="ACCELERATION")
        assert engine.positions[0].entry_phase == "ACCELERATION"


# ── _portfolio_value ─────────────────────────────────────────────────────────

class TestPortfolioValue:

    def test_cash_only(self, engine):
        """No positions => portfolio value equals cash."""
        val = engine._portfolio_value("2024-01-15")
        assert val == engine.cash

    def test_cash_plus_positions(self, engine, simple_etf_data):
        """Portfolio value = cash + mark-to-market positions."""
        engine._enter_position("테스트", "TEST01", "2024-01-15")
        val = engine._portfolio_value("2024-01-22")
        # Should be roughly initial capital (minus slippage costs)
        assert val > 0
        assert val != engine.cash  # positions add value


# ── run() ────────────────────────────────────────────────────────────────────

class TestRun:

    def test_empty_data_returns_empty(self):
        """Engine with no ETF data returns empty series and no trades."""
        with patch("backtest.engine.ETF_UNIVERSE", {}):
            eng = BacktestEngine(etf_data={}, params=_TEST_PARAMS)
        pv, trades = eng.run("2024-01-01", "2024-03-01")
        assert len(pv) == 0
        assert trades == []

    def test_closes_positions_at_end(self, simple_etf_data):
        """All positions should be closed at the end of the backtest."""
        # Create an engine that will enter a position via lifecycle
        trend_values = [10.0] * 6 + [15.0, 20.0, 40.0, 50.0, 55.0, 60.0]
        trend_df = _make_trend_df(trend_values)
        trend_data = {"테스트": trend_df}

        with patch("backtest.engine.ETF_UNIVERSE", _TEST_ETF_UNIVERSE):
            with patch("backtest.engine.pick_best_etf", return_value=("TEST01", {"vol_ratio": 2.0})):
                eng = BacktestEngine(
                    etf_data=simple_etf_data,
                    params=_TEST_PARAMS,
                    initial_capital=10_000_000,
                    trend_data=trend_data,
                )
                pv, trades = eng.run("2024-01-01", "2024-03-22")

        # After run completes, no open positions should remain
        assert len(eng.positions) == 0

    def test_run_produces_portfolio_series(self, simple_etf_data):
        """run() returns a pd.Series for portfolio values."""
        with patch("backtest.engine.ETF_UNIVERSE", _TEST_ETF_UNIVERSE):
            eng = BacktestEngine(
                etf_data=simple_etf_data,
                params=_TEST_PARAMS,
                initial_capital=10_000_000,
            )
            pv, trades = eng.run("2024-01-01", "2024-03-22")

        assert isinstance(pv, pd.Series)
        # Should have at least one value for each trading day
        assert len(pv) > 0
