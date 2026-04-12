---
phase: 02-digest-pipeline
plan: 01
subsystem: digest
tags: [digest, aggregation, telegram, html-escape, testing]
requires:
  - app.database.DigestEvent
  - app.telegram_alerter.send_alert
  - app.geoip.lookup_batch
provides:
  - app.digest.send_digest
  - app.digest.build_message
  - tests scaffold (pytest + pytest-asyncio + in-memory SQLite fixture)
affects:
  - Phase 2 Plan 02 (POST /api/digest/send will import send_digest)
  - Phase 2 Plan 03 (preview endpoint will import build_message)
  - Phase 3 scheduler will await send_digest() directly
tech-stack:
  added:
    - pytest==8.0.0 (dev only)
    - pytest-asyncio==0.23.8 (dev only; bumped from 0.23.3 for pytest-8 Package fix)
  patterns:
    - UTF-16 code-unit length measurement for Telegram 4096 limit
    - Per-value html.escape(quote=False) before HTML-tag interpolation
    - Bulk UPDATE with synchronize_session=False after success-gate
    - Reference-based hydration keyed on (source, source_id) logical FK
key-files:
  created:
    - app/digest.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_digest.py
    - requirements-dev.txt
    - pytest.ini
  modified: []
decisions:
  - Orphan detection uses hydrated row COUNT vs. requested id count; rendered as a ⚠ footer line rather than silent drop
  - auth_failures reason (existing repo spelling) mapped to same emoji/label as auth_brute_force so digests stay readable regardless of which convention writes the row
  - Truncation loop is bounded at 4 render passes (10/5/3/3-no-paths); the last attempt is accepted even if still over SAFETY_LIMIT, matching D-15 "whatever fits"
metrics:
  duration: ~35 min
  tasks: 2
  files_touched: 6
  commits: 2
  tests_added: 8
  tests_passing: 8
  completed: 2026-04-12
---

# Phase 2 Plan 01: Digest Pipeline Library Summary

## One-liner

Pure-library digest assembly — queries unsent `digest_events`, hydrates via SQLAlchemy aggregations, renders an HTML-escaped Telegram message bounded to 4000 UTF-16 code units, sends via existing `send_alert`, and batch-stamps `sent_at` only on HTTP 200; ships with pytest scaffold and 8 unit tests covering CONTENT-01..06 + SCHED-03 + D-18.

## What Was Built

**New module `app/digest.py`** implementing:

- `async def send_digest() -> dict` — entrypoint. Opens a SessionLocal, selects `WHERE sent_at IS NULL`, returns `skipped_reason="no_events"` (SCHED-03) when empty, builds the message, calls `await send_alert(message, parse_mode="HTML")`, and runs a bulk `UPDATE ... SET sent_at=utcnow() WHERE id IN (...)` with `synchronize_session=False` only on Telegram 200. Exceptions in `send_alert` are caught and treated as a non-200 failure; rows stay unsent for the next trigger (D-18).
- `async def build_message(db, rows) -> tuple[str, list[int]]` — pure, reusable by the (future) preview endpoint. Splits `source_id`s by source, detects orphans, and delegates to the truncation loop.
- Private section builders: `_build_header`, `_build_blocked_section`, `_build_attack_breakdown`, `_build_top_attackers` (async; calls `lookup_batch` once per render attempt), `_build_traffic_overview`, `_build_footer`.
- `_tg_len(s)` — UTF-16 code-unit count (`len(s.encode("utf-16-le")) // 2`), the exact measurement Telegram uses for its 4096 limit.
- `_esc(s)` — `html.escape(..., quote=False)` applied per-value at interpolation time; structural `<b>`, `<i>`, `<code>` tags are inserted raw.
- `_truncate_if_needed` — iterative rebuild loop per D-15 (attempts `(10,paths)`, `(5,paths)`, `(3,paths)`, `(3,no-paths)`). Accepts the final attempt regardless; the core attack breakdown and counts are never dropped.

**Test scaffold:**

- `requirements-dev.txt` with pinned pytest + pytest-asyncio (dev only; production `requirements.txt` untouched so the Docker image stays slim).
- `pytest.ini` with `asyncio_mode = auto`.
- `tests/conftest.py` — in-memory SQLite `db_session` fixture using `Base.metadata.create_all`, plus `make_intruder`, `make_block`, `make_access`, `make_digest` factories.
- `tests/__init__.py` — empty marker.

**Tests (`tests/test_digest.py`, all 8 passing):**

| Requirement | Test |
|-------------|------|
| SCHED-03 | `test_skip_when_empty` |
| CONTENT-01 | `test_blocked_count` |
| CONTENT-02 | `test_attack_breakdown` |
| CONTENT-03 | `test_top_attackers_ordering` |
| CONTENT-04 | `test_traffic_window` |
| CONTENT-06 | `test_html_escape` |
| CONTENT-05 | `test_truncation` |
| D-18 | `test_sent_at_only_on_success` |

## Verification Results

- `.venv/bin/python -m pytest tests/test_digest.py -x -v` → **8 passed in 0.96s**
- `grep -c "async def send_digest" app/digest.py` → 1
- `grep -c "async def build_message" app/digest.py` → 1
- `grep -c 'encode("utf-16-le")' app/digest.py` → 1
- `grep -c "html.escape" app/digest.py` → 1
- `grep -c "synchronize_session=False" app/digest.py` → 1
- `grep -c "send_alert_sync" app/digest.py` → 0 (correctly absent)
- `grep -cE "DIGEST_HOUR|DIGEST_ENABLED|asyncio.create_task|zoneinfo" app/digest.py` → 0 (Phase 3 scope respected)
- `grep -c 'parse_mode="HTML"' app/digest.py` → 1
- No Phase-1 files modified: `git diff --name-only | grep -E "telegram_alerter|alert_router|database|geoip" | wc -l` → 0
- `git diff requirements.txt` → empty (production image unchanged)
- Truncation test — 200 attacker IPs, final `_tg_len(msg)` ≤ 4000, `+N more` present, attack breakdown preserved
- Escape test — `<script>` absent; `&lt;script&gt;` present; structural tags still present

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest-asyncio 0.23.3 crashed on collection**
- **Found during:** Task 2 verification (`pytest tests/test_digest.py -x -v`)
- **Issue:** `AttributeError: 'Package' object has no attribute 'obj'` from pytest-asyncio 0.23.3's `pytest_collectstart` hook when `tests/__init__.py` is present (pytest 8 collects tests as a Package).
- **Fix:** Bump pin to `pytest-asyncio==0.23.8`, which fixes the Package handling. `tests/__init__.py` is retained because the plan acceptance criteria explicitly require it.
- **Files modified:** `requirements-dev.txt`
- **Commit:** 65920fe (same commit as the module, since the bump is what enabled the test run to pass)

**2. [Rule 2 - Infra] `.venv/` already gitignored; no change needed**
- Local `uv venv --python 3.11 .venv` was used because the system `python3` is 3.12 and `pip` is absent. Verified `.gitignore` already contains `.venv/`, so nothing was committed accidentally.

### Ambiguities Resolved

- **`auth_failures` vs `auth_brute_force` reason strings:** the repo's detector emits `auth_failures` (per `telegram_alerter.py` labels); the plan stub used `auth_brute_force`. Both keys are included in `REASON_LABELS` mapping to the same emoji/label so digests render correctly regardless of which convention a row uses. Non-breaking; protects Phase 3 from a silent UX regression if the detector naming is later unified.
- **IntruderEvent has no dedicated `path` column:** the schema stores attack paths in `details` (String(2048)). The path sample rendered under each top-attacker IP reads `IntruderEvent.details` ordered by most recent timestamp, truncated to 80 chars pre-escape. The `make_intruder` factory stores the `path` kwarg into `details` to keep the test fluent.

## Security Verification (Threat Model)

| Threat | Mitigation Applied | Verified By |
|--------|--------------------|-------------|
| T-02-01 HTML injection via attacker path/host | `_esc()` called per-value at every interpolation; structural tags inserted raw; assembled message never re-escaped | `test_html_escape` (`<script>` absent, `&lt;script&gt;` present) |
| T-02-02 Message-length DoS | `_tg_len` uses UTF-16 code units; 4000-unit margin; iterative truncation loop | `test_truncation` (_tg_len ≤ 4000 for 200 IPs) |
| T-02-03 Malformed entity parse error | Stdlib `html.escape` handles `&`, `<`, `>` | Covered by T-02-01 test |
| T-02-04 Token leakage in logs | Reuse `send_alert`; digest only prints counts/status, never payload body | Code inspection — only `print(f"Digest send failed: ...")` with counts |
| T-02-05 SQL injection in aggregations | 100% SQLAlchemy ORM `filter(col.in_(ids))` / `between(min, max)`; no `text()` | Code inspection |
| T-02-06 Duplicate digest on rare DB-after-Telegram failure | Accepted per D-18 | Documented; no code change |
| T-02-07 Oversized path reflection | Pre-escape truncation to 80 chars in `_build_top_attackers` | Code inspection |

No new threat flags discovered — all security-relevant surfaces added in this plan were enumerated in the plan's threat model.

## Known Stubs

None. All rendered sections are wired to real data sources; the `lookup_batch` geoip call gracefully degrades to `🏳️` when the service is unavailable (runtime-only concern, not a stub).

## Self-Check: PASSED

- FOUND: `app/digest.py`
- FOUND: `tests/test_digest.py`
- FOUND: `tests/conftest.py`
- FOUND: `tests/__init__.py`
- FOUND: `requirements-dev.txt`
- FOUND: `pytest.ini`
- FOUND commit: 17103d2 (test scaffold)
- FOUND commit: 65920fe (digest module + tests)
- All 8 unit tests pass (`pytest tests/test_digest.py -x -v` → 8 passed)

## Commits

| Hash | Message |
|------|---------|
| 17103d2 | test(02-01): add pytest scaffold + in-memory SQLite fixture |
| 65920fe | feat(02-01): add digest pipeline library with unit coverage |

## Follow-ups for Plan 02-02 / 02-03

- Plan 02-02 wires `POST /api/digest/send` — imports `from app.digest import send_digest` and returns its dict directly; no modifications to `app/digest.py` needed.
- Plan 02-03 adds a preview endpoint — can import `build_message` and reuse the existing hydration/truncation path; must NOT stamp `sent_at`.
- Phase 3 scheduler: `await send_digest()` is already safe from an `asyncio.create_task` inside the FastAPI lifespan (no `asyncio.run()` is ever called from `send_digest`).
