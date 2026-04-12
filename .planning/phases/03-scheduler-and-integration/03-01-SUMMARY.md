---
phase: 03-scheduler-and-integration
plan: 01
subsystem: config
tags: [config, scheduler, env-vars, digest]
dependency_graph:
  requires: []
  provides: [DIGEST_ENABLED, DIGEST_HOUR]
  affects: [app/scheduler.py (plan 03-02)]
tech_stack:
  added: []
  patterns: [env-var validation with fallback, try/except ValueError guard]
key_files:
  created: []
  modified:
    - app/config.py
decisions:
  - Placed digest config block after ABUSEIPDB_AUTO_REPORT to follow existing file ordering
  - Used try/except ValueError around int() to guard against non-integer input (SCHED-01, threat T-03-02)
  - Range check uses Python chained comparison (0 <= x <= 23) matching existing style
metrics:
  duration: "3 minutes"
  completed: "2026-04-12"
  tasks_completed: 1
  files_modified: 1
---

# Phase 03 Plan 01: Digest Scheduler Config Constants Summary

Added `DIGEST_ENABLED` (bool) and `DIGEST_HOUR` (int, 0-23) to `app/config.py` with ValueError guard and range validation, providing the config surface Plan 02's scheduler module imports.

## What Was Built

Two new environment-variable-backed constants appended to `app/config.py` after the existing `ABUSEIPDB_AUTO_REPORT` block:

- **`DIGEST_ENABLED`** — bool, default `True`. Uses the existing bool pattern (`os.getenv(...).lower() == "true"`). Controls whether the async scheduler task starts at lifespan startup; manual endpoints remain active regardless.
- **`DIGEST_HOUR`** — int 0-23, default `8` (8 AM UTC). Protected by `try/except ValueError` (prevents crash on non-integer like `"8am"`) and a range check (rejects values outside 0-23). Both invalid cases fall back to `8` with a `print()` warning.

The validation pattern mirrors `ALERT_MIN_SEVERITY` (lines 18-26 of config.py) exactly, per D-24, D-25, D-28 from the phase context.

## Validation Pattern

```python
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "true").lower() == "true"

try:
    _DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
except ValueError:
    print(f"Config warning: DIGEST_HOUR={os.getenv('DIGEST_HOUR')!r} is not a valid integer, falling back to 8")
    _DIGEST_HOUR_RAW = -1  # forces fallback in range check below

if not 0 <= _DIGEST_HOUR_RAW <= 23:
    print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range 0-23, falling back to 8")
    DIGEST_HOUR = 8
else:
    DIGEST_HOUR = _DIGEST_HOUR_RAW
```

## Existing-Deployment Behavior Preserved

- `DIGEST_ENABLED` defaults to `True` — existing deployments that never set this variable get the scheduler enabled automatically when Plan 02 wires it up.
- `DIGEST_HOUR` defaults to `8` — an 8 AM UTC digest for existing deployments with no config change needed.
- No changes to any existing config block (`ALERT_MIN_SEVERITY`, `HONEYPOT_INSTANT_BLOCK`, `ABUSEIPDB_AUTO_REPORT`, etc.).
- No new imports added to `config.py` (no `zoneinfo`, no `asyncio`, no `datetime`).

## Task Commits

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Add DIGEST_ENABLED and DIGEST_HOUR to app/config.py | 2119cb9 |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — the two constants are complete implementations, not stubs. They will be imported by `app/scheduler.py` in Plan 02.

## Threat Surface

No new network endpoints or auth paths introduced. Config validation mitigates T-03-01 (range check) and T-03-02 (ValueError guard) as specified in the plan's threat model.

## Self-Check

- [x] `app/config.py` exists and contains `DIGEST_ENABLED` and `DIGEST_HOUR`
- [x] Commit `2119cb9` is a single-file change (1 file, 20 insertions)
- [x] All four Python verification assertions pass
- [x] All acceptance criteria grep checks return expected counts
- [x] `ALERT_MIN_SEVERITY` block still present at lines 18-26 (unchanged)
- [x] No `utcnow`, `zoneinfo`, `asyncio`, or `DIGEST_TIMEZONE` in config.py

## Self-Check: PASSED
