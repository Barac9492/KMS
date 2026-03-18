"""Tests for utils, run.load_positions, and notify._send."""

import json
import os
import tempfile

import pandas as pd
import pytest
from unittest.mock import patch

from utils import get_latest_price


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_etf_df(prices: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=dates)


# ── get_latest_price ─────────────────────────────────────────────────────────

class TestGetLatestPrice:

    def test_returns_float_for_valid_data(self):
        df = _make_etf_df([100.0, 105.0, 110.0])
        result = get_latest_price(df, "2024-01-05")
        assert isinstance(result, float)
        assert result == pytest.approx(110.0)

    def test_returns_none_for_empty_df(self):
        df = pd.DataFrame(columns=["Close"])
        df.index = pd.DatetimeIndex([], name="Date")
        result = get_latest_price(df, "2024-01-05")
        assert result is None

    def test_returns_none_when_date_before_all_data(self):
        df = _make_etf_df([100.0, 105.0], start="2024-06-01")
        result = get_latest_price(df, "2024-01-01")
        assert result is None

    def test_returns_latest_before_date(self):
        """When as_of_date is between data points, returns the last available."""
        df = _make_etf_df([100.0, 200.0, 300.0], start="2024-01-01")
        # 2024-01-02 is the second business day
        result = get_latest_price(df, "2024-01-02")
        assert result == pytest.approx(200.0)


# ── load_positions ───────────────────────────────────────────────────────────

class TestLoadPositions:

    def test_corrupted_json_recovery(self):
        """Corrupted JSON should be backed up and return empty state."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json content!!!}")
            tmp_path = f.name

        try:
            with patch("run.POSITIONS_FILE", tmp_path):
                from run import load_positions
                result = load_positions()

            assert result == {"positions": [], "closed": []}
            # Backup file should exist
            assert os.path.exists(tmp_path + ".corrupt")
        finally:
            os.unlink(tmp_path)
            if os.path.exists(tmp_path + ".corrupt"):
                os.unlink(tmp_path + ".corrupt")

    def test_missing_file_returns_default(self):
        """Non-existent file returns empty state."""
        with patch("run.POSITIONS_FILE", "/tmp/nonexistent_kms_test_positions.json"):
            from run import load_positions
            result = load_positions()
        assert result == {"positions": [], "closed": []}

    def test_valid_json_loads_correctly(self):
        """Valid JSON loads as expected."""
        state = {"positions": [{"theme": "AI"}], "closed": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            tmp_path = f.name

        try:
            with patch("run.POSITIONS_FILE", tmp_path):
                from run import load_positions
                result = load_positions()
            assert result == state
        finally:
            os.unlink(tmp_path)


# ── notify._send ─────────────────────────────────────────────────────────────

class TestNotifySend:

    def test_returns_false_when_credentials_not_set(self):
        """_send returns False when TELEGRAM_BOT_TOKEN or CHAT_ID is empty."""
        with patch("notify.TELEGRAM_BOT_TOKEN", ""), \
             patch("notify.TELEGRAM_CHAT_ID", ""):
            from notify import _send
            result = _send("test message")
        assert result is False
