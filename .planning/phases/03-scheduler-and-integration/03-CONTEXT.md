# Phase 3: Scheduler and Integration - Context

**Gathered:** 2026-04-12
**Mode:** interactive (--chain)
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire an asyncio background task into the existing FastAPI lifespan that calls `send_digest()` (built in Phase 2) automatically at the wall-clock hour configured via `DIGEST_HOUR`. The scheduler must start cleanly at app startup, shut down without orphaned tasks, and use timezone-aware `datetime` with `zoneinfo`. No dashboard UI changes.

Covers requirements: SCHED-01, SCHED-02, SCHED-04, SCHED-05.

**Out of scope:** Digest content changes (Phase 2), `DIGEST_TIMEZONE` env var (v2 / ADV-05), alternative notification channels (v2).

</domain>

<decisions>
## Implementation Decisions

### Scheduler Loop Design

- **D-21:** Scheduler uses **next-fire calculation**, not a polling loop. On startup, compute `seconds_until_next_fire = seconds until the next occurrence of DIGEST_HOUR:00:00 in UTC`. Sleep that duration, fire `send_digest()`, then compute the next fire time and loop. This is drift-free, correct across DST, and avoids no-op wake-ups every 60 seconds.
- **D-22:** **Miss policy: wait until tomorrow.** If the application starts after `DIGEST_HOUR` has already passed for the current day (e.g., `DIGEST_HOUR=8` and startup is at 08:05 UTC), the scheduler computes the next fire as `DIGEST_HOUR:00:00 the following day` and waits. No surprise digest on container restart. The manual `/api/digest/send` endpoint remains available if the operator needs an immediate send after a restart.

### Shutdown / Cancellation

- **D-23:** Store the `asyncio.Task` returned by `asyncio.create_task(_digest_scheduler())` in a module-level or lifespan-local variable. In the lifespan shutdown block:
  ```python
  _scheduler_task.cancel()
  try:
      await _scheduler_task
  except asyncio.CancelledError:
      pass
  ```
  This is idiomatic asyncio and prevents `Task was destroyed but it is pending` log noise. The scheduler coroutine must **not** suppress `asyncio.CancelledError` internally (the `sleep` already propagates it correctly).

### DIGEST_HOUR + DIGEST_ENABLED Config

- **D-24:** `DIGEST_HOUR` accepts an **integer string only** (e.g., `"8"` → hour 8, fires at 08:00 UTC). Minutes are always :00. Validation at load time: must be 0–23; invalid value falls back to `8` with a `print()` warning, matching the existing `ALERT_MIN_SEVERITY` validation pattern in `config.py`.
- **D-25:** `DIGEST_ENABLED` defaults to `"true"`. When `false`, the scheduler task is **not started** at all (the `create_task` call is guarded by `if DIGEST_ENABLED`). It does **not** suppress the manual `/api/digest/send` or `/api/digest/preview` endpoints — those remain available for operator testing and one-off sends regardless of this flag.

### Timezone Handling

- **D-26:** All scheduling datetime arithmetic uses `zoneinfo.ZoneInfo("UTC")` explicitly — no `datetime.utcnow()` calls in scheduling code. Implementation pattern:
  ```python
  from zoneinfo import ZoneInfo
  UTC = ZoneInfo("UTC")
  now = datetime.now(UTC)
  ```
  `DIGEST_TIMEZONE` env var is **deferred to v2** (per ADV-05 in REQUIREMENTS.md). Phase 3 hardcodes UTC so the code is timezone-correct without exposing an additional config knob.

### Lifespan Integration

- **D-27:** The scheduler is wired into the existing `lifespan` context manager in `app/main.py` (currently lines 28–34). Pattern:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Startup
      init_db()
      watcher.start()
      scheduler_task = asyncio.create_task(_digest_scheduler()) if DIGEST_ENABLED else None
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
  The scheduler loop itself (`_digest_scheduler`) lives in a new module `app/scheduler.py` (not inline in `main.py`) to keep `main.py` focused on routes. `main.py` imports and calls it.

### Config Surface (Phase 3)

- **D-28:** Add to `app/config.py`:
  ```python
  DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "true").lower() == "true"
  _DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
  if not 0 <= _DIGEST_HOUR_RAW <= 23:
      print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range, falling back to 8")
      DIGEST_HOUR = 8
  else:
      DIGEST_HOUR = _DIGEST_HOUR_RAW
  ```
  No other new env vars in this phase.

### Claude's Discretion

- Exact module-level structure of `app/scheduler.py` (helper function names, loop variable names).
- Whether to add a startup log line (`print("Digest scheduler started, next fire at ...")`) — recommended yes for operator visibility.
- Whether to catch and log exceptions raised by `send_digest()` inside the loop (recommended yes — a failed send should not crash the scheduler; log and continue to next cycle).
- Whether to return a result from `send_digest()` and log it in the scheduler (recommended yes — aids debugging without requiring Telegram access to verify).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-Level
- `.planning/PROJECT.md` — vision, constraints (no stack changes, backwards compat, Docker env vars)
- `.planning/REQUIREMENTS.md` — SCHED-01, SCHED-02, SCHED-04, SCHED-05 verbatim
- `.planning/ROADMAP.md` §"Phase 3" — goal + 4 success criteria
- `CLAUDE.md` — conventions (snake_case, PEP 8, print logging, no custom exceptions)

### Prior Phase Artifacts (must stay honored)
- `.planning/phases/01-foundation-and-alert-routing/01-CONTEXT.md` — D-01..D-11
- `.planning/phases/02-digest-pipeline/02-CONTEXT.md` — D-12..D-20 (especially D-19: `send_digest` is `async def`, safe to call from running loop)

### Files to read
- `app/main.py:28-34` — existing lifespan block being extended
- `app/config.py` — add `DIGEST_ENABLED` + `DIGEST_HOUR` following established `os.getenv` + validation pattern
- `app/digest.py` — `send_digest()` signature and return shape (D-17 from Phase 2 context)

### Files to create
- `app/scheduler.py` — new module with `_digest_scheduler()` coroutine

### Files to modify
- `app/main.py` — import and wire scheduler into lifespan
- `app/config.py` — add `DIGEST_ENABLED`, `DIGEST_HOUR`

### Standard library references
- `zoneinfo` (Python 3.9+, included in 3.11 slim image) — for timezone-aware datetime
- `asyncio` — `create_task`, `sleep`, `CancelledError`

No external ADRs/specs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/main.py:28-34` — `lifespan` context manager; extend with scheduler task start/stop (D-27).
- `app/digest.py:send_digest()` — already `async def`, designed for direct call from scheduler (D-19 from Phase 2).
- `app/config.py` — established `os.getenv` + validation + fallback pattern; `DIGEST_HOUR` / `DIGEST_ENABLED` follow the same form as `ALERT_MIN_SEVERITY`.

### Established Patterns
- `asyncio.create_task()` already used in `app/main.py` (lines 779, 794) for the SSE queue — scheduler follows same pattern.
- `watcher.start()` / `watcher.stop()` in lifespan is the template for start/stop lifecycle management.
- Print-based logging (`print(f"...")`) for startup messages and errors.
- No `asyncio.Queue`, no thread pools — pure async loop.

### Integration Points
- Lifespan in `app/main.py:28-34` — the only change to `main.py` is the `create_task` call and its cancellation in shutdown.
- `app/config.py` — two new constants (`DIGEST_ENABLED`, `DIGEST_HOUR`) loaded at import time.

</code_context>

<specifics>
## Specific Ideas

- Startup log line: `print(f"Digest scheduler started — next fire at {next_fire.isoformat()}")` so the operator can see the scheduled time in container logs immediately on startup.
- Failed digest log: `print(f"Digest send failed: {e}")` inside a `try/except Exception` around the `send_digest()` call — keeps the scheduler running on transient Telegram failures.
- The sleep duration could be long (up to 24h). That is fine — `asyncio.sleep` with long durations is supported and the task will be cancelled cleanly by `task.cancel()` during shutdown regardless of how far through the sleep it is.

</specifics>

<deferred>
## Deferred Ideas

- `DIGEST_TIMEZONE` env var (e.g., `"Europe/Berlin"`) — v2 per ADV-05 in REQUIREMENTS.md. The code uses `zoneinfo` so adding this later is a one-liner change.
- Sub-hour digest granularity (`DIGEST_HOUR` as `HH:MM`) — not needed for a daily summary.
- Multiple digest schedules (e.g., hourly or 4-hour) — v2 per ADV-04.
- `DIGEST_ENABLED=false` suppressing the manual endpoint — user confirmed: manual always works.

</deferred>

---

*Phase: 03-scheduler-and-integration*
*Context gathered: 2026-04-12 (--chain, interactive)*
