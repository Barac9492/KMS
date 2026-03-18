"""KMS Configuration — ETF universe, parameters, API keys, paths."""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── ETF Universe & Keywords (loaded from themes.yaml) ────────────────────────

from data.theme_loader import get_etf_universe, get_trend_keywords

ETF_UNIVERSE = get_etf_universe()
TREND_KEYWORDS = get_trend_keywords()

# ── Naver DataLab API ─────────────────────────────────────────────────────────

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

# ── Default Parameters ────────────────────────────────────────────────────────

DEFAULT_PARAMS = {
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

# ── Cost Model ────────────────────────────────────────────────────────────────

SLIPPAGE = 0.003       # 0.3%
TRANSACTION_TAX = 0.0023  # 0.23%
TOTAL_COST = SLIPPAGE + TRANSACTION_TAX  # applied on both entry and exit

# ── Backtest ──────────────────────────────────────────────────────────────────

INITIAL_CAPITAL = 10_000_000  # KRW
BACKTEST_START = "2019-01-01"
BACKTEST_END = "2024-12-31"
RISK_FREE_RATE = 0.035  # 3.5% for Sharpe ratio
BENCHMARK_CODE = "069500"  # KODEX 200 (KOSPI 200 tracker)

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
TREND_CACHE_DIR = os.path.join(BASE_DIR, "data", "trend_cache")
POSITIONS_FILE = os.path.join(BASE_DIR, "data", "positions.json")
REPORT_DIR = os.path.join(BASE_DIR, "report")

# ── Telegram (optional) ─────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
