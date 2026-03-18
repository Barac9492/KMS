"""Load themes from YAML, provide backward-compatible dicts."""

import os
import yaml

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_YAML_PATH = os.path.join(_BASE_DIR, "themes.yaml")

_cache = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    with open(_YAML_PATH, encoding="utf-8") as f:
        _cache = yaml.safe_load(f)
    return _cache


def get_scan_config() -> dict:
    """Return scan-level config (surge_threshold, batch_delay_seconds)."""
    return _load().get("scan", {})


def get_themes() -> dict:
    """Return raw themes dict from YAML."""
    return _load().get("themes", {})


def get_etf_universe() -> dict:
    """Backward-compatible ETF_UNIVERSE dict.

    Returns {theme: [{"name": ..., "code": ..., "type": ...}, ...]}
    Only themes with at least one instrument are included.
    """
    universe = {}
    for theme, cfg in get_themes().items():
        instruments = cfg.get("instruments", [])
        if instruments:
            universe[theme] = instruments
    return universe


def get_trend_keywords() -> dict:
    """Backward-compatible TREND_KEYWORDS dict.

    Returns {theme: [keyword, ...]}
    """
    return {
        theme: cfg["keywords"]
        for theme, cfg in get_themes().items()
        if cfg.get("keywords")
    }


def get_all_etf_codes() -> list[str]:
    """Return flat list of all unique instrument codes."""
    codes = set()
    for cfg in get_themes().values():
        for inst in cfg.get("instruments", []):
            codes.add(inst["code"])
    return sorted(codes)


def get_theme_categories() -> dict[str, str]:
    """Return {theme: category} mapping."""
    return {
        theme: cfg.get("category", "기타")
        for theme, cfg in get_themes().items()
    }


def get_instrument_slippage(instrument: dict) -> float:
    """Return slippage for an instrument — stocks have higher slippage."""
    return 0.005 if instrument.get("type") == "stock" else 0.003
