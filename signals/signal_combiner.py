"""Combine search + volume signals with graceful fallback."""

from config import ETF_UNIVERSE, DEFAULT_PARAMS
from signals.volume_signal import pick_best_etf, compute_volume_signal
from signals.search_signal import compute_search_signal


def compute_combined_signals(
    etf_data: dict,
    trend_data: dict,
    as_of_date: str,
    params: dict | None = None,
) -> list[dict]:
    """Compute combined signals for all themes.

    Falls back to volume-only when no trend data is available for a theme.

    Returns list of signal dicts:
        [{theme, etf_code, etf_name, action, search_sig, volume_sig}, ...]
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    signals = []

    for theme, etfs in ETF_UNIVERSE.items():
        codes = [e["code"] for e in etfs]
        code_to_name = {e["code"]: e["name"] for e in etfs}

        # Search signal
        has_trend = theme in trend_data and not trend_data[theme].empty
        if has_trend:
            search_sig = compute_search_signal(
                trend_data[theme], as_of_date,
                lookback_weeks=params["search_lookback_weeks"],
                recent_weeks=params["search_recent_weeks"],
                threshold=params["search_threshold"],
            )
        else:
            search_sig = {"signal": False, "ratio": 0.0, "trend": "none"}

        # Volume signal — pick best ETF
        best_code, vol_sig = pick_best_etf(
            etf_data, codes, as_of_date,
            vol_threshold=params["vol_threshold"],
        )

        # Determine action
        if has_trend:
            # Combined mode: both signals required
            if search_sig["signal"] and vol_sig.get("signal", False):
                action = "BUY"
            elif search_sig["ratio"] >= params["search_threshold"] * 0.7:
                action = "WATCH"
            else:
                action = "NONE"
        else:
            # Volume-only fallback (stricter threshold)
            vol_threshold_strict = params["vol_threshold"] * 1.2
            if best_code:
                vol_sig_strict = compute_volume_signal(
                    etf_data[best_code], as_of_date, vol_threshold_strict
                )
                if vol_sig_strict["signal"]:
                    action = "BUY"
                elif vol_sig.get("signal", False):
                    action = "WATCH"
                else:
                    action = "NONE"
            else:
                action = "NONE"

        etf_name = code_to_name.get(best_code, "") if best_code else ""
        signals.append({
            "theme": theme,
            "etf_code": best_code or "",
            "etf_name": etf_name,
            "action": action,
            "search_signal": search_sig,
            "volume_signal": vol_sig,
            "has_trend_data": has_trend,
        })

    return signals
