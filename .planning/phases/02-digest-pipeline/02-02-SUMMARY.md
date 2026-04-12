---
phase: 02-digest-pipeline
plan: 02
subsystem: digest
tags: [fastapi, endpoint, digest, manual-trigger, http]
requires:
  - app.digest.send_digest
  - FastAPI app instance in app.main
provides:
  - POST /api/digest/send (D-17 manual trigger)
affects:
  - Phase 3 scheduler can reuse the same send_digest import path (already designed)
tech-stack:
  added: []
  patterns:
    - httpx.AsyncClient + ASGITransport for in-process endpoint tests
    - monkeypatch of app.digest.SessionLocal / send_alert / lookup_batch to isolate the HTTP layer
key-files:
  created:
    - tests/test_digest_endpoint.py
  modified:
    - app/main.py
decisions:
  - Endpoint is a 3-line passthrough (return await send_digest()) — all logic stays in app/digest.py per D-19
  - No auth middleware, no body, no query params — matches /api/blocklist posture per D-17 (accepted threat T-02-E01)
  - Test-only _NoCloseWrap shim keeps the in-memory fixture session alive when send_digest calls SessionLocal().close()
metrics:
  duration: ~15 min
  tasks: 1
  files_touched: 2
  commits: 2
  tests_added: 3
  tests_passing: 11
  completed: 2026-04-12
---

# Phase 2 Plan 02: Manual Digest Trigger Endpoint Summary

## One-liner

Thin FastAPI passthrough `POST /api/digest/send` that calls `app.digest.send_digest()` and returns its dict verbatim, with 3 async integration tests covering empty / success / Telegram-failed paths via `httpx.AsyncClient` + `ASGITransport`.

## What Was Built

**`app/main.py` (2 additions, +8 lines):**
- Import: `from app.digest import send_digest` next to the other `app.xxx` imports.
- Route: `@app.post("/api/digest/send")` → `async def trigger_digest(): return await send_digest()`, placed between `/api/retention/cleanup` and `/api/stream` to group with other POST operations. No `Depends`, no body schema, no query params.

**`tests/test_digest_endpoint.py` (new, 3 tests):**

| Test | Asserts |
|------|---------|
| `test_endpoint_empty_returns_no_events` | 200 + exact `{sent:false, event_count:0, skipped_reason:"no_events", telegram_ok:false, message:null}`; `send_alert` is guarded with `_boom` that would raise if called |
| `test_endpoint_success` | Seeds 2 intruder + 1 auto_block + matching source/access rows, stubs `send_alert → True`; asserts `sent=true`, `event_count=3`, `telegram_ok=true`, `skipped_reason=null`, message contains `<b>` and `🛡️`; verifies D-18 stamping (`unsent == 0`) |
| `test_endpoint_telegram_failure` | Stubs `send_alert → False`; asserts 200 HTTP success with `sent=false`, `skipped_reason="telegram_failed"`, `telegram_ok=false`; verifies D-18 non-stamping on failure (`unsent == 1`) |

`_NoCloseWrap` shim lets the tests hand a single in-memory session to `send_digest` while keeping the pytest fixture's close/dispose lifecycle intact.

## Verification Results

- `.venv/bin/python -m pytest tests/test_digest_endpoint.py -x -v` → **3 passed in 0.53s**
- `.venv/bin/python -m pytest -x` (full suite) → **11 passed in 1.14s** (8 from Plan 02-01 + 3 new)
- `grep -c '@app.post("/api/digest/send")' app/main.py` → 1
- `grep -c "from app.digest import send_digest" app/main.py` → 1
- `grep -c "async def trigger_digest" app/main.py` → 1
- `git diff --cached app/main.py` at commit time → exactly 2 hunks (import + route), no other logic changed
- `git log --stat` confirms: no modifications to `app/digest.py`, `app/telegram_alerter.py`, `app/alert_router.py`, `app/database.py`
- Endpoint has no `Depends`, no auth middleware — matches `/api/blocklist` style per D-17

## Deviations from Plan

None — plan executed exactly as written. TDD RED → GREEN cycle completed; no REFACTOR pass needed (endpoint body is 3 lines).

### Notes on working-tree state

At the start of execution the working tree already contained pre-existing uncommitted modifications to `app/main.py`, `templates/index.html`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/config.json` (SSE JSON-encoding fix, favicon, CORS headers, state bookkeeping) that were **not** part of this plan. To keep commit 5f3ef03 strictly scoped to Plan 02-02, the endpoint was staged via a targeted `git apply --cached` patch containing only the import + route hunks; the unrelated pre-existing hunks were left in the working tree untouched for the user to handle separately.

## Security Verification (Threat Model)

| Threat | Disposition | Verified By |
|--------|-------------|-------------|
| T-02-E01 Spoofing / no auth | accept (D-17 explicit) | Matches existing dashboard posture; no code change required |
| T-02-E02 DoS via flood | accept (internal-only by deployment) | Flood sends at most 1 real digest per unsent-batch; rest return `no_events` |
| T-02-E03 Info disclosure via response body | mitigate | Message assembled by `build_message` (Plan 02-01) which HTML-escapes all attacker fields via `_esc()`; endpoint passes the dict through without additional exposure |
| T-02-E04 Tampering via request body | mitigate | FastAPI signature `async def trigger_digest()` takes no arguments; extra body/query input is ignored by the framework |

No new threat flags discovered.

## Known Stubs

None. The endpoint is fully wired; test stubs (`_NoCloseWrap`, fake `send_alert`, fake `lookup_batch`) live in `tests/` and never ship in production.

## Self-Check: PASSED

- FOUND: `app/main.py` (route + import present)
- FOUND: `tests/test_digest_endpoint.py`
- FOUND commit: 6f08766 (test RED)
- FOUND commit: 5f3ef03 (endpoint GREEN)
- 11/11 tests passing across the suite

## Commits

| Hash | Message |
|------|---------|
| 6f08766 | test(02-02): add failing integration tests for POST /api/digest/send |
| 5f3ef03 | feat(02-02): add POST /api/digest/send manual trigger endpoint |

## Follow-ups for Plan 02-03 / Phase 3

- Plan 02-03 (preview endpoint) can mirror this pattern: import `build_message`, add a GET route returning the assembled string without sending / without stamping `sent_at`.
- Phase 3 scheduler will `await send_digest()` directly via the same import — no HTTP round-trip required, exactly as designed in Plan 02-01.
- Pre-existing uncommitted changes in `app/main.py` (SSE JSON encoding, CORS headers) and `templates/index.html` are unrelated to this plan and remain in the working tree for separate handling.
