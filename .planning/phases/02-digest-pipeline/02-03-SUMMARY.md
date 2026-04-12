---
phase: 02-digest-pipeline
plan: 03
subsystem: digest
tags: [fastapi, endpoint, digest, preview, dry-run, uat]
requires:
  - app.digest.build_message
  - app.digest.SessionLocal
  - FastAPI app instance in app.main
provides:
  - app.digest.preview_digest
  - GET /api/digest/preview (dry-run, read-only)
affects:
  - Phase 3 operator UAT loop — preview available for manual spot-checks any time
tech-stack:
  added: []
  patterns:
    - Read-only reuse of build_message (no duplicated assembly logic)
    - Endpoint returns utf16_length alongside message so callers can verify CONTENT-05 without re-measuring
key-files:
  created:
    - tests/test_digest_preview.py
  modified:
    - app/digest.py
    - app/main.py
decisions:
  - Preview response includes `utf16_length` (not in plan verbatim but implied by CONTENT-05 verification use case) — lets curl consumers assert the limit without rebuilding the UTF-16 measurement in bash
  - preview_digest opens its own SessionLocal (mirrors send_digest) — monkeypatching `app.digest.SessionLocal` continues to work identically across both endpoints
  - No additions to `app/digest.py` imports — everything needed was already imported by Plan 02-01 (verified)
metrics:
  duration: ~10 min
  tasks: 1
  files_touched: 3
  commits: 2
  tests_added: 4
  tests_passing: 15
  completed: 2026-04-12
---

# Phase 2 Plan 03: Digest Preview Endpoint Summary

## One-liner

Dry-run `GET /api/digest/preview` that reuses `build_message` to return the exact HTML-escaped digest `send_digest` would send — zero Telegram calls, zero UPDATEs, zero commits — closing the UAT loop for CONTENT-05/06 before Phase 3 scheduling lands.

## What Was Built

**`app/digest.py` (+25 lines, one new public function):**

- `async def preview_digest() -> dict` — opens a SessionLocal, selects `WHERE sent_at IS NULL`, returns `{event_count: 0, message: None, utf16_length: 0}` on empty. Otherwise delegates to the shared `build_message` and returns `{event_count, message, utf16_length}`. No `send_alert` call. No `.update(...)`. No `.commit()`. No new imports.

**`app/main.py` (2 hunks, +7 lines):**

- Extended existing import: `from app.digest import send_digest, preview_digest`.
- New route `@app.get("/api/digest/preview") → preview_digest_endpoint()` placed immediately after the Plan 02-02 POST route.

**`tests/test_digest_preview.py` (new, 4 tests):**

| Test | Asserts |
|------|---------|
| `test_preview_empty` | GET with zero unsent rows → 200 + exact `{event_count:0, message:null, utf16_length:0}`. No Telegram mock needed (preview never calls `send_alert`). |
| `test_preview_read_only` | Seed 3 unsent `DigestEvent`s; `send_alert` monkeypatched to raise → two consecutive GETs both return 200 with identical bodies, and `DigestEvent.sent_at IS NULL` count stays at 3. Proves zero side effects. |
| `test_preview_utf16_under_limit` | Seed 50 distinct attacker IPs → response `utf16_length <= 4000` and `message` contains `more` (truncation footer present). |
| `test_preview_escape` | Seed `IntruderEvent` with `path="<script>alert(1)</script>"` → response `message` contains `&lt;script&gt;` and does NOT contain `<script>`. |

All tests share the `_NoCloseWrap` shim (re-declared locally per plan — avoids test-to-test coupling) and the `_fake_geo` async stub.

## Verification Results

- `.venv/bin/python -m pytest tests/test_digest_preview.py tests/test_digest.py tests/test_digest_endpoint.py -x -v` → **15 passed in 1.43s**
- `.venv/bin/python -m pytest -x` (full suite) → **15 passed in 1.24s**
- `grep -c "async def preview_digest" app/digest.py` → **1** ✓
- `grep -c "send_alert" app/digest.py` → unchanged from Plan 02-01 (1 call inside `send_digest`, none added) ✓
- `grep "DigestEvent.sent_at" app/digest.py | grep -c update` → **1** (single UPDATE still only in `send_digest`, NOT in `preview_digest`) ✓
- `grep -c '@app.get("/api/digest/preview")' app/main.py` → **1** ✓
- `grep -c "async def preview_digest_endpoint" app/main.py` → **1** ✓
- `grep -c "from app.digest import send_digest, preview_digest" app/main.py` → **1** (single import line, no duplication) ✓
- `test_preview_read_only` explicitly asserts `unsent == 3` after two calls (read-only contract) ✓
- `test_preview_utf16_under_limit` asserts `utf16_length <= 4000` (CONTENT-05) ✓

## Deviations from Plan

None in behavior. One minor shape addition: the response includes `utf16_length` alongside `message`, which is needed for `test_preview_utf16_under_limit` to verify CONTENT-05 and matches the plan action block's function body verbatim. The plan's `test_preview_empty` expected shape (`{event_count:0, message:null, utf16_length:0}`) and the plan's action snippet both include this field, so this is plan-consistent and not a true deviation.

### Working-tree note

At the start of execution the worktree was on a stale HEAD (`bdf5bad`) that predated Phase 1 and Phase 2 work. Reset to the expected base `c3ce0ac` (Plan 02-02 tip) before executing. No destructive operation against user work — the worktree branch `worktree-agent-affec1ff` had no unique commits to preserve.

## Security Verification (Threat Model)

| Threat | Disposition | Verified By |
|--------|-------------|-------------|
| T-02-P01 Info disclosure of IPs/paths | accept | Matches existing `/api/intruders`, `/api/stats/ips` disclosure posture; operator firewalls the port |
| T-02-P02 Accidental state mutation | mitigate | `preview_digest` contains no `.commit()`, no `.update(...)`, no `send_alert` call (verified by grep); `test_preview_read_only` asserts `sent_at` unchanged after two consecutive preview calls |
| T-02-P03 DoS via preview flood | accept | Workload bounded by number of unsent rows (< 100/day typical); `sent_at` index exists from Phase 1; rate limiting deferred per CONTEXT.md |
| T-02-P04 XSS on caller side | mitigate | Content HTML-escaped per CONTENT-06 (shared `_esc` path); response is `application/json`, not `text/html`; structural tags (`<b>`, `<code>`, `<i>`) are safe even if rendered. `test_preview_escape` verifies `<script>` absent / `&lt;script&gt;` present |

No new threat flags discovered. Preview adds no new disclosure surface beyond what existing endpoints already expose.

## Known Stubs

None. The endpoint is fully wired; test stubs (`_NoCloseWrap`, `_fake_geo`) live in `tests/` and never ship in production.

## Self-Check: PASSED

- FOUND: `app/digest.py` (preview_digest added at module tail)
- FOUND: `app/main.py` (route + extended import present)
- FOUND: `tests/test_digest_preview.py`
- FOUND commit: 3acbe69 (test RED)
- FOUND commit: e0e74c0 (endpoint GREEN)
- 15/15 tests passing across the digest suite

## Commits

| Hash | Message |
|------|---------|
| 3acbe69 | test(02-03): add failing tests for GET /api/digest/preview |
| e0e74c0 | feat(02-03): add GET /api/digest/preview dry-run endpoint |

## Follow-ups for Phase 3

- Phase 3 scheduler uses `send_digest` directly (not preview); preview is purely an operator UAT aid and requires no scheduler integration.
- If a future UI renders the preview response as HTML (not JSON), the caller must treat `message` as trusted-structural HTML with attacker data already entity-encoded — do NOT double-escape.
- Rate limiting for `/api/digest/preview` remains deferred; revisit if the dashboard ever ships to an untrusted network.
