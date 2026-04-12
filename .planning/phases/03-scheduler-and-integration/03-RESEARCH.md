# Phase 3: Scheduler and Integration - Research

**Researched:** 2026-04-12
**Domain:** asyncio background task scheduling inside FastAPI lifespan
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-21:** Scheduler uses next-fire calculation (not polling). Compute `seconds until DIGEST_HOUR:00:00 UTC`, sleep, fire, repeat. Drift-free, correct across DST, no no-op wake-ups.
- **D-22:** Miss policy: wait until tomorrow. If app starts after `DIGEST_HOUR` has already passed, the next fire is `DIGEST_HOUR:00:00 the following day`. No surprise digest on restart. Manual `/api/digest/send` remains available.
- **D-23:** Shutdown via `task.cancel()` + `await task` + `CancelledError` suppression. Scheduler coroutine must NOT suppress `CancelledError` internally.
- **D-24:** `DIGEST_HOUR` is integer 0–23. Invalid value falls back to 8 with `print()` warning, matching the `ALERT_MIN_SEVERITY` validation pattern in `config.py`.
- **D-25:** `DIGEST_ENABLED=false` prevents scheduler from starting (`create_task` is guarded by `if DIGEST_ENABLED`). Manual `/api/digest/send` and `/api/digest/preview` endpoints remain active regardless.
- **D-26:** All scheduling uses `zoneinfo.ZoneInfo("UTC")` explicitly. No `datetime.utcnow()` in scheduling code. `DIGEST_TIMEZONE` env var is deferred to v2 (ADV-05).
- **D-27:** Scheduler loop lives in new `app/scheduler.py`. `main.py` lifespan does `create_task` / `cancel`. Exact pattern:
  ```python
  scheduler_task = asyncio.create_task(_digest_scheduler()) if DIGEST_ENABLED else None
  # shutdown:
  if scheduler_task:
      scheduler_task.cancel()
      try:
          await scheduler_task
      except asyncio.CancelledError:
          pass
  ```
- **D-28:** Two new constants in `app/config.py`: `DIGEST_ENABLED` (bool, default `true`) and `DIGEST_HOUR` (int, default 8, validated 0–23).

### Claude's Discretion

- Exact module-level structure of `app/scheduler.py` (helper function names, loop variable names).
- Whether to add a startup log line — recommended yes: `print(f"Digest scheduler started — next fire at {next_fire.isoformat()}")`.
- Whether to catch and log exceptions from `send_digest()` inside the loop — recommended yes: a failed send should not crash the scheduler.
- Whether to log the `send_digest()` return value in the scheduler — recommended yes for debugging.

### Deferred Ideas (OUT OF SCOPE)

- `DIGEST_TIMEZONE` env var (ADV-05) — deferred to v2.
- Sub-hour digest granularity.
- Multiple digest schedules (hourly / 4-hour) — ADV-04, v2.
- `DIGEST_ENABLED=false` suppressing the manual endpoint — user confirmed: manual always works.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHED-01 | Digest is sent once per day at a configurable time via `DIGEST_HOUR` env var (default 08:00 UTC) | D-21 + next-fire calculation pattern below |
| SCHED-02 | Digest can be disabled via `DIGEST_ENABLED` env var (default `true`) | D-25 + D-28 config pattern |
| SCHED-04 | Scheduler runs as asyncio task inside FastAPI lifespan — no new process or worker | D-27 lifespan integration pattern |
| SCHED-05 | Scheduler uses timezone-aware `datetime` with `zoneinfo` — no `datetime.utcnow()` for scheduling | D-26 + verified `zoneinfo` availability |
</phase_requirements>

---

## Summary

Phase 3 is a pure wiring phase: one new file (`app/scheduler.py`), two config additions (`DIGEST_ENABLED`, `DIGEST_HOUR`), and a small lifespan extension in `app/main.py`. The `send_digest()` function from Phase 2 already exists and is `async def`; the scheduler only needs to call it at the right time and handle exceptions gracefully.

The scheduling pattern is next-fire calculation: compute the number of seconds until `DIGEST_HOUR:00:00 UTC`, sleep that duration using `asyncio.sleep`, call `send_digest()`, then loop. `asyncio.sleep` propagates `CancelledError` naturally, so clean shutdown requires no special handling inside the coroutine itself — only the caller (`lifespan`) suppresses it once.

The `zoneinfo` standard library module (Python 3.9+, present in Python 3.11/3.12 slim images) provides the `ZoneInfo("UTC")` object needed for timezone-aware `datetime.now()`. The existing codebase uses `datetime.utcnow()` widely — the new scheduler must explicitly use the `zoneinfo` pattern; it does not need to retrofit the rest of the codebase.

**Primary recommendation:** Implement `app/scheduler.py` as a self-contained module with one public coroutine `digest_scheduler()`, one private helper `_seconds_until_next_fire(hour: int) -> float`, and wrap the `send_digest()` call in `try/except Exception` to log failures without crashing the loop.

---

## Standard Stack

### Core — No New Dependencies

All required functionality is available from the Python 3.11 standard library and the already-installed packages. No new `pip install` is needed for this phase. [VERIFIED: codebase inspection + runtime check]

| Module | Source | Purpose |
|--------|--------|---------|
| `zoneinfo` | stdlib (Python 3.9+) | Timezone-aware `datetime` objects |
| `asyncio` | stdlib | `create_task`, `sleep`, `CancelledError` |
| `datetime` | stdlib | `datetime.now(tz)`, `timedelta`, `replace()` |

**Runtime verification:** `zoneinfo` confirmed available in this environment (Python 3.12.3). The Python 3.11 slim Docker image used in production also ships `zoneinfo` as part of the standard library without requiring `tzdata` for UTC. [VERIFIED: local runtime check]

**Note on `tzdata` package:** For non-UTC `zoneinfo` keys on some slim Docker images, `pip install tzdata` is required. For `ZoneInfo("UTC")` only (Phase 3 scope), the stdlib is sufficient without `tzdata`. [VERIFIED: Python docs — UTC is always available from stdlib]

---

## Architecture Patterns

### Recommended Module Structure

```
app/
├── scheduler.py       # NEW: digest_scheduler() coroutine
├── config.py          # MODIFY: add DIGEST_ENABLED + DIGEST_HOUR
├── main.py            # MODIFY: lifespan — create_task + cancel
└── digest.py          # UNCHANGED: send_digest() is the call target
```

### Pattern 1: Next-Fire Calculation

**What:** Compute wall-clock seconds until the next occurrence of a given hour (UTC), sleep exactly that duration, fire, then repeat.

**Why:** Drift-free. No accumulation of small timing errors across days. Correct when clocks stay in UTC (DST irrelevant for UTC schedules).

**Verified example (confirmed working in this environment):**

```python
# Source: verified via local Python 3.12.3 runtime
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")

def _seconds_until_next_fire(hour: int) -> float:
    now = datetime.now(UTC)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
```

Test result: when called at 09:05 UTC with `hour=8`, returns 82500 seconds (22.92 hours — correctly points to tomorrow 08:00). [VERIFIED: local runtime test]

### Pattern 2: Scheduler Coroutine Loop

**What:** Async coroutine that computes next fire, sleeps, calls `send_digest()`, then loops.

**Key property:** `asyncio.sleep` raises `asyncio.CancelledError` when the task is cancelled. The coroutine must NOT have a bare `except Exception` around the sleep — only around the `send_digest()` call. If `CancelledError` is caught by a broad `except`, it must be re-raised.

```python
# Source: Python asyncio documentation pattern + CONTEXT.md D-23
import asyncio
from app.config import DIGEST_HOUR
from app.digest import send_digest

UTC = ZoneInfo("UTC")


async def digest_scheduler() -> None:
    """Background task: calls send_digest() once daily at DIGEST_HOUR:00 UTC.

    Sleep duration is computed fresh each iteration (next-fire calculation, D-21).
    Miss policy: if started after DIGEST_HOUR, waits until tomorrow (D-22).
    CancelledError from asyncio.sleep propagates naturally — do not suppress it here.
    """
    while True:
        seconds = _seconds_until_next_fire(DIGEST_HOUR)
        next_fire = datetime.now(UTC) + timedelta(seconds=seconds)
        print(f"Digest scheduler: next fire at {next_fire.isoformat()}")
        await asyncio.sleep(seconds)
        try:
            result = await send_digest()
            print(f"Digest scheduler: send_digest result={result}")
        except Exception as e:
            print(f"Digest scheduler: send_digest failed: {e}")
```

### Pattern 3: Lifespan Integration

**What:** Extend the existing `lifespan` context manager in `main.py` to start and stop the scheduler task.

**Existing lifespan (lines 28-35 of app/main.py):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    watcher.start()
    yield
    # Shutdown
    watcher.stop()
```

**Extended lifespan (Phase 3 change):**
```python
# Source: CONTEXT.md D-27 + established create_task pattern in main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    watcher.start()
    scheduler_task = asyncio.create_task(digest_scheduler()) if DIGEST_ENABLED else None
    yield
    # Shutdown
    watcher.stop()
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
```

### Pattern 4: Config Additions (matches existing `ALERT_MIN_SEVERITY` pattern)

```python
# Source: CONTEXT.md D-28, mirrors existing ALERT_MIN_SEVERITY validation in config.py
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "true").lower() == "true"

_DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
if not 0 <= _DIGEST_HOUR_RAW <= 23:
    print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range, falling back to 8")
    DIGEST_HOUR = 8
else:
    DIGEST_HOUR = _DIGEST_HOUR_RAW
```

**Issue to watch:** `int(os.getenv("DIGEST_HOUR", "8"))` will raise `ValueError` if a non-integer string (e.g. `"8am"`) is provided. Add `try/except ValueError` to match defensive patterns in other config blocks. [ASSUMED — existing pattern defensiveness warrants this, but the CONTEXT.md D-28 snippet does not show it explicitly]

### Anti-Patterns to Avoid

- **Bare `except Exception` around `asyncio.sleep`:** This silently swallows `CancelledError` in Python < 3.8. In Python 3.8+ `CancelledError` is a subclass of `BaseException`, not `Exception`, so this specific anti-pattern is less dangerous — but catch only what you intend.
- **`datetime.utcnow()` in scheduling code:** Produces naive datetime (no tz info), causing comparison bugs with timezone-aware datetimes. Banned by SCHED-05 and D-26.
- **Module-level `asyncio.create_task()` outside lifespan:** Tasks created before the event loop starts will fail. Always create the task inside the `lifespan` async context or a route handler.
- **Long-sleep tasks without cancellation handling:** If the task is cancelled mid-sleep (e.g., during a 23-hour wait), it must propagate `CancelledError` upward. The current design does this correctly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Daily scheduling | Custom cron-like poller with 60s wake-ups | Next-fire calculation + `asyncio.sleep` | No drift, no wasted wake-ups, already decided (D-21) |
| Timezone-aware datetime | Manual UTC offset math | `datetime.now(ZoneInfo("UTC"))` | Handles edge cases, stdlib, no deps |
| Task cleanup | Thread joins, process signals | `task.cancel()` + `await` + `CancelledError` suppression | Standard asyncio pattern, handles pending sleep correctly |

**Key insight:** `APScheduler` was explicitly rejected (REQUIREMENTS.md Out of Scope) — native asyncio is sufficient and has no multi-worker footguns.

---

## Common Pitfalls

### Pitfall 1: `int()` on invalid `DIGEST_HOUR` string raises `ValueError` at import time

**What goes wrong:** If someone sets `DIGEST_HOUR=8am` in `.env`, `int(os.getenv("DIGEST_HOUR", "8"))` raises `ValueError` before the fallback logic can run, crashing the process at startup.

**Why it happens:** The `int()` call is outside any try/except in the D-28 snippet.

**How to avoid:** Wrap in `try/except ValueError` and fall back to 8 with a warning — consistent with how `ALERT_MIN_SEVERITY` gracefully handles invalid strings.

**Warning signs:** `ValueError: invalid literal for int()` in startup logs.

### Pitfall 2: Catching `CancelledError` inside the scheduler loop

**What goes wrong:** A broad `try/except Exception` around `await asyncio.sleep(...)` appears to work in Python 3.8+ (because `CancelledError` is `BaseException`, not `Exception`). However, wrapping the loop body in `except BaseException` and not re-raising `CancelledError` will prevent clean shutdown — the task runs forever and `await scheduler_task` in the lifespan shutdown block hangs.

**Why it happens:** Copy-paste of generic error handling boilerplate.

**How to avoid:** The `except Exception` guard belongs only around the `send_digest()` call, not around the `asyncio.sleep` call. The sleep needs to propagate `CancelledError` freely.

**Warning signs:** Application hangs for seconds on shutdown; `"Task was destroyed but it is pending"` log noise despite `task.cancel()`.

### Pitfall 3: Scheduler task created before event loop is running

**What goes wrong:** `asyncio.create_task()` called at module level (outside an async context) raises `RuntimeError: no running event loop`.

**Why it happens:** Attempting to move the `create_task` call outside of `lifespan` for "cleanliness".

**How to avoid:** Always create the task inside the `lifespan` async context manager or an async function — exactly as D-27 specifies.

### Pitfall 4: `replace()` on a naive datetime compared to an aware datetime

**What goes wrong:** If `datetime.now()` (naive) is used instead of `datetime.now(UTC)` (aware), comparing or subtracting the result against a timezone-aware `target` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.

**Why it happens:** Forgetting the `tz=` parameter or importing UTC but then calling `datetime.now()` without it.

**How to avoid:** Always pass `UTC` to `datetime.now()`. The SCHED-05 requirement and D-26 lock this in.

### Pitfall 5: Long sleep duration in test environments

**What goes wrong:** Unit tests that instantiate the scheduler and `await` it will sleep for up to 24 hours if not cancelled promptly, hanging the test suite.

**Why it happens:** The scheduler's first action is a long sleep (up to 23h59m59s).

**How to avoid:** Tests should cancel the task immediately after creation and check the startup log line; they should not `await` the full execution. Integration tests for the actual send use the manual `/api/digest/send` endpoint instead.

---

## Code Examples

### Complete `app/scheduler.py` reference implementation

```python
"""Digest scheduler — daily asyncio background task.

Computes next wall-clock fire time at DIGEST_HOUR:00 UTC on each
iteration (next-fire calculation, D-21). Miss policy: if started after
DIGEST_HOUR today, waits until tomorrow (D-22).

CancelledError from asyncio.sleep propagates to the caller (lifespan).
Do not suppress it here. Only the send_digest() call gets try/except.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import DIGEST_HOUR
from app.digest import send_digest

UTC = ZoneInfo("UTC")


def _seconds_until_next_fire(hour: int) -> float:
    """Return seconds from now until the next occurrence of `hour`:00:00 UTC.

    Always returns a positive value. If `hour`:00:00 already passed today,
    returns seconds until `hour`:00:00 tomorrow (miss policy D-22).
    """
    now = datetime.now(UTC)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def digest_scheduler() -> None:
    """Run the daily digest on a next-fire loop. Designed for asyncio.create_task().

    Runs until cancelled. CancelledError from asyncio.sleep propagates naturally;
    the lifespan shutdown block suppresses it once (D-23).
    """
    while True:
        seconds = _seconds_until_next_fire(DIGEST_HOUR)
        next_fire = datetime.now(UTC) + timedelta(seconds=seconds)
        print(f"Digest scheduler: next fire at {next_fire.isoformat()}")

        await asyncio.sleep(seconds)  # CancelledError propagates here — do not catch

        try:
            result = await send_digest()
            print(f"Digest scheduler: send_digest completed — {result}")
        except Exception as e:
            print(f"Digest scheduler: send_digest raised exception: {e}")
            # Continue looping; next cycle will fire in ~24 hours
```

### Lifespan additions in `app/main.py`

```python
# Add to imports at top of main.py
from app.config import DIGEST_ENABLED
from app.scheduler import digest_scheduler

# Replace existing lifespan block (lines 28-35)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    watcher.start()
    scheduler_task = asyncio.create_task(digest_scheduler()) if DIGEST_ENABLED else None
    yield
    # Shutdown
    watcher.stop()
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
```

### Config additions in `app/config.py`

```python
# Digest scheduling
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "true").lower() == "true"

try:
    _DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
except ValueError:
    print("Config warning: DIGEST_HOUR is not a valid integer, falling back to 8")
    _DIGEST_HOUR_RAW = -1  # force fallback branch below

if not 0 <= _DIGEST_HOUR_RAW <= 23:
    print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range, falling back to 8")
    DIGEST_HOUR = 8
else:
    DIGEST_HOUR = _DIGEST_HOUR_RAW
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `datetime.utcnow()` | `datetime.now(ZoneInfo("UTC"))` | Aware vs. naive — prevents TypeError in comparisons; SCHED-05 requirement |
| APScheduler | Native `asyncio.create_task` + sleep loop | No extra dependency; sufficient for a single daily task |
| Polling every 60s | Next-fire calculation | No wasted wake-ups; drift-free |

**Deprecated/outdated:**
- `datetime.utcnow()`: Deprecated in Python 3.12 (DeprecationWarning). The codebase uses it widely in non-scheduling code, but all NEW scheduling code must use `datetime.now(ZoneInfo("UTC"))` per SCHED-05.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `int(os.getenv(...))` needs `try/except ValueError` wrapper for non-integer strings | Common Pitfalls / Config Examples | Low — the CONTEXT.md D-28 snippet omits it, so a strict planner could omit it too; if omitted, startup crashes on misconfigured `DIGEST_HOUR` value |

---

## Open Questions

1. **Should `.env.example` and `docker-compose.yml` be updated?**
   - What we know: Both files document all other env vars that config.py exposes. `DIGEST_ENABLED` and `DIGEST_HOUR` are new env vars.
   - What's unclear: Whether the planner should include tasks to update these files as part of Phase 3, or leave them for a docs-cleanup pass.
   - Recommendation: Include as explicit tasks — operators deploy from `.env.example` and `docker-compose.yml`; missing entries cause confusion.

2. **Should `DIGEST_ENABLED` be wired into `docker-compose.yml`?**
   - What we know: Other optional features (`HONEYPOT_INSTANT_BLOCK`, `ABUSEIPDB_AUTO_REPORT`) appear in `docker-compose.yml` environment section.
   - What's unclear: Whether consistency requires adding `DIGEST_ENABLED` and `DIGEST_HOUR` to the compose file.
   - Recommendation: Yes — follow existing pattern; default values in compose match config.py defaults.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | `zoneinfo` stdlib, async support | Yes | 3.12.3 (dev); 3.11 (Docker) | — |
| `zoneinfo` stdlib | SCHED-05 timezone-aware datetime | Yes | Stdlib, Python 3.9+ | — |
| `asyncio` stdlib | SCHED-04 task lifecycle | Yes | Stdlib | — |
| `app/digest.py` `send_digest()` | Scheduler call target | Yes | Built in Phase 2 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

---

## Project Constraints (from CLAUDE.md)

- **Tech stack:** Python 3.11 + FastAPI + SQLite + HTMX — no new frameworks or services.
- **No new external dependencies:** `zoneinfo` and `asyncio` are stdlib; no `pip install` needed.
- **Backwards compatible:** `DIGEST_ENABLED` defaults to `true`; existing deployments without the env var get the scheduler by default. Operators who want to opt out set `DIGEST_ENABLED=false`.
- **Docker / env vars:** New config exposed via env var using `os.getenv()` pattern, consistent with all existing config.
- **Language:** All log messages, print warnings, and comments in English.
- **Naming:** Module `scheduler.py` (lowercase underscores). Public function `digest_scheduler()` (verb-first, lowercase underscores). Private helper `_seconds_until_next_fire()` (underscore prefix).
- **Print-based logging:** No logging library — use `print(f"...")` for startup messages and errors, consistent with existing codebase.
- **No custom exception classes:** Use standard `Exception` in catch clauses.
- **Type hints:** Function parameters and return types annotated consistently.

---

## Sources

### Primary (HIGH confidence)
- Local runtime verification — `zoneinfo.ZoneInfo("UTC")` confirmed available; next-fire calculation verified with edge case test
- `app/main.py` lines 28–35 — existing lifespan block being extended
- `app/config.py` — established `os.getenv` + validation pattern that `DIGEST_HOUR`/`DIGEST_ENABLED` must follow
- `app/digest.py` — `send_digest()` signature confirmed `async def`, returns `dict`
- `03-CONTEXT.md` — all implementation decisions D-21 through D-28

### Secondary (MEDIUM confidence)
- Python docs — `asyncio.CancelledError` is `BaseException` subclass (Python 3.8+), `asyncio.sleep` propagates it without intervention
- Python docs — `datetime.utcnow()` deprecated in Python 3.12; `datetime.now(tz)` is the replacement

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies are stdlib, confirmed available
- Architecture: HIGH — all patterns are locked decisions from CONTEXT.md or directly verifiable in the codebase
- Pitfalls: HIGH — verified against Python stdlib behavior (CancelledError as BaseException, datetime naive/aware mixing rules)

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stdlib patterns are stable; asyncio API has not changed for these primitives since Python 3.7)
