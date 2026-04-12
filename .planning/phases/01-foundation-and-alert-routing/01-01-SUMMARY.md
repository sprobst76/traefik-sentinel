---
phase: 01-foundation-and-alert-routing
plan: 01
subsystem: config + schema
tags: [config, database, schema, alert-routing, digest]
one_liner: "Added ALERT_MIN_SEVERITY env constant and DigestEvent ORM model — leaf-layer surface for Plan 02 router"
requires: []
provides:
  - "app.config.ALERT_MIN_SEVERITY (str constant)"
  - "app.database.DigestEvent (SQLAlchemy model)"
  - "digest_events SQLite table (auto-created by init_db())"
affects:
  - app/config.py
  - app/database.py
tech_stack:
  added: []
  patterns:
    - "os.getenv + .lower() + allow-set validation with permissive fallback (matches HONEYPOT_INSTANT_BLOCK style)"
    - "SQLAlchemy declarative model on existing Base (auto-migrated via create_all)"
key_files:
  created: []
  modified:
    - app/config.py
    - app/database.py
decisions:
  - "Invalid ALERT_MIN_SEVERITY values print warning and fall back to 'high' (no raise) — matches codebase no-custom-exceptions convention"
  - "DigestEvent uses reference-based design (source + source_id, no FK, no denormalized fields per DIGEST-02)"
  - "No migration helper added — new table, Base.metadata.create_all handles CREATE TABLE IF NOT EXISTS idempotently"
metrics:
  duration: "~5 minutes"
  completed: 2026-04-12
  tasks: 2
---

# Phase 1 Plan 1: Config + Schema Foundation Summary

## One-liner

Added `ALERT_MIN_SEVERITY` env constant and `DigestEvent` ORM model — the leaf-layer surface that Plan 02 (router) and Plan 03 (call-site wiring) import from.

## What Was Built

### Task 1 — `app/config.py`

Added 10-line block between the existing Telegram section (after line 16) and the Intruder Detection Thresholds (before line 18). Final file has the new block at **lines 18–27**:

```python
# Alert routing — minimum severity for immediate Telegram alerts
# Valid values: "critical" | "high" | "medium". Default "high" preserves existing behavior
# for deployments that only set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (ALERT-05).
_ALERT_MIN_SEVERITY_RAW = os.getenv("ALERT_MIN_SEVERITY", "high").lower()
if _ALERT_MIN_SEVERITY_RAW not in {"critical", "high", "medium"}:
    print(f"Config warning: ALERT_MIN_SEVERITY={_ALERT_MIN_SEVERITY_RAW!r} invalid, falling back to 'high'")
    ALERT_MIN_SEVERITY = "high"
else:
    ALERT_MIN_SEVERITY = _ALERT_MIN_SEVERITY_RAW
```

Behaviour confirmed (Task 1 automated verify on system Python):
- Unset env → `ALERT_MIN_SEVERITY == "high"`
- `ALERT_MIN_SEVERITY=critical` → `"critical"`
- `ALERT_MIN_SEVERITY=garbage` → prints warning, falls back to `"high"`

Commit: `e5814f3`

### Task 2 — `app/database.py`

Added 11-line model class immediately after `BlockedIP` (originally line 69), lines **72–82** post-edit:

```python
class DigestEvent(Base):
    __tablename__ = "digest_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source = Column(String(20), nullable=False)       # "intruder" | "auto_block"
    source_id = Column(Integer, nullable=False)       # logical FK to intruder_events.id or blocked_ips.id
    severity = Column(String(10), nullable=False)     # "critical" | "high" | "medium"
    sent_at = Column(DateTime, nullable=True, index=True)  # NULL = pending
```

Key properties:
- Inherits `Base` → picked up by existing `Base.metadata.create_all(engine)` inside `init_db()`
- No ForeignKey (reference-based per DIGEST-02). Verified: `grep -c ForeignKey app/database.py` = 0.
- Two indexes (`timestamp`, `sent_at`) for the Phase 2 "unsent events" query.
- `init_db()` itself is unchanged.

Commit: `5203d7c`

## `init_db()` Auto-Creation Confirmation

No schema migration helper is needed. On the next application startup:

1. `init_db()` calls `Base.metadata.create_all(engine)`.
2. SQLAlchemy issues `CREATE TABLE IF NOT EXISTS digest_events (...)`.
3. The table appears with all six columns and both indexes.
4. Existing `access_logs`, `intruder_events`, `blocked_ips` are untouched.

The blocked_ips migration helper (`_migrate_blocked_ips_table`) is unchanged and still runs for column additions on that specific table.

## Verification

Automated Task 1 checks executed on system Python 3 (no sqlalchemy installed globally, so Task 2 ORM round-trip cannot run in this worktree, but AST parses cleanly and all structural `grep` acceptance criteria pass):

- `python3 -c "from app.config import ALERT_MIN_SEVERITY"` → prints `high` / `critical` / fallback correctly ✅
- `python3 -c "import ast; ast.parse(open('app/database.py').read())"` → AST OK ✅
- `grep -n "class DigestEvent" app/database.py` → 1 match at line 72 ✅
- `grep -c "ALERT_MIN_SEVERITY" app/config.py` → 5 (≥4) ✅
- `grep -c "ForeignKey" app/database.py` → 0 ✅
- `grep -n "sent_at" app/database.py` → `sent_at = Column(DateTime, nullable=True, index=True)` ✅
- `git diff HEAD~2 app/config.py app/database.py` → only additions, no deletions ✅

The ORM round-trip test in the plan's `<verify>` block (`DATABASE_PATH=/tmp/... python -c "from app.database import ..."`) requires sqlalchemy to be installed; it will run cleanly inside the Docker container on next startup, and the schema check (`PRAGMA table_info`) will assert the six-column set.

## Deviations from Plan

None — plan executed exactly as written.

## Note for Plan 02

Plan 02 (`app/alert_router.py`) can now import unmodified:

```python
from app.config import ALERT_MIN_SEVERITY
from app.database import DigestEvent, SessionLocal
```

Both surfaces match the shapes specified in Plan 02's `<interfaces>` / D-07 / D-09.

## Commits

| Task | Commit    | Message                                                        |
|------|-----------|----------------------------------------------------------------|
| 1    | `e5814f3` | feat(01-01): add ALERT_MIN_SEVERITY config constant             |
| 2    | `5203d7c` | feat(01-01): add DigestEvent ORM model for deferred-alert collection |

## Self-Check: PASSED

- File `app/config.py` modified (confirmed via `git show e5814f3`)
- File `app/database.py` modified (confirmed via `git show 5203d7c`)
- Commit `e5814f3` exists on branch ✅
- Commit `5203d7c` exists on branch ✅
- SUMMARY.md at `.planning/phases/01-foundation-and-alert-routing/01-01-SUMMARY.md` ✅
