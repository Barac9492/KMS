"""Shared utilities for KMS."""

import pandas as pd


def get_latest_price(df: pd.DataFrame, as_of_date: str) -> float | None:
    """Get the latest closing price from a DataFrame up to a given date.

    Returns None if no data is available.
    """
    sliced = df.loc[:as_of_date]
    if sliced.empty:
        return None
    return float(sliced["Close"].iloc[-1])
