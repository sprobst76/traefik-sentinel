"""Shared pytest fixtures + factories for traefik-sentinel tests.

Provides an in-memory SQLite `db_session` fixture (schema created via
Base.metadata.create_all) and minimal row factories for the four models
Phase 2 digest tests exercise: IntruderEvent, BlockedIP, AccessLog, DigestEvent.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    AccessLog,
    IntruderEvent,
    BlockedIP,
    DigestEvent,
)


@pytest.fixture
def db_session():
    """Yield a fresh in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_intruder(
    db,
    *,
    ip,
    reason,
    path="/",
    host=None,
    status_code=403,
    timestamp=None,
    details=None,
) -> IntruderEvent:
    row = IntruderEvent(
        ip=ip,
        reason=reason,
        details=details if details is not None else path,
        status_code=status_code,
        host=host,
        timestamp=timestamp or datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def make_block(
    db,
    *,
    ip,
    reason="honeypot",
    timestamp=None,
) -> BlockedIP:
    row = BlockedIP(
        ip=ip,
        reason=reason,
        blocked_at=timestamp or datetime.utcnow(),
        active=1,
        is_cidr=0,
        block_count=1,
        auto_blocked=1,
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def make_access(
    db,
    *,
    ip,
    status,
    host=None,
    timestamp=None,
    method="GET",
    path="/",
    protocol="HTTP/1.1",
    bytes_=0,
) -> AccessLog:
    row = AccessLog(
        timestamp=timestamp or datetime.utcnow(),
        ip=ip,
        method=method,
        path=path,
        protocol=protocol,
        status=status,
        bytes=bytes_,
        host=host,
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def make_digest(
    db,
    *,
    source,
    source_id,
    severity="medium",
    timestamp=None,
    sent_at=None,
) -> DigestEvent:
    row = DigestEvent(
        timestamp=timestamp or datetime.utcnow(),
        source=source,
        source_id=source_id,
        severity=severity,
        sent_at=sent_at,
    )
    db.add(row)
    db.flush()
    db.commit()
    return row
