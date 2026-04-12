"""Integration tests for GET /api/digest/preview (Plan 02-03).

Verifies the dry-run preview endpoint returns the same message `send_digest`
would assemble, while guaranteeing zero side effects: no Telegram call, no
UPDATE against `digest_events`, no commit.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import DigestEvent
from tests.conftest import make_intruder, make_access, make_digest


class _NoCloseWrap:
    """Stubbed SessionLocal result: delegates to the shared in-memory session
    but no-ops close() so the fixture retains lifecycle control."""

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
async def test_preview_empty(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/digest/preview")

    assert r.status_code == 200
    assert r.json() == {"event_count": 0, "message": None, "utf16_length": 0}


@pytest.mark.asyncio
async def test_preview_read_only(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    async def _boom(*a, **kw):
        raise AssertionError("send_alert called from preview")

    monkeypatch.setattr("app.digest.send_alert", _boom)

    now = datetime.utcnow()
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    for i, ip in enumerate(ips):
        ev = make_intruder(
            db_session, ip=ip, reason="sql_injection",
            path=f"/p{i}", timestamp=now - timedelta(minutes=10 - i),
        )
        make_access(
            db_session, ip=ip, status=403, host="example.com",
            timestamp=ev.timestamp,
        )
        make_digest(
            db_session, source="intruder", source_id=ev.id,
            severity="medium", timestamp=ev.timestamp,
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r1 = await c.get("/api/digest/preview")
        r2 = await c.get("/api/digest/preview")

    assert r1.status_code == 200
    assert r2.status_code == 200
    b1, b2 = r1.json(), r2.json()
    assert b1 == b2
    assert b1["event_count"] == 3
    assert isinstance(b1["message"], str) and b1["message"]
    assert b1["utf16_length"] > 0

    # Read-only: sent_at untouched after two preview calls
    unsent = (
        db_session.query(DigestEvent)
        .filter(DigestEvent.sent_at.is_(None))
        .count()
    )
    assert unsent == 3


@pytest.mark.asyncio
async def test_preview_utf16_under_limit(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    now = datetime.utcnow()
    for i in range(50):
        ip = f"172.16.{i // 256}.{i % 256}"
        ev = make_intruder(
            db_session, ip=ip, reason="suspicious_path",
            path=f"/scan/{i}", timestamp=now - timedelta(seconds=i),
        )
        make_digest(
            db_session, source="intruder", source_id=ev.id,
            severity="low", timestamp=ev.timestamp,
        )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/digest/preview")

    assert r.status_code == 200
    body = r.json()
    assert body["utf16_length"] <= 4000
    assert "more" in body["message"]


@pytest.mark.asyncio
async def test_preview_escape(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.digest.SessionLocal", lambda: _NoCloseWrap(db_session)
    )
    monkeypatch.setattr("app.digest.lookup_batch", _fake_geo)

    now = datetime.utcnow()
    ev = make_intruder(
        db_session, ip="8.8.8.8", reason="sql_injection",
        path="<script>alert(1)</script>",
        timestamp=now - timedelta(minutes=1),
    )
    make_digest(
        db_session, source="intruder", source_id=ev.id,
        severity="high", timestamp=ev.timestamp,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/digest/preview")

    assert r.status_code == 200
    msg = r.json()["message"]
    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg
