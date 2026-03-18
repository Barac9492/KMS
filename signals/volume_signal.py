"""Volume signal: vol_ratio >= threshold AND close > MA20."""

import pandas as pd


def compute_volume_signal(
    df: pd.DataFrame,
    as_of_date: str,
    vol_threshold: float = 1.5,
) -> dict:
    """Compute volume signal for a single ETF as of a given date.

    Args:
        df: ETF DataFrame with Close, MA20, Volume, VolMA20, VolRatio columns.
        as_of_date: Date string. Only data up to this date is used.
        vol_threshold: Minimum vol_ratio for signal ON.

    Returns:
        {"signal": bool, "vol_ratio": float, "above_ma20": bool}
    """
    sliced = df.loc[:as_of_date]
    if sliced.empty or pd.isna(sliced["VolRatio"].iloc[-1]) or pd.isna(sliced["MA20"].iloc[-1]):
        return {"signal": False, "vol_ratio": 0.0, "above_ma20": False}

    row = sliced.iloc[-1]
    vol_ratio = float(row["VolRatio"])
    above_ma20 = bool(row["Close"] > row["MA20"])
    signal = vol_ratio >= vol_threshold and above_ma20

    return {"signal": signal, "vol_ratio": vol_ratio, "above_ma20": above_ma20}


def pick_best_etf(
    etf_data: dict,
    etf_codes: list[str],
    as_of_date: str,
    vol_threshold: float = 1.5,
) -> tuple[str | None, dict]:
    """Among ETFs for a theme, pick the one with highest vol_ratio that has signal ON.

    Returns:
        (best_code, best_signal) or (None, {}) if no signal.
    """
    best_code = None
    best_signal = {}
    best_ratio = 0.0

    for code in etf_codes:
        if code not in etf_data:
            continue
        df = etf_data[code]
        if as_of_date < df.index.min().strftime("%Y-%m-%d"):
            continue  # ETF doesn't exist yet at this date
        sig = compute_volume_signal(df, as_of_date, vol_threshold)
        if sig["signal"] and sig["vol_ratio"] > best_ratio:
            best_code = code
            best_signal = sig
            best_ratio = sig["vol_ratio"]

    return best_code, best_signal
