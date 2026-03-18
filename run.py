"""Weekly signal generation — mania lifecycle detection."""

import csv
import json
import os
import shutil
from datetime import datetime, timedelta

import pandas as pd

from config import (
    ETF_UNIVERSE, DEFAULT_PARAMS, POSITIONS_FILE,
    TOTAL_COST,
)
from data.fetch_etf import fetch_all_etfs, add_indicators
from data.fetch_trend import load_all_trend_cache, fetch_all_trends
from kms_logger import logger
from notify import send_signal_report, send_error_alert
from signals.lifecycle import detect_phase, get_action, get_stop_loss, PHASE_ACTIONS, BUY, EXIT, WATCH, HOLD
from signals.keyword_scanner import scan_all_themes, detect_surges
from signals.volume_signal import pick_best_etf
from utils import get_latest_price

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCURACY_LOG = os.path.join(_BASE_DIR, "signal_accuracy.csv")


def load_positions() -> dict:
    """Load current position state from JSON. Recovers from corruption."""
    if not os.path.exists(POSITIONS_FILE):
        return {"positions": [], "closed": []}
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Corrupted positions.json: %s — backing up and starting fresh", e)
        backup = POSITIONS_FILE + ".corrupt"
        shutil.copy2(POSITIONS_FILE, backup)
        logger.info("Backup saved to %s", backup)
        return {"positions": [], "closed": []}
    except OSError as e:
        logger.error("Cannot read positions.json: %s", e)
        return {"positions": [], "closed": []}


def save_positions(state: dict):
    """Save position state to JSON with atomic write."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    tmp = POSITIONS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, POSITIONS_FILE)
    except OSError as e:
        logger.error("Failed to save positions: %s", e)


def log_accuracy(trade: dict):
    """Append a closed trade to the signal accuracy CSV."""
    file_exists = os.path.exists(ACCURACY_LOG)
    try:
        with open(ACCURACY_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "theme", "etf_code", "etf_name", "entry_date", "exit_date",
                "entry_phase", "entry_price", "exit_price", "return_pct",
                "exit_reason", "hold_days",
            ])
            if not file_exists:
                writer.writeheader()

            hold_days = (pd.Timestamp(trade.get("exit_date", "")) -
                         pd.Timestamp(trade.get("entry_date", ""))).days

            writer.writerow({
                "theme": trade.get("theme", ""),
                "etf_code": trade.get("etf_code", ""),
                "etf_name": trade.get("etf_name", ""),
                "entry_date": trade.get("entry_date", ""),
                "exit_date": trade.get("exit_date", ""),
                "entry_phase": trade.get("entry_phase", ""),
                "entry_price": trade.get("entry_price", ""),
                "exit_price": trade.get("current_price", ""),
                "return_pct": f"{trade.get('pnl_pct', 0):.4f}",
                "exit_reason": trade.get("exit_reason", ""),
                "hold_days": hold_days,
            })
    except OSError as e:
        logger.warning("Failed to log accuracy: %s", e)


def check_exits(state: dict, etf_data: dict, trend_data: dict,
                today: str, params: dict) -> list[dict]:
    """Check if any held positions should be exited (lifecycle-aware)."""
    exits = []
    remaining = []

    for pos in state["positions"]:
        entry_date = pd.Timestamp(pos["entry_date"])
        current_date = pd.Timestamp(today)
        hold_days = (current_date - entry_date).days

        should_exit = False
        reason = ""

        # Time exit
        if hold_days >= params["max_hold_weeks"] * 7:
            should_exit = True
            reason = "time_exit"

        # Price + lifecycle check
        if pos["etf_code"] in etf_data:
            df = etf_data[pos["etf_code"]]
            current_price = get_latest_price(df, today)
            if current_price is not None:
                pnl_pct = (current_price / pos["entry_price"]) - 1
                pos["current_price"] = current_price
                pos["pnl_pct"] = pnl_pct

                # Lifecycle phase check
                theme = pos["theme"]
                stop_loss = params["stop_loss"]
                if theme in trend_data:
                    try:
                        phase_result = detect_phase(
                            trend_data[theme], today,
                            etf_df=df,
                            lookback_weeks=params["search_lookback_weeks"],
                            recent_weeks=params["search_recent_weeks"],
                            search_threshold=params["search_threshold"],
                        )
                        phase = phase_result["phase"]
                        pos["phase"] = phase
                        action = get_action(phase, holding=True)
                        if action == EXIT and not should_exit:
                            should_exit = True
                            reason = f"lifecycle_{phase.lower()}"

                        stop_loss = get_stop_loss(phase, params["stop_loss"])
                    except Exception as e:
                        logger.warning("Phase detection failed for %s: %s", theme, e)

                if pnl_pct <= -stop_loss and not should_exit:
                    should_exit = True
                    reason = "stop_loss"

        if should_exit:
            pos["exit_reason"] = reason
            pos["exit_date"] = today
            exits.append(pos)
        else:
            remaining.append(pos)

    state["positions"] = remaining
    state["closed"].extend(exits)
    return exits


def format_signal_report(scan_results: list[dict], phase_signals: list[dict],
                         state: dict, today: str) -> str:
    """Format signal report for terminal output."""
    lines = [
        f"\n오늘의 KMS 신호 — {today}",
        "═" * 65,
    ]

    # Current positions (HOLD)
    for pos in state["positions"]:
        hold_days = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
        pnl = pos.get("pnl_pct", 0)
        phase = pos.get("phase", "?")
        lines.append(
            f"  ⏳ HOLD   {pos['theme']:<10s}  {pos['etf_name']} ({pos['etf_code']})  "
            f"진입 {hold_days}일 / {pnl:+.1%}  [{phase}]"
        )

    # Phase signals
    held_themes = {p["theme"] for p in state["positions"]}
    for sig in phase_signals:
        theme = sig["theme"]
        if theme in held_themes:
            continue

        phase = sig["phase"]
        action = sig["action"]
        ratio = sig["metrics"]["ratio"]
        roc = sig["metrics"]["roc"]

        if action == BUY:
            etf_info = f"  {sig.get('etf_name', '')} ({sig.get('etf_code', '')})" if sig.get("etf_code") else ""
            lines.append(
                f"  ✅ BUY    {theme:<10s}{etf_info}  "
                f"검색 {ratio:.1f}x / roc {roc:+.2f}  [{phase}]"
            )
        elif action == WATCH:
            lines.append(
                f"  👀 WATCH  {theme:<10s}  검색 {ratio:.1f}x / roc {roc:+.2f}  [{phase}]"
            )

    # Surge alerts (unmapped manias)
    surges = [s for s in scan_results if s.get("alert")]
    if surges:
        lines.append("")
        lines.append("  ⚠️  UNMAPPED MANIA ALERTS:")
        for s in surges:
            lines.append(
                f"     {s['theme']:<10s}  검색 {s['metrics']['ratio']:.1f}x  [{s['category']}]"
            )

    lines.append("═" * 65)
    return "\n".join(lines)


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    params = DEFAULT_PARAMS.copy()

    # Fetch recent ETF data (last 60 trading days is enough for MA20)
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    logger.info("Fetching ETF data...")
    try:
        etf_data = fetch_all_etfs(ETF_UNIVERSE, start, today)
    except Exception as e:
        logger.error("Fatal: ETF data fetch failed: %s", e)
        state = load_positions()
        send_error_alert(str(e), today, len(state.get("positions", [])))
        return

    # Load/update trend data
    logger.info("Loading trend data...")
    trend_data = load_all_trend_cache()
    if not trend_data:
        logger.info("  No cached trend data. Attempting fetch...")
        try:
            fetch_all_trends()
            trend_data = load_all_trend_cache()
        except Exception as e:
            logger.warning("Trend fetch failed: %s — continuing with volume-only", e)

    # Load position state
    state = load_positions()

    # Update current prices for held positions
    for pos in state["positions"]:
        if pos["etf_code"] in etf_data:
            df = etf_data[pos["etf_code"]]
            price = get_latest_price(df, today)
            if price is not None:
                pos["current_price"] = price
                pos["pnl_pct"] = (price / pos["entry_price"]) - 1

    # Check exits (lifecycle-aware)
    exits = check_exits(state, etf_data, trend_data, today, params)
    if exits:
        logger.info("  청산 신호: %d건", len(exits))
        for ex in exits:
            logger.info("    EXIT  %s  %s  (%s)", ex["theme"], ex["etf_name"], ex["exit_reason"])
            log_accuracy(ex)

    # Scan all themes for surges
    logger.info("Scanning themes...")
    scan_results = scan_all_themes(trend_data, today,
                                    lookback_weeks=params["search_lookback_weeks"],
                                    recent_weeks=params["search_recent_weeks"])
    surges = detect_surges(trend_data, today,
                           lookback_weeks=params["search_lookback_weeks"],
                           recent_weeks=params["search_recent_weeks"])

    # Compute lifecycle phase + action for tradeable themes
    phase_signals = []
    held_themes = {p["theme"] for p in state["positions"]}
    held_etf_codes = {p["etf_code"] for p in state["positions"]}  # for dedup check

    for theme, instruments in ETF_UNIVERSE.items():
        if theme in held_themes:
            continue

        if theme in trend_data:
            codes = [inst["code"] for inst in instruments]
            # Get first available ETF for price divergence
            etf_df = None
            for c in codes:
                if c in etf_data:
                    etf_df = etf_data[c]
                    break

            try:
                phase_result = detect_phase(
                    trend_data[theme], today,
                    etf_df=etf_df,
                    lookback_weeks=params["search_lookback_weeks"],
                    recent_weeks=params["search_recent_weeks"],
                    search_threshold=params["search_threshold"],
                )
            except Exception as e:
                logger.warning("Phase detection failed for %s: %s", theme, e)
                continue

            action = get_action(phase_result["phase"], holding=False)

            # Pick best ETF if actionable
            etf_code, etf_name = "", ""
            if action == BUY:
                best_code, vol_sig = pick_best_etf(
                    etf_data, codes, today,
                    vol_threshold=params["vol_threshold"],
                )
                if best_code:
                    # Dedup check: skip if this ETF is already held under another theme
                    if best_code in held_etf_codes:
                        logger.info("  Skipping %s — ETF %s already held", theme, best_code)
                        continue
                    etf_code = best_code
                    etf_name = {inst["code"]: inst["name"] for inst in instruments}.get(best_code, "")

            phase_signals.append({
                "theme": theme,
                "phase": phase_result["phase"],
                "action": action,
                "metrics": phase_result["metrics"],
                "confidence": phase_result["confidence"],
                "etf_code": etf_code,
                "etf_name": etf_name,
            })

    # Sort: BUY first, then WATCH, then others
    action_order = {BUY: 0, WATCH: 1}
    phase_signals.sort(key=lambda s: (action_order.get(s["action"], 9), -s["metrics"]["ratio"]))

    # Print report
    logger.info(format_signal_report(scan_results, phase_signals, state, today))

    # Record new BUY entries in position state
    max_pos = params["max_positions"]
    new_buys = []
    for sig in phase_signals:
        if sig["action"] == BUY and sig["theme"] not in held_themes:
            if len(state["positions"]) >= max_pos:
                break
            if sig["etf_code"] and sig["etf_code"] in etf_data:
                # Dedup: also check against newly added positions in this run
                if sig["etf_code"] in held_etf_codes:
                    continue
                df = etf_data[sig["etf_code"]]
                entry_price = get_latest_price(df, today)
                if entry_price is not None:
                    state["positions"].append({
                        "theme": sig["theme"],
                        "etf_code": sig["etf_code"],
                        "etf_name": sig["etf_name"],
                        "entry_date": today,
                        "entry_price": entry_price,
                        "entry_phase": sig["phase"],
                    })
                    held_themes.add(sig["theme"])
                    held_etf_codes.add(sig["etf_code"])
                    new_buys.append(sig)

    save_positions(state)
    logger.info("  포지션 상태 저장: %s", POSITIONS_FILE)

    # Telegram notification
    buy_signals = [s for s in phase_signals if s["action"] == BUY and s in new_buys]
    watch_signals = [s for s in phase_signals if s["action"] == WATCH]
    unmapped_alerts = [s for s in scan_results if s.get("alert")]
    next_monday = (datetime.now() + timedelta(days=(7 - datetime.now().weekday()) % 7 or 7))
    next_run = next_monday.strftime("%m/%d(%a) 08:30")

    send_signal_report(
        buy_signals=buy_signals,
        exit_signals=exits,
        positions=state["positions"],
        watch_signals=watch_signals,
        unmapped_alerts=unmapped_alerts,
        today=today,
        next_run=next_run,
    )


if __name__ == "__main__":
    main()
