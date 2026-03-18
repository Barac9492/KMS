"""Batch-scan all keywords via Naver API, detect surges."""

import time
from datetime import datetime, timedelta

from data.theme_loader import get_themes, get_scan_config
from data.fetch_trend import fetch_naver_trend
from signals.lifecycle import compute_search_metrics


def scan_all_themes(
    trend_cache: dict,
    as_of_date: str | None = None,
    lookback_weeks: int = 6,
    recent_weeks: int = 2,
) -> list[dict]:
    """Scan all themes and return search metrics for each.

    Uses cached trend data. Returns sorted by search_ratio descending.

    Returns:
        [{"theme": str, "metrics": dict, "has_instruments": bool}, ...]
    """
    themes = get_themes()
    as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
    results = []

    for theme, cfg in themes.items():
        trend_df = trend_cache.get(theme)
        if trend_df is None or trend_df.empty:
            results.append({
                "theme": theme,
                "metrics": {"ratio": 0.0, "roc": 0.0, "accel": 0.0, "abs_level": 0.0, "trend": "none"},
                "has_instruments": bool(cfg.get("instruments")),
                "category": cfg.get("category", "기타"),
            })
            continue

        metrics = compute_search_metrics(
            trend_df, as_of_date, lookback_weeks, recent_weeks
        )
        results.append({
            "theme": theme,
            "metrics": metrics,
            "has_instruments": bool(cfg.get("instruments")),
            "category": cfg.get("category", "기타"),
        })

    results.sort(key=lambda x: x["metrics"]["ratio"], reverse=True)
    return results


def detect_surges(
    trend_cache: dict,
    as_of_date: str | None = None,
    lookback_weeks: int = 6,
    recent_weeks: int = 2,
    surge_threshold: float | None = None,
) -> list[dict]:
    """Filter themes to those with search_ratio >= surge_threshold.

    Returns list sorted by ratio descending.
    """
    if surge_threshold is None:
        surge_threshold = get_scan_config().get("surge_threshold", 1.5)

    all_themes = scan_all_themes(trend_cache, as_of_date, lookback_weeks, recent_weeks)

    surges = [
        t for t in all_themes
        if t["metrics"]["ratio"] >= surge_threshold
    ]

    # Flag unmapped manias
    for s in surges:
        if not s["has_instruments"]:
            s["alert"] = "UNMAPPED MANIA DETECTED"

    return surges


def batch_fetch_trends(
    themes_to_fetch: list[str] | None = None,
) -> dict:
    """Fetch fresh trend data for themes via Naver API.

    Batches into groups of 5 keywords (Naver API limit per request).
    Returns {theme: DataFrame}.
    """
    all_themes = get_themes()
    scan_config = get_scan_config()
    delay = scan_config.get("batch_delay_seconds", 0.5)

    if themes_to_fetch is None:
        themes_to_fetch = list(all_themes.keys())

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    results = {}
    for i, theme in enumerate(themes_to_fetch):
        cfg = all_themes.get(theme)
        if not cfg or not cfg.get("keywords"):
            continue

        keywords = cfg["keywords"]
        df = fetch_naver_trend(keywords, start_date, end_date)
        if not df.empty:
            results[theme] = df

        # Rate limit
        if i < len(themes_to_fetch) - 1:
            time.sleep(delay)

    return results
