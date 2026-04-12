---
phase: 01-foundation-and-alert-routing
plan: 03
subsystem: alert-routing-wiring
tags: [alert-routing, digest, log-watcher, auto-blocker, call-sites]
one_liner: "Wired route_event gate into log_watcher and redirected auto_blocker notifications to digest_events — Phase 1 behavioral change complete"
requires:
  - "app.alert_router.route_event (from 01-02)"
  - "app.alert_router.persist_to_digest (from 01-02)"
  - "app.alert_router.get_severity (from 01-02)"
provides:
  - "Gated intruder-event path in log_watcher.process_line (immediate vs digest)"
  - "Auto-block notifications always persisted to digest_events (never immediate Telegram)"
affects:
  - app/log_watcher.py
  - app/auto_blocker.py
tech_stack:
  added: []
  patterns:
    - "Call-site gating with if/else on route_event (no double-dispatch)"
    - "Auto_blocker bypasses router entirely per D-05 (always severity='high' digest)"
    - "Reuse of existing db sessions for digest writes (no new SessionLocal)"
key_files:
  created: []
  modified:
    - app/log_watcher.py
    - app/auto_blocker.py
decisions:
  - "D-02 applied: log_watcher branches on route_event; immediate path calls send_alert_sync unchanged"
  - "D-05 applied: auto_blocker never calls route_event; all auto-block notifications → digest with severity='high'"
  - "notify_auto_block and _send_honeypot_alert fully removed (no dangling references); asyncio.create_task gymnastics in honeypot path eliminated"
  - "Digest writes reuse the session that block_ip just committed to (A3 confirmed; block_ip returns dict with 'id' key)"
metrics:
  duration: "~6 minutes"
  completed: 2026-04-12
  tasks: 2
---

# Phase 1 Plan 3: Call-Site Wiring Summary

## One-liner

Wired the `route_event` gate into `log_watcher.process_line` and redirected all auto-block notifications in `auto_blocker.py` to `digest_events` via `persist_to_digest`. Phase 1's behavioral change — immediate Telegram for critical/high, digest for medium, auto-blocks never immediate — is now live.

## What Was Built

### Task 1 — `app/log_watcher.py`

**Import added (line 12):**
```python
from app.alert_router import route_event, persist_to_digest, get_severity
```

**Call-site change (former line 133-134, now lines 133-144):**

Before:
```python
# Send Telegram alert (without Ollama - on-demand now)
send_alert_sync(event)
```

After:
```python
# Route the event: critical/high → immediate Telegram; medium → digest.
# Reuse the already-open db session (see alert_router.persist_to_digest signature).
if route_event(event) == "immediate":
    send_alert_sync(event)
else:
    persist_to_digest(
        db,
        source="intruder",
        source_id=intruder.id,
        severity=get_severity(event["reason"], event),
    )
```

Guarantees honored:
- `intruder.id` populated (prior `db.commit()` on line 131 flushed the autoincrement PK)
- Same `db` session reused (`SessionLocal()` still called exactly once, at line 96)
- `_schedule_auto_block` try/except preserved verbatim
- No double-dispatch (if/else ensures exactly one of immediate or digest per event)

Commit: `e1bc395`

### Task 2 — `app/auto_blocker.py`

**Import added (after line 15):**
```python
from app.alert_router import persist_to_digest
```

**Change 1 — `process_intruder_event` (replaces old lines 124-127):**

Before:
```python
if result.get("success"):
    # Send notification
    await notify_auto_block(ip, abuse_score, block_reason, event_count)
    return result
```

After:
```python
if result.get("success"):
    # ALERT-04: auto-block notifications go to the digest, not Telegram immediate.
    # auto_blocker skips the router entirely (D-05); always digest with high severity.
    blocked_ip_id = result.get("id")
    if blocked_ip_id is not None:
        persist_to_digest(
            db,
            source="auto_block",
            source_id=blocked_ip_id,
            severity="high",
        )
    return result
```

**Change 2 — `notify_auto_block` FULLY REMOVED** (was lines 134-152). No longer referenced anywhere.

**Change 3 — `check_and_block_honeypot` honeypot-notify block replaced** (old lines 216-238):

Before (with asyncio gymnastics):
```python
if result.get("success"):
    try:
        from app.telegram_alerter import send_alert_sync
        message = (...)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_send_honeypot_alert(ip, path, host))
            else:
                pass
        except:
            pass
    except Exception as e:
        print(f"Honeypot notification failed: {e}")

    return result
```

After:
```python
if result.get("success"):
    # ALERT-04 + D-05: honeypot auto-block notifications persisted to digest, never sent immediately.
    blocked_ip_id = result.get("id")
    if blocked_ip_id is not None:
        try:
            persist_to_digest(
                db,
                source="auto_block",
                source_id=blocked_ip_id,
                severity="high",
            )
        except Exception as e:
            print(f"Honeypot digest persist failed: {e}")

    return result
```

**Change 4 — `_send_honeypot_alert` FULLY REMOVED** (was lines 247-260). Orphaned after Change 3.

Commit: `ff68edc`

## Grep-Enforced Guarantees

Confirmed on working tree after Task 2:

| Check | Expected | Actual |
|-------|----------|--------|
| `grep -cE "send_alert(_sync)?" app/auto_blocker.py` | 0 | 0 ✅ |
| `grep -c "async def notify_auto_block" app/auto_blocker.py` | 0 | 0 ✅ |
| `grep -c "async def _send_honeypot_alert" app/auto_blocker.py` | 0 | 0 ✅ |
| `grep -c "route_event" app/auto_blocker.py` | 0 | 0 ✅ |
| `grep -c 'source="auto_block"' app/auto_blocker.py` | 2 | 2 ✅ |
| `grep -c 'severity="high"' app/auto_blocker.py` | 2 | 2 ✅ |
| `grep -c "persist_to_digest" app/auto_blocker.py` | ≥3 | 3 ✅ |
| `grep -c "notify_auto_block\|_send_honeypot_alert" app/auto_blocker.py` | 0 | 0 ✅ |
| `grep -c "SessionLocal()" app/log_watcher.py` | 1 | 1 ✅ |
| `grep -c "if route_event(event) == \"immediate\":" app/log_watcher.py` | 1 | 1 ✅ |
| `grep -c "send_alert_sync(event)" app/log_watcher.py` | 1 | 1 ✅ |
| `grep -c "source=\"intruder\"" app/log_watcher.py` | 1 | 1 ✅ |
| AST parse both files | OK | OK ✅ |

Runtime sqlalchemy/fastapi imports require the Docker container (not installed on host), matching the pattern from Plans 01-01 and 01-02. All structural acceptance criteria pass on host.

## Roadmap Phase 1 Success Criteria — Cross-Reference

| SC | Criterion | Implemented by |
|----|-----------|----------------|
| 1 | honeypot/sql_injection always immediate | `get_severity` returns `"critical"` for both (Plan 01-02); `route_event` → `"immediate"` under default `ALERT_MIN_SEVERITY=high`; `log_watcher` calls `send_alert_sync(event)` on immediate branch (Plan 01-03, line 137) |
| 2 | medium produces no immediate Telegram message | `log_watcher` else-branch at lines 138-144 calls `persist_to_digest` only; no `send_alert_sync` call for medium |
| 3 | `ALERT_MIN_SEVERITY=critical` restricts to criticals | `route_event` rank comparison (Plan 01-02) consumed unchanged by Plan 01-03's if/else |
| 4 | existing deployments still receive critical alerts | Default `ALERT_MIN_SEVERITY="high"` (Plan 01-01 config); `send_alert_sync` path preserved byte-for-byte on immediate branch |
| 5 | `digest_events` table receives medium events on detection, surviving restart | `persist_to_digest` (Plan 01-02) commits inline to SQLite; log_watcher's else-branch calls it with the reused committed session; Plan 01-01's `DigestEvent` model auto-created by `init_db()` |

## Requirements Completed

- **ALERT-04**: Auto-block notifications always digest (never immediate) — `auto_blocker.py` has zero `send_alert` references
- **DIGEST-01**: Medium events persisted to `digest_events` instead of sent immediately — `log_watcher.py` else-branch
- **DIGEST-02**: Auto-block notifications written to `digest_events` with `source="auto_block"`, `source_id=BlockedIP.id` — both call sites use `result.get("id")`

## Release Note Recommendation for Operators

> **Upgrade notice:** After upgrade, medium-severity events (`suspicious_path`, `rate_limit`) no longer send immediate Telegram messages by default. They accumulate in the new `digest_events` table for the Phase 2 daily digest. Auto-block and honeypot notifications are also now queued for the digest instead of sent per-event. To temporarily retain the pre-upgrade "notify on everything" behavior for intruder events, set `ALERT_MIN_SEVERITY=medium` (note: auto-block notifications will still route to digest — that is intentional per ALERT-04).

## Note for Phase 2 (Digest Aggregation)

- `digest_events` rows with `sent_at IS NULL` are pending. Phase 2's aggregation query selects these, groups by `source` and `severity`, and JOINs back to `intruder_events.id` (where `source='intruder'`) or `blocked_ips.id` (where `source='auto_block'`) for denormalized display fields (IP, reason, path, etc.).
- After sending, Phase 2 sets `sent_at = datetime.utcnow()` in a single UPDATE over the selected id set.
- Crash-between-commits window: an `intruder_events` row without a matching `digest_events` row is acceptable — the intruder row is still visible in the live dashboard. Phase 2 aggregation tolerates missing digest rows (it shows only what's in `digest_events`).

## Deviations from Plan

None — plan executed exactly as written. One trivial cosmetic adjustment: reworded a comment in `process_intruder_event` from `always severity="high"` to `with high severity` so the strict `grep -c 'severity="high"' = 2` acceptance criterion (code-only match) holds.

## Commits

| Task | Commit    | Message |
|------|-----------|---------|
| 1    | `e1bc395` | feat(01-03): gate log_watcher intruder events via alert_router |
| 2    | `ff68edc` | feat(01-03): redirect auto-block notifications to digest (ALERT-04, D-05) |

## Self-Check: PASSED

- `app/log_watcher.py` modified — commit `e1bc395` on branch ✅
- `app/auto_blocker.py` modified — commit `ff68edc` on branch ✅
- Both commits present in `git log` ✅
- SUMMARY.md at `.planning/phases/01-foundation-and-alert-routing/01-03-SUMMARY.md` ✅
- No files outside the two targets modified (`git diff --name-only 32a627c..HEAD` = exactly two files) ✅
