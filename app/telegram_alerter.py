import asyncio
import httpx
from datetime import datetime
from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED


async def send_telegram_alert(event: dict) -> bool:
    """Send an intrusion alert via Telegram."""
    if not TELEGRAM_ENABLED:
        return False

    reason_labels = {
        "suspicious_path": "🔍 Suspicious Path",
        "sql_injection": "💉 SQL Injection",
        "rate_limit": "⚡ Rate Limit",
        "auth_failures": "🔐 Auth Failures",
    }

    reason = event.get("reason", "unknown")
    label = reason_labels.get(reason, reason)
    timestamp = event.get("timestamp", datetime.utcnow())
    if isinstance(timestamp, datetime):
        timestamp = timestamp.strftime("%d.%m.%Y %H:%M:%S")

    status_code = event.get("status_code", "-")
    host = event.get("host", "-")
    recommendation = event.get("recommendation", "")

    message = (
        f"<b>🚨 Traefik Intruder Alert</b>\n"
        f"{'─' * 25}\n\n"
        f"<b>Type:</b> {label}\n"
        f"<b>IP:</b> <code>{event.get('ip', 'unknown')}</code>\n"
        f"<b>Host:</b> {host}\n"
        f"<b>Status:</b> {status_code}\n"
        f"<b>Time:</b> {timestamp}\n"
        f"<b>Details:</b> {event.get('details', 'N/A')}\n"
    )

    if event.get("request_count"):
        message += f"<b>Requests:</b> {event['request_count']}\n"

    if recommendation:
        message += f"\n<b>💡 Empfehlung:</b>\n<i>{recommendation}</i>\n"

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
