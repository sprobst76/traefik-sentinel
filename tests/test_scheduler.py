"""Unit tests for app.scheduler — SCHED-01, SCHED-02, SCHED-05 scheduler logic."""

import asyncio
import inspect
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.scheduler import _seconds_until_next_fire, digest_scheduler

UTC = ZoneInfo("UTC")


def test_seconds_until_next_fire_returns_positive():
    """_seconds_until_next_fire returns a positive float ≤ 86400 for any valid hour."""
    for hour in range(24):
        result = _seconds_until_next_fire(hour)
        assert isinstance(result, float), f"hour={hour}: expected float, got {type(result)}"
        assert 0 < result <= 86400, f"hour={hour}: {result} not in (0, 86400]"


def test_seconds_until_next_fire_points_to_tomorrow_when_past():
    """At 09:05 UTC with hour=8, next fire is tomorrow at 08:00 (~22h55m away)."""
    fake_now = datetime(2026, 4, 12, 9, 5, 0, tzinfo=UTC)
    with patch("app.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = _seconds_until_next_fire(8)
    # Tomorrow 08:00 UTC minus 09:05 UTC = 22h55m = 82500s
    expected = (datetime(2026, 4, 13, 8, 0, 0, tzinfo=UTC) - fake_now).total_seconds()
    assert abs(result - expected) < 1, f"expected ~{expected}, got {result}"


def test_seconds_until_next_fire_points_to_today_when_future():
    """At 05:00 UTC with hour=8, next fire is today at 08:00 (~3 hours away)."""
    fake_now = datetime(2026, 4, 12, 5, 0, 0, tzinfo=UTC)
    with patch("app.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = _seconds_until_next_fire(8)
    # Today 08:00 UTC minus 05:00 UTC = 3h = 10800s
    expected = (datetime(2026, 4, 12, 8, 0, 0, tzinfo=UTC) - fake_now).total_seconds()
    assert abs(result - expected) < 1, f"expected ~{expected}, got {result}"


def test_digest_scheduler_is_async_coroutine():
    """digest_scheduler must be an async coroutine function."""
    assert inspect.iscoroutinefunction(digest_scheduler)


def test_digest_scheduler_cancellation_propagates():
    """CancelledError from asyncio.sleep must not be suppressed inside digest_scheduler."""
    async def main():
        task = asyncio.create_task(digest_scheduler())
        # Yield to let the coroutine enter asyncio.sleep
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return  # Expected — cancellation propagated correctly
        raise AssertionError("CancelledError was not raised; scheduler suppressed it")

    asyncio.run(main())


def test_no_utcnow_in_scheduler_source():
    """app/scheduler.py must not contain datetime.utcnow() (SCHED-05)."""
    import importlib.util
    import os
    # Find the scheduler module source file
    spec = importlib.util.find_spec("app.scheduler")
    assert spec is not None, "app.scheduler module not found"
    source_path = spec.origin
    assert source_path is not None
    with open(source_path) as f:
        source = f.read()
    assert "utcnow" not in source, (
        f"app/scheduler.py contains 'utcnow' — violates SCHED-05. "
        f"Use datetime.now(ZoneInfo('UTC')) instead."
    )
