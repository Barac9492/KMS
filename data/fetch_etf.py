"""ETF OHLCV data fetching with CSV caching."""

import os
import pandas as pd
import FinanceDataReader as fdr
from config import DATA_CACHE_DIR
from kms_logger import logger


def _cache_path(code: str) -> str:
    return os.path.join(DATA_CACHE_DIR, f"{code}.csv")


def fetch_etf_data(code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """Fetch ETF OHLCV data. Caches raw data to CSV; indicators recomputed on load."""
    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    cache_file = _cache_path(code)

    if use_cache and os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        except (pd.errors.ParserError, ValueError) as e:
            logger.warning("Corrupted cache for %s, refetching: %s", code, e)
            df = pd.DataFrame()

        if not df.empty:
            needs_update = False
            # Extend backward: cache starts after requested start
            if df.index.min().strftime("%Y-%m-%d") > start:
                pre_end = (df.index.min() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    pre_df = fdr.DataReader(code, start, pre_end)
                    if not pre_df.empty:
                        df = pd.concat([pre_df, df])
                        needs_update = True
                except Exception as e:
                    logger.warning("Failed to extend cache backward for %s: %s", code, e)

            # Extend forward: cache ends before requested end
            if df.index.max().strftime("%Y-%m-%d") < end:
                new_start = (df.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    new_df = fdr.DataReader(code, new_start, end)
                    if not new_df.empty:
                        df = pd.concat([df, new_df])
                        needs_update = True
                except Exception as e:
                    logger.warning("Failed to extend cache forward for %s: %s", code, e)

            if needs_update:
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)
                df.to_csv(cache_file)
    else:
        try:
            df = fdr.DataReader(code, start, end)
            if df.empty:
                logger.info("No data returned for ETF %s", code)
                return pd.DataFrame()
            df.to_csv(cache_file)
        except Exception as e:
            logger.warning("Failed to fetch ETF %s: %s", code, e)
            return pd.DataFrame()

    # Filter to requested range
    df = df.loc[start:end].copy()
    return df


def add_indicators(df: pd.DataFrame, ma_period: int = 20) -> pd.DataFrame:
    """Add MA20, VolMA20, VolRatio indicators. Recomputed each time (enables grid search)."""
    if df.empty:
        return df
    df = df.copy()
    df["MA20"] = df["Close"].rolling(ma_period).mean()
    df["VolMA20"] = df["Volume"].rolling(ma_period).mean()
    df["VolRatio"] = df["Volume"] / df["VolMA20"]
    return df


def fetch_all_etfs(etf_universe: dict, start: str, end: str, ma_period: int = 20) -> dict:
    """Fetch and add indicators for all ETFs in the universe.
    Returns {code: DataFrame} for ETFs that have data."""
    result = {}
    for theme, etfs in etf_universe.items():
        for etf in etfs:
            code = etf["code"]
            df = fetch_etf_data(code, start, end)
            if not df.empty:
                df = add_indicators(df, ma_period)
                result[code] = df
    return result
