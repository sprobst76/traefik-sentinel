"""Digest pipeline — aggregates unsent digest_events into a single Telegram message.

Phase 2 scope: library module only. Assembles an HTML-escaped, size-bounded
Telegram digest from `digest_events` rows whose `sent_at IS NULL`, sends via
`telegram_alerter.send_alert`, and batch-stamps `sent_at` only after Telegram
returns HTTP 200 (D-18).

Phase 3 will wire a scheduler that `await send_digest()` directly.
"""

import html
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, func

from app.database import (
    AccessLog,
    BlockedIP,
    DigestEvent,
    IntruderEvent,
    SessionLocal,
)
from app.geoip import lookup_batch
from app.telegram_alerter import send_alert


# UTF-16 code-unit safety margin below Telegram's 4096 hard limit (Pitfall 1).
SAFETY_LIMIT = 4000

# Emoji + human label per intruder reason (D-12 aesthetic).
REASON_LABELS: dict[str, tuple[str, str]] = {
    "sql_injection":    ("💉", "SQL injection"),
    "honeypot":         ("🕳️", "Honeypot hit"),
    "suspicious_path":  ("🔍", "Suspicious path scan"),
    "rate_limit":       ("🚦", "Rate limit"),
    "auth_brute_force": ("🔐", "Auth brute-force"),
    "auth_failures":    ("🔐", "Auth brute-force"),
}
DEFAULT_REASON_EMOJI = "⚠️"


def _tg_len(s: str) -> int:
    """Length in UTF-16 code units — Telegram's 4096 measurement unit."""
    return len(s.encode("utf-16-le")) // 2


def _esc(s: Optional[str]) -> str:
    """HTML-escape an attacker-controlled value for insertion between tags.

    `quote=False` is correct: values are interpolated between tags, not inside
    HTML attributes. Never call this on the assembled message.
    """
    if s is None:
        return ""
    return html.escape(str(s), quote=False)


def _fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _reason_parts(reason: str) -> tuple[str, str]:
    if reason in REASON_LABELS:
        return REASON_LABELS[reason]
    return (DEFAULT_REASON_EMOJI, reason.replace("_", " ").title())


def _build_header(min_ts: datetime, max_ts: datetime, event_count: int) -> str:
    return (
        "<b>🛡️ Traefik Sentinel Digest</b>\n"
        f"<i>Since: {_fmt_ts(min_ts)} · Until: {_fmt_ts(max_ts)}</i>"
    )


def _build_blocked_section(db, block_ids: list[int]) -> str:
    if not block_ids:
        return "🚫 Blocked IPs: <b>0</b>"
    n = (
        db.query(func.count(func.distinct(BlockedIP.ip)))
        .filter(BlockedIP.id.in_(block_ids))
        .scalar()
        or 0
    )
    return f"🚫 Blocked IPs: <b>{n}</b>"


def _build_attack_breakdown(db, intruder_ids: list[int]) -> str:
    if not intruder_ids:
        return ""
    rows = (
        db.query(IntruderEvent.reason, func.count(IntruderEvent.id).label("n"))
        .filter(IntruderEvent.id.in_(intruder_ids))
        .group_by(IntruderEvent.reason)
        .order_by(desc("n"))
        .all()
    )
    if not rows:
        return ""
    lines = ["🎯 <b>Attack breakdown</b>"]
    for reason, n in rows:
        emoji, label = _reason_parts(reason)
        lines.append(f"{emoji} {label}: <b>{n}</b>")
    return "\n".join(lines)


async def _build_top_attackers(
    db,
    intruder_ids: list[int],
    top_n: int = 10,
    include_paths: bool = True,
) -> str:
    if not intruder_ids:
        return ""

    # Distinct IP count (used for "+N more" footer).
    distinct_ip_count = (
        db.query(func.count(func.distinct(IntruderEvent.ip)))
        .filter(IntruderEvent.id.in_(intruder_ids))
        .scalar()
        or 0
    )

    top_rows = (
        db.query(
            IntruderEvent.ip,
            func.count(IntruderEvent.id).label("n"),
            func.max(IntruderEvent.timestamp).label("latest"),
        )
        .filter(IntruderEvent.id.in_(intruder_ids))
        .group_by(IntruderEvent.ip)
        .order_by(desc("n"), desc("latest"))
        .limit(top_n)
        .all()
    )

    if not top_rows:
        return ""

    top_ips = [r[0] for r in top_rows]
    flags = await lookup_batch(top_ips)

    lines = ["🌐 <b>Top attackers</b>"]
    for ip, n, _latest in top_rows:
        info = flags.get(ip, {}) if isinstance(flags, dict) else {}
        flag = info.get("flag") or "🏳️"
        country = info.get("country") or ""
        line = (
            f"{flag} <code>{_esc(ip)}</code>"
            f" — {_esc(country)} ({n} events)"
            if country
            else f"{flag} <code>{_esc(ip)}</code> ({n} events)"
        )
        lines.append(line)

        if include_paths:
            sample = (
                db.query(IntruderEvent.details)
                .filter(
                    IntruderEvent.id.in_(intruder_ids),
                    IntruderEvent.ip == ip,
                )
                .order_by(desc(IntruderEvent.timestamp))
                .first()
            )
            if sample and sample[0]:
                path = str(sample[0])[:80]
                lines.append(f"   <i>{_esc(path)}</i>")

    if distinct_ip_count > top_n:
        remaining = distinct_ip_count - top_n
        lines.append(f"<i>+{remaining} more</i>")

    return "\n".join(lines)


def _build_traffic_overview(db, min_ts: datetime, max_ts: datetime) -> str:
    total = (
        db.query(func.count(AccessLog.id))
        .filter(AccessLog.timestamp.between(min_ts, max_ts))
        .scalar()
        or 0
    )
    unique = (
        db.query(func.count(func.distinct(AccessLog.ip)))
        .filter(AccessLog.timestamp.between(min_ts, max_ts))
        .scalar()
        or 0
    )
    errors = (
        db.query(func.count(AccessLog.id))
        .filter(
            AccessLog.timestamp.between(min_ts, max_ts),
            AccessLog.status >= 400,
        )
        .scalar()
        or 0
    )
    top_hosts = (
        db.query(AccessLog.host, func.count(AccessLog.id).label("n"))
        .filter(
            AccessLog.timestamp.between(min_ts, max_ts),
            AccessLog.host.isnot(None),
        )
        .group_by(AccessLog.host)
        .order_by(desc("n"))
        .limit(3)
        .all()
    )
    error_rate_pct = round((errors / total) * 100, 1) if total else 0.0

    lines = [
        "📊 <b>Traffic overview</b>",
        (
            f"Requests: <b>{total}</b> · Unique IPs: <b>{unique}</b>"
            f" · Error rate: <b>{error_rate_pct}%</b>"
        ),
    ]
    if top_hosts:
        host_strs = ", ".join(f"{_esc(h)} ({n})" for h, n in top_hosts)
        lines.append(f"🎪 Top hosts: {host_strs}")
    return "\n".join(lines)


def _build_footer(event_count: int, orphan_count: int) -> str:
    parts = []
    if orphan_count > 0:
        parts.append(f"⚠ {orphan_count} orphaned events")
    parts.append(f"<i>{event_count} events in this digest</i>")
    return "\n".join(parts)


async def _render(
    db,
    rows,
    intruder_ids: list[int],
    block_ids: list[int],
    min_ts: datetime,
    max_ts: datetime,
    top_n: int,
    include_paths: bool,
    orphan_count: int,
) -> str:
    parts = [
        _build_header(min_ts, max_ts, len(rows)),
        _build_blocked_section(db, block_ids),
        _build_attack_breakdown(db, intruder_ids),
        await _build_top_attackers(
            db, intruder_ids, top_n=top_n, include_paths=include_paths
        ),
        _build_traffic_overview(db, min_ts, max_ts),
        _build_footer(len(rows), orphan_count),
    ]
    return "\n\n".join(p for p in parts if p)


async def _truncate_if_needed(
    db,
    rows,
    intruder_ids: list[int],
    block_ids: list[int],
    min_ts: datetime,
    max_ts: datetime,
    orphan_count: int,
) -> str:
    """Iterative rebuild per D-15: shrink attacker list 10→5→3 (paths on),
    then 3 with paths off. Max 4 renders; accept last attempt regardless."""
    attempts = [
        (10, True),
        (5, True),
        (3, True),
        (3, False),
    ]
    msg = ""
    for top_n, include_paths in attempts:
        msg = await _render(
            db,
            rows,
            intruder_ids,
            block_ids,
            min_ts,
            max_ts,
            top_n=top_n,
            include_paths=include_paths,
            orphan_count=orphan_count,
        )
        if _tg_len(msg) <= SAFETY_LIMIT:
            return msg
    return msg  # whatever fits after passes (D-15)


async def build_message(db, rows) -> tuple[str, list[int]]:
    """Assemble the digest HTML message.

    Pure function: does not send, does not update sent_at. Returns
    (message, included_row_ids) — shared by send_digest and (future) preview.
    """
    intruder_ids = [r.source_id for r in rows if r.source == "intruder"]
    block_ids = [r.source_id for r in rows if r.source == "auto_block"]

    # Orphan detection — requested ids vs. hydrated source rows.
    intruder_hydrated = (
        db.query(IntruderEvent.id)
        .filter(IntruderEvent.id.in_(intruder_ids))
        .count()
        if intruder_ids
        else 0
    )
    block_hydrated = (
        db.query(BlockedIP.id).filter(BlockedIP.id.in_(block_ids)).count()
        if block_ids
        else 0
    )
    orphan_count = (len(intruder_ids) - intruder_hydrated) + (
        len(block_ids) - block_hydrated
    )

    min_ts = min(r.timestamp for r in rows)
    max_ts = max(r.timestamp for r in rows)

    message = await _truncate_if_needed(
        db, rows, intruder_ids, block_ids, min_ts, max_ts, orphan_count
    )
    return message, [r.id for r in rows]


async def send_digest() -> dict:
    """Entry point — manually triggered (via Phase 2 endpoint) and Phase-3 scheduled.

    Returns: {sent, event_count, skipped_reason, telegram_ok, message}.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(DigestEvent)
            .filter(DigestEvent.sent_at.is_(None))
            .all()
        )
        if not rows:
            return {
                "sent": False,
                "event_count": 0,
                "skipped_reason": "no_events",
                "telegram_ok": False,
                "message": None,
            }

        message, included_ids = await build_message(db, rows)

        try:
            telegram_ok = await send_alert(message, parse_mode="HTML")
        except Exception as e:
            print(f"Digest send failed: exception from send_alert: {e}")
            telegram_ok = False

        if telegram_ok:
            now = datetime.utcnow()
            (
                db.query(DigestEvent)
                .filter(DigestEvent.id.in_(included_ids))
                .update({DigestEvent.sent_at: now}, synchronize_session=False)
            )
            db.commit()
            return {
                "sent": True,
                "event_count": len(included_ids),
                "skipped_reason": None,
                "telegram_ok": True,
                "message": message,
            }

        print(
            f"Digest send failed: Telegram returned non-200; "
            f"{len(included_ids)} rows stay unsent"
        )
        return {
            "sent": False,
            "event_count": len(included_ids),
            "skipped_reason": "telegram_failed",
            "telegram_ok": False,
            "message": message,
        }
    finally:
        db.close()
