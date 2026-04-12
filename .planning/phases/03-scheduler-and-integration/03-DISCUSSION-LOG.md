# Phase 3: Scheduler and Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-12
**Phase:** 03-scheduler-and-integration
**Areas discussed:** Scheduler loop design, Shutdown / cancellation, DIGEST_HOUR + DIGEST_ENABLED config, Timezone handling

---

## Scheduler Loop Design

| Option | Description | Selected |
|--------|-------------|----------|
| Calculate next-fire | On startup compute seconds until DIGEST_HOUR, sleep, fire, repeat. Drift-free, zoneinfo-correct. | ✓ |
| Fixed 60s poll loop | Wake every 60s, check if current hour matches, fire if not yet sent today. Simpler but noisy. | |

**User's choice:** Calculate next-fire

---

| Option | Description | Selected |
|--------|-------------|----------|
| Wait until tomorrow | If startup is past DIGEST_HOUR, schedule the next fire for the following day. | ✓ |
| Fire immediately on startup | Send a digest right away if startup is past DIGEST_HOUR. | |

**User's choice:** Wait until tomorrow

---

## Shutdown / Cancellation

| Option | Description | Selected |
|--------|-------------|----------|
| task.cancel() + await | Store the Task, cancel it in lifespan shutdown, await with CancelledError suppression. Idiomatic asyncio. | ✓ |
| asyncio.Event stop signal | Pass a stop Event into the loop; set it on shutdown. More explicit but replicates what cancel() does natively. | |

**User's choice:** task.cancel() + await

---

## DIGEST_HOUR + DIGEST_ENABLED Config

| Option | Description | Selected |
|--------|-------------|----------|
| Integer only (e.g. 8) | DIGEST_HOUR is a whole-hour integer, always fires at :00. Simple to validate and document. | ✓ |
| HH:MM format (e.g. 08:30) | Sub-hour precision. Adds parsing complexity for a feature unlikely to be needed. | |

**User's choice:** Integer only, e.g. 8

---

| Option | Description | Selected |
|--------|-------------|----------|
| Scheduler only, manual always works | DIGEST_ENABLED gates the auto-scheduler only; /api/digest/send stays available. | ✓ |
| Disables both scheduler and manual trigger | Full kill switch — both scheduler and REST endpoint gated. | |

**User's choice:** Scheduler only, manual always works

---

## Timezone Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Defer to v2, UTC only for now | Use zoneinfo.ZoneInfo("UTC") — code is correct, no DIGEST_TIMEZONE env var yet. | ✓ |
| Add DIGEST_TIMEZONE in this phase | Expose env var now since zoneinfo already handles it. | |

**User's choice:** Defer to v2, UTC only for now

---

## Claude's Discretion

- Exact function/helper names in `app/scheduler.py`
- Whether to log the next-fire time on startup (recommended yes)
- Exception handling inside the scheduler loop for failed `send_digest()` calls
- Whether to include the send result in the scheduler log output

## Deferred Ideas

- `DIGEST_TIMEZONE` env var — v2 (ADV-05)
- Sub-hour `DIGEST_HOUR` as HH:MM format — not needed
- Multiple digest frequencies — v2 (ADV-04)
