---
phase: 03-scheduler-and-integration
fixed_at: 2026-04-12T00:00:00Z
review_path: .planning/phases/03-scheduler-and-integration/03-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-04-12T00:00:00Z
**Source review:** .planning/phases/03-scheduler-and-integration/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (1 Critical, 3 Warning)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `json` module used but never imported in `app/main.py`

**Files modified:** `app/main.py`
**Commit:** 4cb0392
**Applied fix:** Added `import json` to the stdlib import block at the top of `app/main.py` (line 2, alphabetically between `asyncio` and `socket`). This resolves the `NameError: name 'json' is not defined` that would crash the SSE stream generator on every successful `queue.get()`.

---

### WR-01: `datetime` mock in scheduler tests does not patch `timedelta` — tests pass for wrong reason

**Files modified:** `tests/test_scheduler.py`
**Commit:** dcbcba8
**Applied fix:** Added `mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)` to both `test_seconds_until_next_fire_points_to_tomorrow_when_past` and `test_seconds_until_next_fire_points_to_today_when_future`. This passthrough constructor ensures that `now.replace(...)` returns a real `datetime` object (not a `MagicMock`), so the subsequent `target <= now` comparison and `(target - now).total_seconds()` arithmetic operate on real datetime values. Tests now verify the actual computed seconds rather than passing vacuously through mock comparisons.

---

### WR-02: Bare `except:` on `VACUUM` silently swallows all errors including `KeyboardInterrupt`

**Files modified:** `app/main.py`
**Commit:** 7bbf789
**Applied fix:** Changed `except:` to `except Exception:` in the VACUUM fallback block at line 756. Also updated the comment to be more specific about the expected failure mode (`e.g., active read transaction`). This prevents `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` from being swallowed during shutdown.

---

### WR-03: Duplicate environment variable declarations in `docker-compose.yml` and `.env.example`

**Files modified:** `docker-compose.yml`, `.env.example`
**Commit:** 1b62704
**Applied fix:** Removed the second duplicate `# Digest scheduling` block (lines 36-38) from `docker-compose.yml`. Removed the entire second `# DIGEST SCHEDULING (Phase 3)` section (lines 88-101) from `.env.example`. Each variable now appears exactly once in both files, with the first (more detailed, commented) declaration retained.

---

_Fixed: 2026-04-12T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
