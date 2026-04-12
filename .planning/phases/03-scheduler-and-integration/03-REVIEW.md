---
phase: 03-scheduler-and-integration
reviewed: 2026-04-12T00:00:00Z
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
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-04-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

This review covers the digest scheduler implementation (`app/scheduler.py`), its wiring into the FastAPI lifespan (`app/main.py`), new config knobs (`app/config.py`), compose/env updates, and the scheduler test suite.

The scheduler logic itself is clean: it uses timezone-aware `datetime.now(UTC)`, correctly propagates `CancelledError`, and the next-fire calculation is correct. The lifespan shutdown sequence is well-structured.

Two issues are significant enough to require attention before shipping. The `json` module is used in `app/main.py` (line 811) without ever being imported — this is a runtime `NameError` that will crash the SSE stream endpoint for every connected client. Separately, the test for `_seconds_until_next_fire` when patching `datetime` has a subtle mocking gap that causes the tests to pass for the wrong reason. Three lower-severity findings round out the review.

---

## Critical Issues

### CR-01: `json` module used but never imported in `app/main.py`

**File:** `app/main.py:811`
**Issue:** `json.dumps(data)` is called inside the `event_generator()` generator of the `/api/stream` SSE endpoint, but `json` is not listed in `app/main.py`'s imports (lines 1-16). Every `await asyncio.wait_for(queue.get(), timeout=30.0)` success branch will raise `NameError: name 'json' is not defined`, silently terminating the SSE stream for the connected client. The endpoint itself does not return a 500 — the generator just stops, leaving clients with a stale connection.

**Fix:**
```python
# Add to the import block at the top of app/main.py (after line 1 or grouped with stdlib)
import json
```

---

## Warnings

### WR-01: `datetime` mock in scheduler tests does not patch `timedelta` — tests pass for wrong reason

**File:** `tests/test_scheduler.py:35-41` and `tests/test_scheduler.py:49-57`
**Issue:** `test_seconds_until_next_fire_points_to_tomorrow_when_past` and `test_seconds_until_next_fire_points_to_today_when_future` both patch `app.scheduler.datetime` with a `MagicMock`, replacing it entirely. Inside `_seconds_until_next_fire`, the expression `target += timedelta(days=1)` still resolves to `timedelta` from the real `datetime` module import (`from datetime import datetime, timedelta`). However, `now.replace(...)` calls `mock_dt.now.return_value.replace(...)`, and arithmetic on the mock return value (`target <= now`, `target - now`) operates on `MagicMock` objects, not real `datetime` objects. The tests happen to pass because mock comparisons don't raise exceptions, but they are not actually verifying the computed seconds against a real datetime calculation. A future refactor that changes the comparison logic could silently regress.

**Fix:** Patch only `app.scheduler.datetime.now` rather than the entire `datetime` class, so `timedelta` and `.replace()` continue to operate on real `datetime` objects:
```python
with patch("app.scheduler.datetime") as mock_dt:
    # Ensure replace() and arithmetic work on real datetime objects
    mock_dt.now.return_value = fake_now
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)  # passthrough constructor
    result = _seconds_until_next_fire(8)
```
Or, more robustly, freeze time with `freezegun` or patch only `app.scheduler.datetime.now`:
```python
with patch("app.scheduler.datetime") as mock_dt:
    mock_dt.now.return_value = fake_now
    mock_dt.now.side_effect = None
    # but timedelta must still be accessible — prefer freezegun for this pattern
```

### WR-02: Bare `except:` on `VACUUM` silently swallows all errors including `KeyboardInterrupt`

**File:** `app/main.py:755-756`
**Issue:** The `VACUUM` fallback uses a bare `except:` (no exception type), which catches `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` in addition to database errors. This can prevent clean shutdown in edge cases.
```python
except:
    pass  # VACUUM may fail in some contexts, that's ok
```
**Fix:**
```python
except Exception:
    pass  # VACUUM may fail in some contexts (e.g., active read transaction), that's ok
```

### WR-03: Duplicate environment variable declarations in `docker-compose.yml` and `.env.example`

**File:** `docker-compose.yml:31-38` and `.env.example:65-101`
**Issue:** `DIGEST_ENABLED` and `DIGEST_HOUR` are declared twice each in both files. In `docker-compose.yml`, lines 31-32 and 37-38 are identical. In `.env.example`, the entire "DIGEST SCHEDULING" section (lines 65-76) is copy-pasted verbatim at lines 89-101 under a different heading. This is not a runtime bug (last declaration wins in compose, duplicate keys in `.env` are typically ignored by `python-dotenv` with the first value winning), but it creates operator confusion about which declaration is authoritative and could lead to one copy being updated while the other is not.

**Fix:** Remove the duplicate block. In `docker-compose.yml`, delete lines 36-38. In `.env.example`, delete the second "DIGEST SCHEDULING" section (lines 88-101).

---

## Info

### IN-01: `test_no_utcnow_in_scheduler_source` uses a relative path — fails when pytest is not run from project root

**File:** `tests/test_scheduler.py:89`
**Issue:** `pathlib.Path("app/scheduler.py").read_text()` uses a relative path. If pytest is invoked from any directory other than the project root (e.g., `pytest tests/` from inside `tests/`), this raises `FileNotFoundError` and the test fails with an uninformative error rather than the intended assertion.

**Fix:**
```python
import pathlib
source = (pathlib.Path(__file__).parent.parent / "app" / "scheduler.py").read_text()
```

### IN-02: `ALERT_MIN_SEVERITY` validation prints a warning but does not log at startup when value is valid

**File:** `app/config.py:21-26`
**Issue:** The validation pattern is consistent with the rest of the module, but the valid-path branch emits no startup confirmation. This is a minor observability gap — operators cannot confirm the effective value from logs without setting an invalid one. Not a bug, but worth noting for consistency with `DIGEST_HOUR` which has the same gap.

**Fix:** Consider a single startup summary log at the end of `config.py`:
```python
print(f"Config: ALERT_MIN_SEVERITY={ALERT_MIN_SEVERITY!r}, DIGEST_ENABLED={DIGEST_ENABLED}, DIGEST_HOUR={DIGEST_HOUR}")
```

### IN-03: `_DIGEST_HOUR_RAW = -1` sentinel value is implicit

**File:** `app/config.py:161`
**Issue:** On `ValueError`, `_DIGEST_HOUR_RAW` is set to `-1` as a sentinel to force the subsequent range check to fail. This is functional but opaque — `-1` is a magic number with no comment explaining it. The `not 0 <= _DIGEST_HOUR_RAW <= 23` guard on line 163 also produces a misleading warning message (`DIGEST_HOUR=-1 out of range`) even though the actual invalid value was something non-numeric.

**Fix:**
```python
except ValueError:
    _raw_val = os.getenv('DIGEST_HOUR')
    print(f"Config warning: DIGEST_HOUR={_raw_val!r} is not a valid integer, falling back to 8")
    DIGEST_HOUR = 8  # skip range check entirely
else:
    if not 0 <= _DIGEST_HOUR_RAW <= 23:
        print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range 0-23, falling back to 8")
        DIGEST_HOUR = 8
    else:
        DIGEST_HOUR = _DIGEST_HOUR_RAW
```
This eliminates the sentinel and makes the two error paths independent.

---

_Reviewed: 2026-04-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
