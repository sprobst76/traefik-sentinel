"""Alert routing: severity computation + immediate/digest gate + digest persistence.

Leaf module in the alerting subgraph. Imports only from app.config and app.database.
MUST NOT import from telegram_alerter, log_watcher, or auto_blocker (circular-import risk).
"""
from datetime import datetime
from typing import Literal
from sqlalchemy.orm import Session
from app.config import ALERT_MIN_SEVERITY
from app.database import DigestEvent


# Severity classification (moved from telegram_alerter.py per D-01)
THREAT_SEVERITY: dict[str, str] = {
    "sql_injection": "critical",
    "honeypot": "critical",
    "auth_failures": "high",
    "rate_limit": "medium",
    "suspicious_path": "medium",
}

# Integer rank for severity comparison (D-03)
_SEVERITY_RANK: dict[str, int] = {"critical": 3, "high": 2, "medium": 1}


def get_severity(reason: str, event: dict) -> Literal["critical", "high", "medium"]:
    """Return severity for an intruder event, honoring request-count escalation.

    Preserves the rule previously implemented in telegram_alerter.get_severity_header (D-06):
    - request_count > 50 -> escalate to critical
    - request_count > 20 and base severity == medium -> escalate to high
    Unknown reasons fall back to "medium".
    """
    severity = THREAT_SEVERITY.get(reason, "medium")
    request_count = event.get("request_count", 1) or 1

    if request_count > 50:
        severity = "critical"
    elif request_count > 20 and severity == "medium":
        severity = "high"

    return severity  # type: ignore[return-value]


def route_event(event: dict) -> Literal["immediate", "digest"]:
    """Decide whether an intruder event fires immediately or waits for the digest.

    Returns "immediate" when rank(severity) >= rank(ALERT_MIN_SEVERITY), else "digest".
    """
    severity = get_severity(event.get("reason", ""), event)
    threshold_rank = _SEVERITY_RANK.get(ALERT_MIN_SEVERITY, _SEVERITY_RANK["high"])
    event_rank = _SEVERITY_RANK.get(severity, _SEVERITY_RANK["medium"])
    return "immediate" if event_rank >= threshold_rank else "digest"


def persist_to_digest(
    db: Session,
    *,
    source: str,
    source_id: int,
    severity: str,
) -> None:
    """Persist a digest-eligible event reference. Commits inline. Synchronous (D-11)."""
    entry = DigestEvent(
        timestamp=datetime.utcnow(),
        source=source,
        source_id=source_id,
        severity=severity,
        sent_at=None,
    )
    db.add(entry)
    db.commit()
