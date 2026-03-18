"""Naver DataLab search trend fetching with CSV caching."""

import os
import sys
import json
import pandas as pd
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET,
    TREND_CACHE_DIR,
)
from data.theme_loader import get_trend_keywords
from kms_logger import logger

NAVER_API_URL = "https://openapi.naver.com/v1/datalab/search"


def _cache_path(theme: str) -> str:
    return os.path.join(TREND_CACHE_DIR, f"{theme}.csv")


def fetch_naver_trend(
    keywords: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch weekly search trend from Naver DataLab API.

    Returns DataFrame with 'date' index and 'ratio' column (0-100 scale).
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return pd.DataFrame()

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "week",
        "keywordGroups": [{"groupName": "target", "keywords": keywords}],
    }

    try:
        response = requests.post(NAVER_API_URL, headers=headers, json=body, timeout=10)
    except requests.exceptions.Timeout:
        logger.warning("Naver API timeout for keywords: %s", keywords[:2])
        return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        logger.warning("Naver API request error: %s", e)
        return pd.DataFrame()
    if response.status_code != 200:
        logger.warning("Naver API error %d: %s", response.status_code, response.text[:200])
        return pd.DataFrame()

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        logger.warning("Naver API returned invalid JSON: %s", e)
        return pd.DataFrame()

    results = data.get("results", [])
    if not results:
        return pd.DataFrame()

    rows = results[0].get("data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["period"])
    df = df.set_index("date")[["ratio"]].sort_index()
    return df


def fetch_and_cache_trend(theme: str, keywords: list[str]) -> pd.DataFrame:
    """Fetch trend data for a theme, merge with cache, save."""
    os.makedirs(TREND_CACHE_DIR, exist_ok=True)
    cache_file = _cache_path(theme)

    # Load existing cache
    cached = pd.DataFrame()
    if os.path.exists(cache_file):
        try:
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        except (pd.errors.ParserError, ValueError) as e:
            logger.warning("Corrupted trend cache for %s, will overwrite: %s", theme, e)

    # Fetch latest year from API
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    new_data = fetch_naver_trend(keywords, start_date, end_date)

    if not new_data.empty:
        if not cached.empty:
            df = pd.concat([cached, new_data])
            df = df[~df.index.duplicated(keep="last")]
            df.sort_index(inplace=True)
        else:
            df = new_data
        df.to_csv(cache_file)
        return df

    return cached


def load_trend_cache(theme: str) -> pd.DataFrame:
    """Load cached trend data for a theme."""
    cache_file = _cache_path(theme)
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    return pd.DataFrame()


def load_all_trend_cache() -> dict:
    """Load all cached trend data. Returns {theme: DataFrame}."""
    result = {}
    for theme in get_trend_keywords():
        df = load_trend_cache(theme)
        if not df.empty:
            result[theme] = df
    return result


def fetch_all_trends():
    """Fetch and cache trend data for all themes from YAML."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("Naver API credentials not set. Set NAVER_CLIENT_ID and "
                        "NAVER_CLIENT_SECRET in .env")
        return

    for theme, keywords in get_trend_keywords().items():
        logger.info("  Fetching trend: %s...", theme)
        df = fetch_and_cache_trend(theme, keywords)
        if not df.empty:
            logger.info("    %d data points (%s → %s)", len(df), df.index.min().date(), df.index.max().date())
        else:
            logger.info("    No data")


if __name__ == "__main__":
    import sys
    if "--init" in sys.argv:
        print("Initializing trend data cache...")
        fetch_all_trends()
        print("Done.")
    else:
        print("Usage: python data/fetch_trend.py --init")
