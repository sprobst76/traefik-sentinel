"""Unit coverage for app.digest — CONTENT-01..06, SCHED-03, D-18."""

from datetime import datetime, timedelta

import pytest

from app import digest as digest_module
from app.digest import _tg_len, build_message, send_digest, SAFETY_LIMIT
from tests.conftest import (
    make_access,
    make_block,
    make_digest,
    make_intruder,
)


# ----- helpers ---------------------------------------------------------------


def _patch_session_local(monkeypatch, db):
    """Route app.digest.SessionLocal() to a passthrough wrapper around `db`.

    Overrides `.close()` so the shared in-memory session survives the
    `finally` block inside `send_digest`.
    """

    class _Passthrough:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            # Swallow close — the fixture manages lifecycle.
            pass

    def _factory():
        return _Passthrough(db)

    monkeypatch.setattr(digest_module, "SessionLocal", _factory)


async def _empty_lookup(ips):
    return {}


# ----- tests -----------------------------------------------------------------


async def test_skip_when_empty(monkeypatch, db_session):
    """SCHED-03: zero unsent rows → skipped, no Telegram call."""
    called = {"n": 0}

    async def fake_send(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("send_alert must NOT be called when no events")

    monkeypatch.setattr(digest_module, "send_alert", fake_send)
    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    _patch_session_local(monkeypatch, db_session)

    result = await send_digest()
    assert result == {
        "sent": False,
        "event_count": 0,
        "skipped_reason": "no_events",
        "telegram_ok": False,
        "message": None,
    }
    assert called["n"] == 0


async def test_blocked_count(monkeypatch, db_session):
    """CONTENT-01: auto_block events → count shown with 🚫 emoji."""
    now = datetime.utcnow()
    for i, ip in enumerate(["1.1.1.1", "2.2.2.2", "3.3.3.3"]):
        b = make_block(db_session, ip=ip, timestamp=now - timedelta(minutes=i))
        make_digest(
            db_session,
            source="auto_block",
            source_id=b.id,
            severity="medium",
            timestamp=now - timedelta(minutes=i),
        )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    assert "🚫" in message
    assert "<b>3</b>" in message


async def test_attack_breakdown(monkeypatch, db_session):
    """CONTENT-02: reason breakdown, count descending."""
    now = datetime.utcnow()
    mix = (
        [("sql_injection", "1.1.1.1")] * 2
        + [("suspicious_path", "2.2.2.2")] * 2
        + [("rate_limit", "3.3.3.3")] * 1
    )
    for reason, ip in mix:
        ev = make_intruder(db_session, ip=ip, reason=reason, timestamp=now)
        make_digest(
            db_session,
            source="intruder",
            source_id=ev.id,
            severity="medium",
            timestamp=now,
        )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    # Each reason line appears with its count bolded.
    assert "SQL injection: <b>2</b>" in message
    assert "Suspicious path scan: <b>2</b>" in message
    assert "Rate limit: <b>1</b>" in message

    # Count descending: the two 2-count lines appear before the 1-count line.
    idx_sql = message.index("SQL injection: <b>2</b>")
    idx_susp = message.index("Suspicious path scan: <b>2</b>")
    idx_rate = message.index("Rate limit: <b>1</b>")
    assert idx_rate > max(idx_sql, idx_susp)


async def test_top_attackers_ordering(monkeypatch, db_session):
    """CONTENT-03: order by count desc, latest-timestamp tiebreaker."""
    base = datetime(2026, 4, 12, 12, 0, 0)
    # A: 5 events ending at base+5m. B: 5 events ending at base+10m (latest).
    # C: 3 events ending at base+4m.
    plan = [
        ("A", "10.0.0.1", 5, base + timedelta(minutes=5)),
        ("B", "10.0.0.2", 5, base + timedelta(minutes=10)),
        ("C", "10.0.0.3", 3, base + timedelta(minutes=4)),
    ]
    for _, ip, count, latest in plan:
        for i in range(count):
            ts = latest - timedelta(seconds=(count - i - 1))
            ev = make_intruder(
                db_session, ip=ip, reason="sql_injection", timestamp=ts
            )
            make_digest(
                db_session,
                source="intruder",
                source_id=ev.id,
                severity="high",
                timestamp=ts,
            )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    idx_a = message.index("10.0.0.1")
    idx_b = message.index("10.0.0.2")
    idx_c = message.index("10.0.0.3")
    # B (latest among 5-count tie) first, then A, then C.
    assert idx_b < idx_a < idx_c


async def test_traffic_window(monkeypatch, db_session):
    """CONTENT-04: traffic counts only consider the batch [min,max] window
    and exclude host IS NULL from top hosts."""
    base = datetime(2026, 4, 12, 12, 0, 0)
    # Digest batch window = [base+1m, base+9m]
    for i, ts in enumerate([base + timedelta(minutes=1), base + timedelta(minutes=9)]):
        ev = make_intruder(
            db_session, ip="9.9.9.9", reason="sql_injection", timestamp=ts
        )
        make_digest(
            db_session,
            source="intruder",
            source_id=ev.id,
            severity="high",
            timestamp=ts,
        )

    # In-window access logs.
    make_access(
        db_session, ip="7.7.7.7", status=200, host="a.example",
        timestamp=base + timedelta(minutes=2),
    )
    make_access(
        db_session, ip="7.7.7.7", status=500, host="a.example",
        timestamp=base + timedelta(minutes=3),
    )
    make_access(
        db_session, ip="8.8.8.8", status=200, host="b.example",
        timestamp=base + timedelta(minutes=5),
    )
    # host=None entry in window — must be excluded from top hosts.
    make_access(
        db_session, ip="6.6.6.6", status=200, host=None,
        timestamp=base + timedelta(minutes=4),
    )
    # Out-of-window entry — must be excluded entirely.
    make_access(
        db_session, ip="5.5.5.5", status=200, host="out.example",
        timestamp=base + timedelta(minutes=30),
    )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    # 4 in-window access rows (not 5).
    assert "Requests: <b>4</b>" in message
    # 3 unique IPs in window (7, 8, 6).
    assert "Unique IPs: <b>3</b>" in message
    # 1 error out of 4 = 25.0%
    assert "Error rate: <b>25.0%</b>" in message
    # Top hosts excludes None; out-of-window host absent.
    assert "a.example" in message
    assert "b.example" in message
    assert "out.example" not in message


async def test_html_escape(monkeypatch, db_session):
    """CONTENT-06: attacker-controlled fields are html-escaped."""
    now = datetime.utcnow()
    ev = make_intruder(
        db_session,
        ip="1.2.3.4",
        reason="sql_injection",
        path="<script>alert(1)</script>",
        host="<b>x</b>",
        details="<script>alert(1)</script>",
        timestamp=now,
    )
    make_digest(
        db_session,
        source="intruder",
        source_id=ev.id,
        severity="high",
        timestamp=now,
    )
    # Traffic access row with attacker-controlled-looking host.
    make_access(
        db_session,
        ip="1.2.3.4",
        status=500,
        host="<b>x</b>",
        timestamp=now,
    )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in message
    assert "&lt;b&gt;x&lt;/b&gt;" in message
    # Literal attacker tags must NOT appear.
    assert "<script>" not in message
    # Structural tags must still be present.
    assert "<b>" in message
    assert "<code>" in message
    assert "<i>" in message


async def test_truncation(monkeypatch, db_session):
    """CONTENT-05: 200 attackers → final message ≤ 4000 UTF-16 code units,
    contains '+N more', still contains attack-type breakdown."""
    now = datetime(2026, 4, 12, 12, 0, 0)
    for i in range(200):
        ip = f"10.{i // 256}.{(i // 16) % 16}.{i % 256}"
        ev = make_intruder(
            db_session,
            ip=ip,
            reason="sql_injection",
            path=f"/attack-{i}",
            timestamp=now + timedelta(seconds=i),
        )
        make_digest(
            db_session,
            source="intruder",
            source_id=ev.id,
            severity="high",
            timestamp=now + timedelta(seconds=i),
        )

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    rows = db_session.query(digest_module.DigestEvent).all()
    message, _ = await build_message(db_session, rows)

    assert _tg_len(message) <= SAFETY_LIMIT
    assert "more" in message and "+" in message
    assert "Attack breakdown" in message  # Core signal never dropped.


async def test_sent_at_only_on_success(monkeypatch, db_session):
    """D-18: sent_at stamped only when Telegram returns True."""
    now = datetime.utcnow()
    ids = []
    for i in range(3):
        ev = make_intruder(
            db_session, ip=f"1.1.1.{i}", reason="sql_injection", timestamp=now
        )
        d = make_digest(
            db_session,
            source="intruder",
            source_id=ev.id,
            severity="high",
            timestamp=now,
        )
        ids.append(d.id)

    monkeypatch.setattr(digest_module, "lookup_batch", _empty_lookup)
    _patch_session_local(monkeypatch, db_session)

    # --- Case A: Telegram returns True ---
    async def ok_send(message, parse_mode="HTML"):
        assert parse_mode == "HTML"
        return True

    monkeypatch.setattr(digest_module, "send_alert", ok_send)
    result = await send_digest()
    assert result["sent"] is True
    assert result["telegram_ok"] is True
    assert result["skipped_reason"] is None
    assert result["event_count"] == 3

    db_session.expire_all()
    sent_rows = (
        db_session.query(digest_module.DigestEvent)
        .filter(digest_module.DigestEvent.id.in_(ids))
        .all()
    )
    assert all(r.sent_at is not None for r in sent_rows)

    # --- Case B: Telegram returns False ---
    # Re-seed with 2 new unsent rows.
    ids_b = []
    for i in range(2):
        ev = make_intruder(
            db_session, ip=f"2.2.2.{i}", reason="rate_limit", timestamp=now
        )
        d = make_digest(
            db_session,
            source="intruder",
            source_id=ev.id,
            severity="medium",
            timestamp=now,
        )
        ids_b.append(d.id)

    async def bad_send(message, parse_mode="HTML"):
        return False

    monkeypatch.setattr(digest_module, "send_alert", bad_send)
    result_b = await send_digest()
    assert result_b["sent"] is False
    assert result_b["telegram_ok"] is False
    assert result_b["skipped_reason"] == "telegram_failed"
    assert result_b["event_count"] == 2

    db_session.expire_all()
    unsent_rows = (
        db_session.query(digest_module.DigestEvent)
        .filter(digest_module.DigestEvent.id.in_(ids_b))
        .all()
    )
    assert all(r.sent_at is None for r in unsent_rows)
