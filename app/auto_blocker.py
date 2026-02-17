"""
Automatic IP blocking based on AbuseIPDB scores, threat patterns, and honeypots.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from app.database import SessionLocal, IntruderEvent, BlockedIP
from app.blocklist import (
    block_ip,
    is_ip_blocked_by_cidr,
    ABUSE_SCORE_AUTO_BLOCK,
    ABUSE_SCORE_PERMANENT,
)
from app.abuseipdb import check_ip, is_configured as abuseipdb_configured
from app.config import HONEYPOT_PATHS, HONEYPOT_INSTANT_BLOCK, WHITELISTED_IPS


# Cache for recent checks to avoid hitting API rate limits
_abuse_check_cache: dict[str, tuple[datetime, dict]] = {}
CACHE_TTL_MINUTES = 60

# Reasons that warrant immediate AbuseIPDB check
HIGH_PRIORITY_REASONS = {"sql_injection", "suspicious_path"}

# Minimum events before auto-checking
MIN_EVENTS_FOR_CHECK = 2


async def should_auto_block(ip: str, reason: str, event_count: int = 1) -> tuple[bool, Optional[int], str]:
    """
    Determine if an IP should be automatically blocked.

    Returns: (should_block, abuse_score, block_reason)
    """
    if not abuseipdb_configured():
        return False, None, ""

    # Check cache first
    if ip in _abuse_check_cache:
        cache_time, cached_result = _abuse_check_cache[ip]
        if datetime.utcnow() - cache_time < timedelta(minutes=CACHE_TTL_MINUTES):
            abuse_score = cached_result.get("abuse_score", 0)
            if abuse_score >= ABUSE_SCORE_AUTO_BLOCK:
                return True, abuse_score, f"AbuseIPDB score {abuse_score}% (cached)"
            return False, abuse_score, ""

    # Decide if we should check AbuseIPDB
    should_check = False

    # High priority reasons always check
    if reason in HIGH_PRIORITY_REASONS:
        should_check = True

    # Multiple events trigger check
    if event_count >= MIN_EVENTS_FOR_CHECK:
        should_check = True

    if not should_check:
        return False, None, ""

    # Check AbuseIPDB
    result = await check_ip(ip)

    if result and "error" not in result:
        # Cache the result
        _abuse_check_cache[ip] = (datetime.utcnow(), result)

        abuse_score = result.get("abuse_score", 0)
        total_reports = result.get("total_reports", 0)

        if abuse_score >= ABUSE_SCORE_AUTO_BLOCK:
            return True, abuse_score, f"AbuseIPDB: {abuse_score}% score, {total_reports} reports"

    return False, result.get("abuse_score") if result else None, ""


async def process_intruder_event(event: dict) -> Optional[dict]:
    """
    Process an intruder event and potentially auto-block.

    Returns block result if blocked, None otherwise.
    """
    ip = event.get("ip")
    reason = event.get("reason")

    if not ip or not reason:
        return None

    db = SessionLocal()
    try:
        # Check if already blocked
        from app.database import BlockedIP
        existing = db.query(BlockedIP).filter(
            BlockedIP.ip == ip,
            BlockedIP.active == 1
        ).first()

        if existing:
            return None

        # Check if covered by CIDR
        if is_ip_blocked_by_cidr(db, ip):
            return None

        # Count recent events for this IP
        since = datetime.utcnow() - timedelta(hours=24)
        event_count = db.query(IntruderEvent).filter(
            IntruderEvent.ip == ip,
            IntruderEvent.timestamp >= since
        ).count()

        # Check if should auto-block
        should_block, abuse_score, block_reason = await should_auto_block(ip, reason, event_count)

        if should_block:
            result = block_ip(
                db=db,
                ip=ip,
                reason=f"Auto-blocked: {block_reason}",
                abuse_score=abuse_score,
                auto_blocked=True
            )

            if result.get("success"):
                # Send notification
                await notify_auto_block(ip, abuse_score, block_reason, event_count)
                return result

        return None
    finally:
        db.close()


async def notify_auto_block(ip: str, abuse_score: int, reason: str, event_count: int):
    """Send notification about auto-blocked IP."""
    try:
        from app.telegram_alerter import send_alert

        message = (
            f"🚫 *Auto-Blocked IP*\n\n"
            f"IP: `{ip}`\n"
            f"AbuseIPDB Score: {abuse_score}%\n"
            f"Events (24h): {event_count}\n"
            f"Reason: {reason}\n"
        )

        if abuse_score >= ABUSE_SCORE_PERMANENT:
            message += "\n⚠️ *Permanent block* (score ≥80%)"

        await send_alert(message)
    except Exception as e:
        print(f"Failed to send auto-block notification: {e}")


def cleanup_cache():
    """Remove expired cache entries."""
    now = datetime.utcnow()
    expired = [
        ip for ip, (cache_time, _) in _abuse_check_cache.items()
        if now - cache_time >= timedelta(minutes=CACHE_TTL_MINUTES)
    ]
    for ip in expired:
        del _abuse_check_cache[ip]


def is_honeypot_path(path: str) -> bool:
    """Check if the path matches a honeypot pattern."""
    path_lower = path.lower()
    for honeypot in HONEYPOT_PATHS:
        if path_lower.startswith(honeypot.lower()):
            return True
    return False


def check_and_block_honeypot(ip: str, path: str, host: str = None) -> Optional[dict]:
    """
    Check if path is a honeypot and instantly block the IP.

    Returns block result if blocked, None otherwise.
    """
    if not HONEYPOT_INSTANT_BLOCK:
        return None

    # Don't block whitelisted IPs
    if ip in WHITELISTED_IPS:
        return None

    # Check if honeypot path
    if not is_honeypot_path(path):
        return None

    db = SessionLocal()
    try:
        # Check if already blocked
        existing = db.query(BlockedIP).filter(
            BlockedIP.ip == ip,
            BlockedIP.active == 1
        ).first()

        if existing:
            return None

        # Check if covered by CIDR
        if is_ip_blocked_by_cidr(db, ip):
            return None

        # INSTANT BLOCK
        result = block_ip(
            db=db,
            ip=ip,
            reason=f"Honeypot: {path[:100]}",
            abuse_score=None,
            auto_blocked=True
        )

        if result.get("success"):
            # Send notification
            try:
                from app.telegram_alerter import send_alert_sync
                message = (
                    f"🍯 *Honeypot Block*\n\n"
                    f"IP: `{ip}`\n"
                    f"Path: `{path[:80]}`\n"
                    f"Host: {host or '-'}\n\n"
                    f"⚡ Sofort blockiert!"
                )
                # Use sync version since we're in sync context
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(_send_honeypot_alert(ip, path, host))
                    else:
                        pass  # Skip notification in sync context
                except:
                    pass
            except Exception as e:
                print(f"Honeypot notification failed: {e}")

            return result

        return None
    finally:
        db.close()


async def _send_honeypot_alert(ip: str, path: str, host: str = None):
    """Send honeypot block notification."""
    try:
        from app.telegram_alerter import send_alert
        message = (
            f"🍯 *Honeypot Block*\n\n"
            f"IP: `{ip}`\n"
            f"Path: `{path[:80]}`\n"
            f"Host: {host or '-'}\n\n"
            f"⚡ Sofort blockiert!"
        )
        await send_alert(message)
    except Exception as e:
        print(f"Honeypot alert failed: {e}")
