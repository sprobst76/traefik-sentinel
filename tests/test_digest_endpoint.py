"""Integration tests for POST /api/digest/send (Plan 02-02, D-17).

Exercises the HTTP boundary via httpx.AsyncClient + ASGITransport. The
underlying `send_digest` library is covered by `test_digest.py`; here we only
verify endpoint wiring, response shape, and no-side-effect on empty state.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import DigestEvent
from tests.conftest import make_intruder, make_block, make_access, make_digest


class _NoCloseWrap:
    """Returned by stubbed SessionLocal; delegates to the shared test session
    but no-ops close() so the test fixture retains lifecycle control."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


async def _fake_geo(ips):
    return {
        ip: {"flag": "🏳️", "country": "X", "country_code": "XX"}
        for ip in ips
    }


@pytest.mark.asyncio
async def test_endpoint_empty_returns_no_events(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )

    async def _boom(*a, **kw):
        raise AssertionError("send_alert must not be called on empty path")

    monkeypatch.setattr("app.digest.send_alert", _boom)
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/digest/send")

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "sent": False,
        "event_count": 0,
        "skipped_reason": "no_events",
        "telegram_ok": False,
        "message": None,
    }


@pytest.mark.asyncio
async def test_endpoint_success(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    async def _ok(msg, parse_mode="HTML"):
        return True

    monkeypatch.setattr("app.digest.send_alert", _ok)

    now = datetime.utcnow()
    # Seed 2 intruder rows + 1 block row with matching sources + some access
    i1 = make_intruder(
        db_session, ip="1.2.3.4", reason="sql_injection",
        path="/?id=1%20OR%201=1", timestamp=now - timedelta(minutes=10),
    )
    i2 = make_intruder(
        db_session, ip="5.6.7.8", reason="suspicious_path",
        path="/wp-admin", timestamp=now - timedelta(minutes=5),
    )
    b1 = make_block(
        db_session, ip="1.2.3.4", reason="auto_block",
        timestamp=now - timedelta(minutes=3),
    )
    make_access(
        db_session, ip="1.2.3.4", status=403, host="example.com",
        timestamp=now - timedelta(minutes=7),
    )
    make_access(
        db_session, ip="5.6.7.8", status=200, host="example.com",
        timestamp=now - timedelta(minutes=6),
    )

    make_digest(
        db_session, source="intruder", source_id=i1.id,
        severity="medium", timestamp=i1.timestamp,
    )
    make_digest(
        db_session, source="intruder", source_id=i2.id,
        severity="low", timestamp=i2.timestamp,
    )
    make_digest(
        db_session, source="auto_block", source_id=b1.id,
        severity="medium", timestamp=b1.blocked_at,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/digest/send")

    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    assert body["event_count"] == 3
    assert body["telegram_ok"] is True
    assert body["skipped_reason"] is None
    assert isinstance(body["message"], str) and body["message"]
    assert "<b>" in body["message"]
    assert "🛡️" in body["message"]

    # D-18: all rows stamped after 200 OK
    unsent = (
        db_session.query(DigestEvent)
        .filter(DigestEvent.sent_at.is_(None))
        .count()
    )
    assert unsent == 0


@pytest.mark.asyncio
async def test_endpoint_telegram_failure(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    async def _fail(msg, parse_mode="HTML"):
        return False

    monkeypatch.setattr("app.digest.send_alert", _fail)

    now = datetime.utcnow()
    i1 = make_intruder(
        db_session, ip="9.9.9.9", reason="sql_injection",
        path="/admin", timestamp=now - timedelta(minutes=2),
    )
    make_access(
        db_session, ip="9.9.9.9", status=403, host="example.com",
        timestamp=now - timedelta(minutes=2),
    )
    make_digest(
        db_session, source="intruder", source_id=i1.id,
        severity="medium", timestamp=i1.timestamp,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/digest/send")

    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is False
    assert body["telegram_ok"] is False
    assert body["skipped_reason"] == "telegram_failed"

    # D-18: no stamping on failure
    unsent = (
        db_session.query(DigestEvent)
        .filter(DigestEvent.sent_at.is_(None))
        .count()
    )
    assert unsent == 1
