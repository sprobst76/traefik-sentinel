---
phase: 03-scheduler-and-integration
fixed_at: 2026-04-12T19:10:00Z
review_path: .planning/phases/03-scheduler-and-integration/03-REVIEW.md
iteration: 2
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-04-12T19:10:00Z
**Source review:** .planning/phases/03-scheduler-and-integration/03-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 3
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-01: `datetime.utcnow()` used in ten places in `app/main.py`

**Files modified:** `app/main.py`
**Commit:** 2affc43
**Applied fix:** Added `from zoneinfo import ZoneInfo` import and `_UTC = ZoneInfo("UTC")` module-level constant. Replaced all ten `datetime.utcnow()` calls with `datetime.now(_UTC).replace(tzinfo=None)` to preserve the naive-datetime contract for SQLAlchemy while eliminating the deprecated call. Affected locations: lines 65, 106, 136, 167, 266, 312, 660, 661, 662, and 718 (pre-edit line numbers).

### WR-02: `RATE_LIMIT_REQUESTS` default mismatch between `config.py` (500) and operator-facing files (100)

**Files modified:** `app/config.py`
**Commit:** f7edb4a
**Applied fix:** Changed the Python fallback in `config.py` from `"500"` to `"100"` and removed the now-inaccurate `# Higher for normal web usage` comment. `docker-compose.yml` and `.env.example` already specified `100`, so no changes were needed in those files — they were already correct.

### WR-03: `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` missing from `docker-compose.yml` environment block

**Files modified:** `docker-compose.yml`
**Commit:** 4e6e211
**Applied fix:** Added `- RETENTION_BLOCKED_IPS_INACTIVE_DAYS=${RETENTION_BLOCKED_IPS_INACTIVE_DAYS:-180}` immediately after the `RETENTION_INTRUDER_EVENTS_DAYS` line in the environment block, matching the default value already defined in `config.py` and documented in `.env.example`.

---

_Fixed: 2026-04-12T19:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
