"""Unit tests for app.scheduler — SCHED-01, SCHED-02, SCHED-04, SCHED-05.

Tests use stdlib-only patterns (unittest + asyncio.run) matching project test style.
"""

import asyncio
import inspect
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from zoneinfo import ZoneInfo

import pytest

UTC = ZoneInfo("UTC")


def test_seconds_until_next_fire_returns_positive():
    """_seconds_until_next_fire(h) returns a float > 0 and <= 86400 for any valid h."""
    from app.scheduler import _seconds_until_next_fire

    for h in range(0, 24):
        result = _seconds_until_next_fire(h)
        assert isinstance(result, float), f"Expected float, got {type(result)} for hour={h}"
        assert 0 < result <= 86400, f"Out of range {result} for hour={h}"


def test_seconds_until_next_fire_points_to_tomorrow_when_past():
    """At 09:05 UTC, _seconds_until_next_fire(8) should be ~22h55m (points to tomorrow)."""
    from app.scheduler import _seconds_until_next_fire

    fake_now = datetime(2024, 1, 15, 9, 5, 0, tzinfo=UTC)

    with patch("app.scheduler.datetime") as mock_dt:
        # Passthrough constructor so replace() and arithmetic work on real datetime objects
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        result = _seconds_until_next_fire(8)

    # Expected: tomorrow 08:00 UTC - 09:05 UTC = 22h55m = 82500s
    # Tolerance: ±60s
    expected = 82500.0
    assert abs(result - expected) <= 60, f"Expected ~{expected}s, got {result}s"


def test_seconds_until_next_fire_points_to_today_when_future():
    """At 05:00 UTC, _seconds_until_next_fire(8) should be ~3 hours (points to today)."""
    from app.scheduler import _seconds_until_next_fire

    fake_now = datetime(2024, 1, 15, 5, 0, 0, tzinfo=UTC)

    with patch("app.scheduler.datetime") as mock_dt:
        # Passthrough constructor so replace() and arithmetic work on real datetime objects
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        result = _seconds_until_next_fire(8)

    # Expected: 08:00 UTC - 05:00 UTC = 3h = 10800s
    expected = 10800.0
    assert abs(result - expected) <= 60, f"Expected ~{expected}s, got {result}s"


def test_digest_scheduler_is_async_coroutine():
    """digest_scheduler must be an async coroutine function (SCHED-04)."""
    from app.scheduler import digest_scheduler

    assert inspect.iscoroutinefunction(digest_scheduler), (
        "digest_scheduler must be an async coroutine function"
    )


def test_digest_scheduler_cancellation_propagates():
    """CancelledError must propagate out of digest_scheduler (not be suppressed)."""
    from app.scheduler import digest_scheduler

    async def main():
        task = asyncio.create_task(digest_scheduler())
        await asyncio.sleep(0)  # yield to let task start
        task.cancel()
        try:
            await task
            raise AssertionError("CancelledError was not raised — it was suppressed inside coroutine")
        except asyncio.CancelledError:
            pass  # expected

    asyncio.run(main())


def test_no_utcnow_in_scheduler_source():
    """app/scheduler.py must NOT contain 'utcnow' (SCHED-05 source-level guard)."""
    import pathlib
    source = (pathlib.Path(__file__).parent.parent / "app" / "scheduler.py").read_text()
    assert "utcnow" not in source, (
        "app/scheduler.py must not use datetime.utcnow() — use datetime.now(UTC) instead"
    )
