"""Telegram notification — fire-and-forget.

Never raises exceptions to the caller. All errors are logged and swallowed.
"""

import os
import requests
from kms_logger import logger

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram credentials not set — skipping notification")
        return False

    try:
        resp = requests.post(
            _API_URL.format(token=TELEGRAM_BOT_TOKEN),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Telegram API error %d: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except requests.exceptions.Timeout:
        logger.warning("Telegram API timeout")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning("Telegram API error: %s", e)
        return False
    except Exception as e:
        logger.warning("Unexpected Telegram error: %s", e)
        return False


def send_signal_report(
    buy_signals: list[dict],
    exit_signals: list[dict],
    positions: list[dict],
    watch_signals: list[dict],
    unmapped_alerts: list[dict],
    today: str,
    next_run: str = "",
) -> bool:
    """Send the weekly 3-section Telegram report.

    Section 1: ACTION REQUIRED (BUY/EXIT)
    Section 2: PORTFOLIO STATUS (held positions)
    Section 3: WATCH (themes approaching threshold)
    """
    lines = [f"📊 KMS 주간 리포트 — {today}"]

    # Section 1: ACTION REQUIRED
    has_actions = buy_signals or exit_signals
    if has_actions:
        lines.append("")
        lines.append("🔴 ACTION REQUIRED")
        for sig in buy_signals:
            lines.append(
                f"✅ BUY  {sig['theme']}  {sig.get('etf_name', '')}\n"
                f"   검색 {sig['metrics']['ratio']:.1f}x / roc {sig['metrics']['roc']:+.2f}  [{sig['phase']}]"
            )
        for ex in exit_signals:
            reason_kr = {
                "stop_loss": "손절",
                "time_exit": "보유기간 만료",
            }.get(ex.get("exit_reason", ""), ex.get("exit_reason", ""))
            pnl = ex.get("pnl_pct", 0)
            lines.append(f"❌ EXIT  {ex['theme']}  {ex.get('etf_name', '')}  ({reason_kr}, {pnl:+.1%})")
    else:
        lines.append("")
        lines.append("✅ 이상 없음 — 신규 신호 없음")

    # Section 2: PORTFOLIO STATUS
    if positions:
        lines.append("")
        lines.append(f"📦 PORTFOLIO ({len(positions)}/5 포지션)")
        for pos in positions:
            import pandas as pd
            hold_days = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pnl = pos.get("pnl_pct", 0)
            phase = pos.get("phase", "?")
            lines.append(f"⏳ {pos['theme']}  {pnl:+.1%}  {hold_days}일차  [{phase}]")

    # Section 3: WATCH
    if watch_signals:
        lines.append("")
        lines.append("👀 WATCH")
        for sig in watch_signals[:5]:
            lines.append(
                f"  {sig['theme']}  검색 {sig['metrics']['ratio']:.1f}x  [{sig['phase']}]"
            )

    # Unmapped mania alerts
    if unmapped_alerts:
        lines.append("")
        lines.append("⚠️ UNMAPPED MANIA")
        for alert in unmapped_alerts[:3]:
            lines.append(f"  {alert['theme']}  검색 {alert['metrics']['ratio']:.1f}x")

    # Footer
    if next_run:
        lines.append("")
        lines.append(f"다음 실행: {next_run}")

    return _send("\n".join(lines))


def send_error_alert(error_msg: str, today: str, num_positions: int = 0) -> bool:
    """Send error notification when the system fails."""
    text = (
        f"⚠️ KMS 실행 오류 — {today}\n\n"
        f"데이터 수집 실패: {error_msg}\n"
        f"수동 확인 필요: python run.py\n\n"
        f"📦 기존 포지션은 변경 없음 ({num_positions}건 보유 중)"
    )
    return _send(text)
