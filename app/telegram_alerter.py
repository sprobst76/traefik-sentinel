import asyncio
import httpx
from datetime import datetime
from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED


# Severity classification is owned by app.alert_router (D-01).
# Import THREAT_SEVERITY + get_severity from the router; this module is a dumb sender.
from app.alert_router import THREAT_SEVERITY, get_severity


def get_severity_header(reason: str, event: dict) -> str:
    """Generate severity-based alert header. Delegates severity to alert_router."""
    severity = get_severity(reason, event)
    headers = {
        "critical": "🔴🔴🔴 CRITICAL THREAT DETECTED 🔴🔴🔴",
        "high": "🟠🟠 HIGH SEVERITY ALERT 🟠🟠",
        "medium": "🟡 Security Alert",
    }
    return headers.get(severity, headers["medium"])


async def send_telegram_alert(event: dict) -> bool:
    """Send an intrusion alert via Telegram."""
    if not TELEGRAM_ENABLED:
        return False

    reason_labels = {
        "suspicious_path": "🔍 Suspicious Path Scan",
        "sql_injection": "💉 SQL INJECTION ATTACK",
        "rate_limit": "⚡ Rate Limit Exceeded",
        "auth_failures": "🔐 Brute Force Attempt",
        "honeypot": "🍯 HONEYPOT TRIGGERED",
    }

    reason = event.get("reason", "unknown")
    label = reason_labels.get(reason, reason)
    timestamp = event.get("timestamp", datetime.utcnow())
    if isinstance(timestamp, datetime):
        timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    status_code = event.get("status_code", "-")
    host = event.get("host", "-")
    recommendation = event.get("recommendation", "")
    request_count = event.get("request_count", 1)

    # Get severity header
    header = get_severity_header(reason, event)

    # Build message with threat-appropriate urgency
    message = f"<b>{header}</b>\n"
    message += f"{'═' * 30}\n\n"

    message += f"<b>🎯 Threat Type:</b> {label}\n"
    message += f"<b>🌐 Attacker IP:</b> <code>{event.get('ip', 'unknown')}</code>\n"

    if event.get("country"):
        message += f"<b>📍 Location:</b> {event.get('flag', '')} {event.get('country', 'Unknown')}\n"

    message += f"<b>🎪 Target Host:</b> {host}\n"
    message += f"<b>📊 Status Code:</b> {status_code}\n"
    message += f"<b>🕐 Time:</b> {timestamp}\n"

    if request_count > 1:
        message += f"<b>📈 Request Count:</b> <b>{request_count}</b>\n"

    message += f"\n<b>📝 Details:</b>\n<code>{event.get('details', 'N/A')}</code>\n"

    # Add blocking status
    if event.get("auto_blocked"):
        message += f"\n<b>✅ ACTION TAKEN:</b> IP automatically blocked\n"
    elif event.get("is_blocked"):
        message += f"\n<b>ℹ️ Status:</b> IP already blocked\n"

    if recommendation:
        message += f"\n<b>💡 Recommendation:</b>\n<i>{recommendation}</i>\n"

    # Add footer for critical threats
    severity = get_severity(reason, event)
    if severity == "critical" or request_count > 20:
        message += f"\n{'─' * 30}\n"
        message += f"<i>⚠️ Immediate review recommended</i>"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            return response.status_code == 200
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False


def send_alert_sync(event: dict) -> bool:
    """Synchronous wrapper for sending alerts."""
    try:
        return asyncio.run(send_telegram_alert(event))
    except RuntimeError:
        # If there's already an event loop running
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(send_telegram_alert(event))


async def send_alert(message: str, parse_mode: str = "Markdown") -> bool:
    """Send a custom message via Telegram."""
    if not TELEGRAM_ENABLED:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            return response.status_code == 200
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        return False
