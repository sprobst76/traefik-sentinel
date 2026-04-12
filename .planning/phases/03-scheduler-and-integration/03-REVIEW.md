---
phase: 03-scheduler-and-integration
reviewed: 2026-04-12T18:51:31Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - app/config.py
  - app/main.py
  - app/scheduler.py
  - docker-compose.yml
  - .env.example
  - tests/test_scheduler.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-04-12T18:51:31Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

This review covers the daily digest scheduler (`app/scheduler.py`), its lifespan wiring (`app/main.py`), new config knobs (`app/config.py`), compose and env documentation, and the scheduler test suite.

The Phase 3 scheduler implementation itself is correct. `app/scheduler.py` uses `datetime.now(UTC)` throughout, never `utcnow()`. `CancelledError` propagates cleanly from `asyncio.sleep` without being caught inside `digest_scheduler`. The lifespan shutdown block correctly cancels the task and suppresses the resulting `CancelledError` once. The `_seconds_until_next_fire` next-fire calculation and miss-policy (tomorrow if the hour has already passed today) are both correct.

The test suite is well-structured. The mock pattern in `test_seconds_until_next_fire_points_to_tomorrow_when_past` and `test_seconds_until_next_fire_points_to_today_when_future` is valid: `mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)` combined with `mock_dt.now.return_value = fake_now` ensures all arithmetic operates on real `datetime` objects. `timedelta` is imported separately in the scheduler module and is unaffected by the `datetime` patch.

Three warnings require operator attention: `datetime.utcnow()` is used in ten places in `main.py` producing UTC-naive datetimes inconsistent with the timezone-aware approach required by SCHED-05; a default-value mismatch for `RATE_LIMIT_REQUESTS` between `config.py` (500) and `docker-compose.yml` (100) means the effective default depends on the deploy path; and `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` is absent from `docker-compose.yml`'s environment block, silently discarding any operator setting.

---

## Warnings

### WR-01: `datetime.utcnow()` used in ten places in `app/main.py` — produces UTC-naive datetimes inconsistent with SCHED-05

**File:** `app/main.py:65, 106, 136, 167, 266, 312, 660, 661, 662, 718`
**Issue:** All database time-window filters and retention cutoffs in `main.py` use `datetime.utcnow()`, which returns a UTC-naive `datetime` (no `tzinfo`). The project convention established by SCHED-05 requires `datetime.now(ZoneInfo("UTC"))` (timezone-aware). If SQLite timestamps are ever stored or compared as timezone-aware values — or if the project migrates toward timezone-aware storage — these calls will produce incorrect comparisons. The inconsistency also makes the codebase harder to reason about: `scheduler.py` is explicit about UTC while `main.py` relies on the deprecated shorthand.

Representative example (`app/main.py:65`):
```python
since = datetime.utcnow() - timedelta(hours=hours)
```

**Fix:** Replace all occurrences with the timezone-aware form. Add `ZoneInfo` to the import block and update each call:
```python
# Add to imports (app/main.py top)
from zoneinfo import ZoneInfo
_UTC = ZoneInfo("UTC")

# Replace each datetime.utcnow() with:
since = datetime.now(_UTC).replace(tzinfo=None)  # keep naive for SQLite compat
# or, if moving fully to aware datetimes:
since = datetime.now(_UTC)
```
If keeping SQLite timestamps naive, the safest short-term fix is:
```python
since = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
```
This preserves the naive-datetime contract for SQLAlchemy while eliminating the deprecated call.

---

### WR-02: `RATE_LIMIT_REQUESTS` default is 500 in `config.py` but 100 in `docker-compose.yml` and `.env.example` — effective default depends on deploy path

**File:** `app/config.py:29` and `docker-compose.yml:23` and `.env.example:36`
**Issue:** `config.py` declares:
```python
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "500"))
```
But `docker-compose.yml` injects:
```yaml
- RATE_LIMIT_REQUESTS=${RATE_LIMIT_REQUESTS:-100}
```
When an operator runs `docker compose up` without a `.env` file or without setting `RATE_LIMIT_REQUESTS`, the compose fallback `:-100` wins and the container sees `RATE_LIMIT_REQUESTS=100`, not 500. The Python fallback of 500 is unreachable in a compose-based deploy. This creates two different effective defaults depending on whether the application is started via `docker compose` or directly with `python -m uvicorn`, making the comment `# Higher for normal web usage` misleading.

**Fix:** Align the defaults. Decide which value (100 or 500) is correct and update both files:
```python
# app/config.py — if 100 is correct:
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
```
```yaml
# docker-compose.yml — if 500 is correct:
- RATE_LIMIT_REQUESTS=${RATE_LIMIT_REQUESTS:-500}
```
Also update `.env.example` to match whichever value is chosen.

---

### WR-03: `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` missing from `docker-compose.yml` environment block — operator setting silently ignored

**File:** `docker-compose.yml:34-35` (after `RETENTION_INTRUDER_EVENTS_DAYS`)
**Issue:** `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` is defined in `config.py` (line 142, default 180), used in two retention endpoints in `main.py` (lines 662 and 672), and documented in `.env.example` (line 60). However, it is not listed in `docker-compose.yml`'s `environment:` block. If an operator sets `RETENTION_BLOCKED_IPS_INACTIVE_DAYS=30` in their `.env` file and deploys via `docker compose`, the variable is not forwarded to the container and the code silently uses the 180-day default regardless.

**Fix:** Add the missing environment passthrough to `docker-compose.yml`:
```yaml
      - RETENTION_BLOCKED_IPS_INACTIVE_DAYS=${RETENTION_BLOCKED_IPS_INACTIVE_DAYS:-180}
```
Place it immediately after the `RETENTION_INTRUDER_EVENTS_DAYS` line for grouping consistency.

---

## Info

### IN-01: `test_no_utcnow_in_scheduler_source` uses a relative path — breaks when pytest is invoked outside project root

**File:** `tests/test_scheduler.py:93`
**Issue:** `pathlib.Path("app/scheduler.py").read_text()` resolves relative to the working directory at test execution time. If pytest is run from `tests/` (`cd tests && pytest`) or from any other directory that is not the project root, this raises `FileNotFoundError` and the test fails with an uninformative error rather than the intended assertion message.

**Fix:** Use `__file__` to anchor the path:
```python
source = (pathlib.Path(__file__).parent.parent / "app" / "scheduler.py").read_text()
```

---

### IN-02: `_DIGEST_HOUR_RAW = -1` sentinel in `config.py` produces a misleading fallback warning message

**File:** `app/config.py:161, 163-164`
**Issue:** When `DIGEST_HOUR` contains a non-integer value (e.g., `"noon"`), the `except ValueError` block sets `_DIGEST_HOUR_RAW = -1` as a sentinel to force the subsequent range check to produce a fallback. This prints the correct warning on the `ValueError` path (line 160), but then also triggers the range-check warning (line 164) with `DIGEST_HOUR=-1 out of range 0-23`, emitting a second, misleading log line about `-1` when the real problem was a non-integer value.

**Fix:** Short-circuit the fallback directly in the `except` block, bypassing the range check:
```python
try:
    _DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
    if not 0 <= _DIGEST_HOUR_RAW <= 23:
        print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range 0-23, falling back to 8")
        DIGEST_HOUR = 8
    else:
        DIGEST_HOUR = _DIGEST_HOUR_RAW
except ValueError:
    print(f"Config warning: DIGEST_HOUR={os.getenv('DIGEST_HOUR')!r} is not a valid integer, falling back to 8")
    DIGEST_HOUR = 8
```
This eliminates the `-1` sentinel, removes the spurious second warning, and makes each error path independent.

---

_Reviewed: 2026-04-12T18:51:31Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
