"""
IP Blocklist Management with CIDR support and ipset integration.
"""
import ipaddress
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.database import BlockedIP
from app.auto_reporter import report_ip_sync


# Block duration based on threat level (in hours)
BLOCK_DURATIONS = {
    "rate_limit": 24,           # 1 day
    "suspicious_path": 168,     # 7 days
    "sql_injection": 720,       # 30 days
    "auth_failures": 72,        # 3 days
    "high_abuse_score": None,   # Permanent (score > 80)
    "repeat_offender": None,    # Permanent (3+ blocks)
    "manual": None,             # Permanent by default
}

# AbuseIPDB thresholds
ABUSE_SCORE_AUTO_BLOCK = 50      # Auto-block if score >= 50%
ABUSE_SCORE_PERMANENT = 80       # Permanent block if score >= 80%
REPEAT_OFFENDER_THRESHOLD = 3    # Permanent after 3 blocks


def parse_ip_or_cidr(ip_str: str) -> tuple[bool, Optional[ipaddress.IPv4Network | ipaddress.IPv6Network | ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    """
    Parse an IP address or CIDR notation.
    Returns (is_cidr, parsed_object) or (False, None) if invalid.
    """
    try:
        if '/' in ip_str:
            network = ipaddress.ip_network(ip_str, strict=False)
            return True, network
        else:
            addr = ipaddress.ip_address(ip_str)
            return False, addr
    except ValueError:
        return False, None


def is_ip_in_cidr(ip: str, cidr: str) -> bool:
    """Check if an IP address is within a CIDR range."""
    try:
        ip_addr = ipaddress.ip_address(ip)
        network = ipaddress.ip_network(cidr, strict=False)
        return ip_addr in network
    except ValueError:
        return False


def is_ip_blocked_by_cidr(db: Session, ip: str) -> Optional[BlockedIP]:
    """
    Check if an IP is covered by an existing CIDR block.
    Returns the blocking CIDR entry if found, None otherwise.
    """
    cidr_blocks = db.query(BlockedIP).filter(
        BlockedIP.active == 1,
        BlockedIP.is_cidr == 1
    ).all()

    for cidr_block in cidr_blocks:
        if is_ip_in_cidr(ip, cidr_block.ip):
            return cidr_block

    return None


def get_block_duration(reason: str, abuse_score: Optional[int] = None) -> Optional[timedelta]:
    """
    Get the block duration based on reason and abuse score.
    Returns None for permanent blocks.
    """
    # High abuse score = permanent
    if abuse_score and abuse_score >= ABUSE_SCORE_PERMANENT:
        return None

    # Map reason to duration
    reason_key = reason.lower().replace(" ", "_").replace("-", "_")

    # Check for known reason patterns
    if "sql" in reason_key or "injection" in reason_key:
        hours = BLOCK_DURATIONS["sql_injection"]
    elif "rate" in reason_key or "limit" in reason_key:
        hours = BLOCK_DURATIONS["rate_limit"]
    elif "auth" in reason_key or "failure" in reason_key:
        hours = BLOCK_DURATIONS["auth_failures"]
    elif "suspicious" in reason_key or "path" in reason_key:
        hours = BLOCK_DURATIONS["suspicious_path"]
    else:
        hours = BLOCK_DURATIONS.get(reason_key, BLOCK_DURATIONS["manual"])

    if hours is None:
        return None
    return timedelta(hours=hours)


def should_be_permanent(db: Session, ip: str, abuse_score: Optional[int] = None) -> bool:
    """
    Determine if an IP should be permanently blocked.
    """
    # High abuse score
    if abuse_score and abuse_score >= ABUSE_SCORE_PERMANENT:
        return True

    # Check if repeat offender
    existing = db.query(BlockedIP).filter(BlockedIP.ip == ip).first()
    if existing and existing.block_count >= REPEAT_OFFENDER_THRESHOLD:
        return True

    return False


def block_ip(
    db: Session,
    ip: str,
    reason: str = None,
    abuse_score: Optional[int] = None,
    auto_blocked: bool = False,
    duration_hours: Optional[int] = None
) -> dict:
    """
    Block an IP or CIDR range with smart duration handling.

    Returns dict with success status and details.
    """
    # Validate and parse IP/CIDR
    is_cidr, parsed = parse_ip_or_cidr(ip)
    if parsed is None:
        return {"error": "Invalid IP or CIDR format", "success": False}

    # Normalize the IP/CIDR string
    ip = str(parsed)

    # For single IPs, check if already covered by CIDR
    if not is_cidr:
        cidr_block = is_ip_blocked_by_cidr(db, ip)
        if cidr_block:
            return {
                "error": f"IP already blocked by CIDR range {cidr_block.ip}",
                "covered_by": cidr_block.ip,
                "success": False
            }

    # Check if already blocked
    existing = db.query(BlockedIP).filter(BlockedIP.ip == ip).first()

    if existing and existing.active == 1:
        return {"error": "IP already blocked", "id": existing.id, "success": False}

    # Calculate block duration
    if duration_hours is not None:
        # Explicit duration provided
        blocked_until = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours > 0 else None
    elif should_be_permanent(db, ip, abuse_score):
        blocked_until = None  # Permanent
    else:
        duration = get_block_duration(reason or "manual", abuse_score)
        blocked_until = datetime.utcnow() + duration if duration else None

    if existing:
        # Reactivate existing block
        existing.active = 1
        existing.blocked_at = datetime.utcnow()
        existing.blocked_until = blocked_until
        existing.reason = reason or existing.reason
        existing.block_count += 1
        existing.abuse_score = abuse_score
        existing.auto_blocked = 1 if auto_blocked else 0
        db.commit()

        # Check if now a repeat offender (make permanent)
        if existing.block_count >= REPEAT_OFFENDER_THRESHOLD and existing.blocked_until:
            existing.blocked_until = None
            existing.reason = f"{existing.reason} [Repeat offender - permanent]"
            db.commit()

        write_blocklist_file(db)

        # Auto-report to AbuseIPDB for repeat offenders
        report_result = None
        if not is_cidr:
            report_reason = f"{reason or 'Reactivated block'} (Block #{existing.block_count})"
            report_result = report_ip_sync(ip, report_reason)

        return {
            "success": True,
            "id": existing.id,
            "ip": ip,
            "reactivated": True,
            "block_count": existing.block_count,
            "permanent": existing.blocked_until is None,
            "auto_reported": report_result is not None and not report_result.get("skipped")
        }

    # Create new block
    blocked = BlockedIP(
        ip=ip,
        reason=reason,
        blocked_until=blocked_until,
        is_cidr=1 if is_cidr else 0,
        abuse_score=abuse_score,
        auto_blocked=1 if auto_blocked else 0,
    )
    db.add(blocked)
    db.commit()

    write_blocklist_file(db)

    # Auto-report to AbuseIPDB (non-blocking)
    report_result = None
    if not is_cidr:
        report_result = report_ip_sync(ip, reason or "Malicious activity")

    return {
        "success": True,
        "id": blocked.id,
        "ip": ip,
        "is_cidr": is_cidr,
        "permanent": blocked_until is None,
        "expires": blocked_until.isoformat() if blocked_until else None,
        "auto_reported": report_result is not None and not report_result.get("skipped")
    }


def unblock_ip(db: Session, ip: str) -> dict:
    """Unblock an IP or CIDR range."""
    blocked = db.query(BlockedIP).filter(BlockedIP.ip == ip, BlockedIP.active == 1).first()
    if not blocked:
        return {"error": "IP not found in blocklist", "success": False}

    blocked.active = 0
    db.commit()

    write_blocklist_file(db)

    return {"success": True, "ip": ip}


def cleanup_expired_blocks(db: Session) -> int:
    """
    Remove expired blocks.
    Returns the number of blocks removed.
    """
    now = datetime.utcnow()

    expired = db.query(BlockedIP).filter(
        BlockedIP.active == 1,
        BlockedIP.blocked_until.isnot(None),
        BlockedIP.blocked_until <= now
    ).all()

    count = 0
    for block in expired:
        block.active = 0
        count += 1

    if count > 0:
        db.commit()
        write_blocklist_file(db)

    return count


def get_blocklist_for_ipset(db: Session) -> tuple[list[str], list[str]]:
    """
    Get blocklist formatted for ipset.
    Returns (single_ips, cidr_ranges).
    """
    blocks = db.query(BlockedIP).filter(BlockedIP.active == 1).all()

    single_ips = []
    cidr_ranges = []

    for block in blocks:
        if block.is_cidr:
            cidr_ranges.append(block.ip)
        else:
            single_ips.append(block.ip)

    return single_ips, cidr_ranges


def write_blocklist_file(db: Session):
    """Write blocklist to JSON file for external sync."""
    blocks = db.query(BlockedIP).filter(BlockedIP.active == 1).all()

    blocklist = []
    for b in blocks:
        blocklist.append({
            "ip": b.ip,
            "reason": b.reason,
            "is_cidr": bool(b.is_cidr),
            "blocked_until": b.blocked_until.isoformat() if b.blocked_until else None,
            "abuse_score": b.abuse_score,
        })

    blocklist_path = "/app/data/blocklist.json"
    with open(blocklist_path, "w") as f:
        json.dump(blocklist, f, indent=2)


def write_ipset_restore_file(db: Session) -> str:
    """
    Write ipset restore file for efficient bulk loading.
    Returns the file path.
    """
    single_ips, cidr_ranges = get_blocklist_for_ipset(db)

    content = []

    # Create hash:ip set for single IPs
    content.append("create blocklist_ips hash:ip family inet hashsize 4096 maxelem 65536 -exist")
    for ip in single_ips:
        content.append(f"add blocklist_ips {ip}")

    # Create hash:net set for CIDR ranges
    content.append("create blocklist_nets hash:net family inet hashsize 1024 maxelem 65536 -exist")
    for cidr in cidr_ranges:
        content.append(f"add blocklist_nets {cidr}")

    ipset_path = "/app/data/blocklist.ipset"
    with open(ipset_path, "w") as f:
        f.write("\n".join(content))

    return ipset_path
