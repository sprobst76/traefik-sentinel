---
phase: 03-scheduler-and-integration
plan: 02
subsystem: scheduler
tags: [scheduler, asyncio, lifespan, zoneinfo, SCHED-01, SCHED-02, SCHED-04, SCHED-05]
dependency_graph:
  requires: [03-01]
  provides: [daily-digest-scheduler, lifespan-scheduler-wiring]
  affects: [app/main.py, app/scheduler.py]
tech_stack:
  added: []
  patterns: [asyncio-task-lifespan, next-fire-scheduling, zoneinfo-utc]
key_files:
  created:
    - app/scheduler.py
    - tests/test_scheduler.py
  modified:
    - app/main.py
    - .env.example
    - docker-compose.yml
decisions:
  - "Used datetime.now(ZoneInfo('UTC')) everywhere in scheduler — no utcnow() (SCHED-05)"
  - "CancelledError not caught inside digest_scheduler — propagates to lifespan for clean shutdown (D-23)"
  - "DIGEST_ENABLED gate lives in lifespan, not in scheduler module — single responsibility"
  - "Docstring phrasing avoids the literal string 'utcnow' to pass the source-level grep guard test"
metrics:
  duration: ~15 minutes
  completed: 2026-04-12
  tasks_completed: 3
  files_changed: 5
---

# Phase 3 Plan 02: Scheduler and Lifespan Wiring Summary

**One-liner:** Daily asyncio digest scheduler using `zoneinfo.ZoneInfo("UTC")` and next-fire arithmetic, wired into FastAPI lifespan with clean CancelledError shutdown.

## What Was Built

### app/scheduler.py (new, 56 lines)

New module exposing two public names:

- `_seconds_until_next_fire(hour: int) -> float` — computes wall-clock seconds until next `hour:00:00 UTC`. Always returns a strictly positive value; if the target hour already passed today, points to tomorrow.
- `digest_scheduler() -> None` (async coroutine) — `while True` loop: sleeps until next fire, then calls `await send_digest()` inside `try/except Exception`. `asyncio.sleep` `CancelledError` propagates without suppression.

Key properties:
- `UTC = ZoneInfo("UTC")` module-level constant — no `datetime.utcnow()` (SCHED-05)
- `from app.config import DIGEST_HOUR` — reads validated constant from Plan 03-01
- No `except asyncio.CancelledError` or `except BaseException` inside the module

### app/main.py lifespan (modified)

Before:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watcher.start()
    yield
    watcher.stop()
```

After:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watcher.start()
    scheduler_task = asyncio.create_task(digest_scheduler()) if DIGEST_ENABLED else None
    yield
    watcher.stop()
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
```

New imports added:
```python
from app.config import HOST, PORT, DIGEST_ENABLED
from app.scheduler import digest_scheduler
```

### Operator documentation

**.env.example** — new section appended:
```
# --- Digest scheduling (Phase 3) ---
DIGEST_ENABLED=true
DIGEST_HOUR=8
```

**docker-compose.yml** — two new environment pass-through lines:
```yaml
- DIGEST_ENABLED=${DIGEST_ENABLED:-true}
- DIGEST_HOUR=${DIGEST_HOUR:-8}
```

### Startup log line (for operator reference)

When the application starts with `DIGEST_ENABLED=true`, the following line appears in stdout:
```
Digest scheduler: next fire at 2026-04-13T08:00:00.000017+00:00
```

## Requirements Satisfied

| Requirement | Description | Status |
|-------------|-------------|--------|
| SCHED-01 | `DIGEST_HOUR` controls daily fire hour via `_seconds_until_next_fire(DIGEST_HOUR)` | Satisfied |
| SCHED-02 | `DIGEST_ENABLED=false` prevents scheduler task creation; manual endpoints unaffected | Satisfied |
| SCHED-04 | Scheduler runs as `asyncio.Task` inside existing FastAPI `lifespan` — no new process/thread | Satisfied |
| SCHED-05 | `app/scheduler.py` uses `datetime.now(ZoneInfo("UTC"))`; grep for `utcnow` returns 0 | Satisfied |

## Threat Mitigations Applied

| Threat | Mitigation |
|--------|------------|
| T-03-05 (DoS: exception in send_digest kills loop) | `try/except Exception` around `await send_digest()` logs and continues |
| T-03-06 (DoS: orphaned task on shutdown) | `scheduler_task.cancel()` + `await` + `except asyncio.CancelledError` in lifespan |
| T-03-08 (DoS: hung shutdown from suppressed CancelledError) | Source-level grep confirms zero `except asyncio.CancelledError` / `except BaseException` in scheduler.py |

## Test Coverage

`tests/test_scheduler.py` — 6 tests, all passing:

1. `test_seconds_until_next_fire_returns_positive` — positive float 0–86400 for all hours 0-23
2. `test_seconds_until_next_fire_points_to_tomorrow_when_past` — at 09:05 UTC with hour=8, result ≈82500s (±60s)
3. `test_seconds_until_next_fire_points_to_today_when_future` — at 05:00 UTC with hour=8, result ≈10800s (±60s)
4. `test_digest_scheduler_is_async_coroutine` — `inspect.iscoroutinefunction(digest_scheduler)` is True
5. `test_digest_scheduler_cancellation_propagates` — `CancelledError` raised when task cancelled
6. `test_no_utcnow_in_scheduler_source` — source file does not contain substring "utcnow"

## Deviations from Plan

**1. [Rule 1 - Bug] Docstring contained "utcnow" substring triggering test 6**
- **Found during:** Task 1 (GREEN phase, first test run)
- **Issue:** The docstring "No datetime.utcnow() calls in this module" contained the literal string "utcnow", causing `test_no_utcnow_in_scheduler_source` to fail
- **Fix:** Replaced docstring phrase with "Uses datetime.now(UTC) — never the deprecated UTC-naive shorthand"
- **Files modified:** app/scheduler.py
- **Impact:** None — semantically equivalent wording

## Known Stubs

None. `send_digest()` is the live implementation from Phase 2 (Plan 02-01).

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced.

## Self-Check

### Created files exist

- [x] app/scheduler.py
- [x] tests/test_scheduler.py
- [x] .env.example (modified)
- [x] docker-compose.yml (modified)
- [x] app/main.py (modified)

### Commits exist

- 238a57d: feat(03-02): add digest_scheduler asyncio coroutine with next-fire UTC timing
- c40e76f: feat(03-02): wire digest_scheduler into lifespan with clean cancellation
- 6ed51cf: docs(03-02): document DIGEST_ENABLED and DIGEST_HOUR in .env.example and compose

## Self-Check: PASSED
