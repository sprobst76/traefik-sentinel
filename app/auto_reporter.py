"""
Auto-report blocked IPs to AbuseIPDB.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from app.config import ABUSEIPDB_AUTO_REPORT, ABUSEIPDB_REPORT_COOLDOWN_MINUTES
from app.abuseipdb import report_ip, is_configured as abuseipdb_configured

# Cache for recent reports to avoid duplicate reporting
_report_cache: dict[str, datetime] = {}

# Map our internal reasons to AbuseIPDB categories
REASON_TO_CATEGORIES = {
    "sql_injection": ["web_app_attack", "hacking"],
    "suspicious_path": ["web_app_attack", "bad_web_bot"],
    "rate_limit": ["brute_force", "bad_web_bot"],
    "auth_failures": ["brute_force", "hacking"],
    "honeypot": ["web_app_attack", "hacking", "bad_web_bot"],
    "scanner": ["port_scan", "bad_web_bot"],
    "default": ["web_app_attack", "hacking"],
}


def _get_categories_for_reason(reason: str) -> list[str]:
    """Get AbuseIPDB categories based on block reason."""
    reason_lower = reason.lower()

    if "sql" in reason_lower or "injection" in reason_lower:
        return REASON_TO_CATEGORIES["sql_injection"]
    elif "honeypot" in reason_lower:
        return REASON_TO_CATEGORIES["honeypot"]
    elif "rate" in reason_lower or "limit" in reason_lower:
        return REASON_TO_CATEGORIES["rate_limit"]
    elif "auth" in reason_lower or "login" in reason_lower or "brute" in reason_lower:
        return REASON_TO_CATEGORIES["auth_failures"]
    elif "scan" in reason_lower:
        return REASON_TO_CATEGORIES["scanner"]
    elif "suspicious" in reason_lower or "path" in reason_lower:
        return REASON_TO_CATEGORIES["suspicious_path"]
    else:
        return REASON_TO_CATEGORIES["default"]


def _should_report(ip: str) -> bool:
    """Check if we should report this IP (cooldown check)."""
    if ip in _report_cache:
        last_report = _report_cache[ip]
        cooldown = timedelta(minutes=ABUSEIPDB_REPORT_COOLDOWN_MINUTES)
        if datetime.utcnow() - last_report < cooldown:
            return False
    return True


def _mark_reported(ip: str):
    """Mark an IP as recently reported."""
    _report_cache[ip] = datetime.utcnow()


def _cleanup_cache():
    """Remove old entries from report cache."""
    now = datetime.utcnow()
    cooldown = timedelta(minutes=ABUSEIPDB_REPORT_COOLDOWN_MINUTES)
    expired = [ip for ip, t in _report_cache.items() if now - t >= cooldown]
    for ip in expired:
        del _report_cache[ip]


async def auto_report_ip(
    ip: str,
    reason: str,
    details: str = None,
    event_count: int = 1
) -> Optional[dict]:
    """
    Automatically report an IP to AbuseIPDB.

    Args:
        ip: The IP address to report
        reason: The reason for blocking (used to determine categories)
        details: Additional details about the attack
        event_count: Number of events/attacks from this IP

    Returns:
        Report result dict or None if not reported
    """
    # Check if auto-report is enabled
    if not ABUSEIPDB_AUTO_REPORT:
        return None

    # Check if AbuseIPDB is configured
    if not abuseipdb_configured():
        return None

    # Don't report CIDR ranges
    if '/' in ip:
        return None

    # Check cooldown
    if not _should_report(ip):
        return {"skipped": True, "reason": "cooldown"}

    # Get categories based on reason
    categories = _get_categories_for_reason(reason)

    # Build comment
    comment_parts = [f"Blocked by Traefik Dashboard"]
    if reason:
        comment_parts.append(f"Reason: {reason}")
    if event_count > 1:
        comment_parts.append(f"Events: {event_count}")
    if details:
        # Truncate long details
        details_truncated = details[:200] if len(details) > 200 else details
        comment_parts.append(f"Details: {details_truncated}")

    comment = ". ".join(comment_parts)

    # Report to AbuseIPDB
    try:
        result = await report_ip(ip, categories, comment)

        if result and result.get("success"):
            _mark_reported(ip)
            print(f"Auto-reported to AbuseIPDB: {ip} (categories: {categories})")
        elif result and result.get("error"):
            # Don't spam logs for expected errors like "already reported"
            if "already reported" not in result.get("error", "").lower():
                print(f"AbuseIPDB report failed for {ip}: {result.get('error')}")

        return result
    except Exception as e:
        print(f"Auto-report error for {ip}: {e}")
        return {"error": str(e)}


def report_ip_sync(ip: str, reason: str, details: str = None, event_count: int = 1) -> Optional[dict]:
    """
    Synchronous wrapper for auto_report_ip.
    Schedules the report in the background.
    """
    if not ABUSEIPDB_AUTO_REPORT or not abuseipdb_configured():
        return None

    if '/' in ip:
        return None

    if not _should_report(ip):
        return {"skipped": True, "reason": "cooldown"}

    try:
        loop = asyncio.get_running_loop()
        # Schedule as background task
        asyncio.create_task(auto_report_ip(ip, reason, details, event_count))
        return {"scheduled": True}
    except RuntimeError:
        # No running loop, run directly
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(auto_report_ip(ip, reason, details, event_count))
            return result
        except Exception as e:
            print(f"Sync report error: {e}")
            return {"error": str(e)}
